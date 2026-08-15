// Ghidra headless postScript: decode the generated COM signal-descriptor table and annotate
// every signal's RAM target with its on-wire binding, so the decompiles read
//   /* COM signal: bit 60 len 3 */ DAT_d000a590
// instead of an opaque global written through a computed pointer.
//
// WHY THIS EXISTS. The COM stack binds signals to RAM in DATA, not code: the unpack routines
// walk a descriptor array and store through a pointer read from it. Ghidra therefore shows the
// target as an unreferenced global with no writer, which is what made the ACC status/state
// variables look "not statically bindable". The descriptors are plain records, so decoding them
// recovers the bindings the call graph cannot.
//
// RECORD LAYOUT (40 bytes, established on MED17.1.1 8R0907115N_0006):
//   +0x00 ptr -> const pool (max)      +0x14 mask (0xffff)   \ invariant pair =
//   +0x04 ptr -> const pool (SNA)      +0x18 RAM TARGET      / the scan signature
//   +0x08 ptr -> const pool (default)  +0x1c [start_bit, bit_len, type, 0]
//   +0x0c conversion callback  <- invariant across the WHOLE table
//   +0x10 context pointer      <- VARIES PER MESSAGE GROUP: emphatically NOT a signature.
//
// The context at +0x10 takes several values (0xd000ad2a, 0xd000aae4, 0x00000000, ...), one per
// message group. Keying the scan on it -- as an earlier version of this script did -- silently
// enumerates a single group and MISSES HALF THE TABLE, including every TX binding: 278 records
// found instead of 560. Key on the callback + mask only, and treat the context as output.
//
// The decode is self-checking: a correct format implies start_bit + bit_len <= 64 for every
// record (signals live in an 8-byte frame). The script reports the pass rate and refuses to
// annotate any record that fails, so a wrong callback/context pair shows up as a low rate
// rather than as silently bogus comments.
//
//   analyzeHeadless <proj> <name> -process -postScript DecodeComBindings.java <cb> <ctx>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class DecodeComBindings extends GhidraScript {

    /** One decoded descriptor: where the signal sits on the wire. */
    private static final class Bind {
        final int startBit, bitLen, type; final long rec;
        Bind(int s, int l, int t, long r) { startBit = s; bitLen = l; type = t; rec = r; }
        @Override public String toString() {
            return String.format("bit %d len %d type %d (desc @0x%08x)", startBit, bitLen, type, rec);
        }
    }

    private static final int REC_CB = 0x0c, REC_CTX = 0x10, REC_RAM = 0x18, REC_DESC = 0x1c;
    private static final int REC_LEN = 0x28;

    private static long le32(byte[] b, int off) {
        return ((long) (b[off] & 0xFF)) | ((long) (b[off + 1] & 0xFF) << 8)
                | ((long) (b[off + 2] & 0xFF) << 16) | ((long) (b[off + 3] & 0xFF) << 24);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("usage: DecodeComBindings <callbackAddr> [maskValue=0xffff]");
            return;
        }
        long cb = Long.decode(args[0]);
        long maskVal = args.length > 1 ? Long.decode(args[1]) : 0x0000ffffL;

        int found = 0, ok = 0, bad = 0, labelled = 0, commented = 0;
        Map<Long, List<Bind>> byTarget = new LinkedHashMap<>();
        Map<Long, Integer> ctxSeen = new LinkedHashMap<>();

        for (MemoryBlock blk : currentProgram.getMemory().getBlocks()) {
            if (!blk.isInitialized()) continue;
            int len = (int) blk.getSize();
            if (len < REC_LEN) continue;
            byte[] buf = new byte[len];
            try {
                blk.getBytes(blk.getStart(), buf);
            } catch (Exception e) {
                println("  skip block " + blk.getName() + ": " + e.getMessage());
                continue;
            }
            long blkBase = blk.getStart().getOffset();

            // The callback/context pair is the record signature; everything else is read
            // relative to it, so a record is never located by assuming the table's stride.
            for (int i = 0; i + 8 <= len - 4; i += 4) {
                if (le32(buf, i) != cb) continue;
                int recOff = i - REC_CB;
                if (recOff < 0 || recOff + REC_LEN > len) continue;
                // Signature is callback (+0x0c) + mask (+0x14). The context at +0x10 varies per
                // message group and must NOT gate the scan.
                if (le32(buf, recOff + 0x14) != maskVal) continue;
                found++;
                ctxSeen.merge(le32(buf, recOff + REC_CTX), 1, Integer::sum);

                long ram = le32(buf, recOff + REC_RAM);
                long desc = le32(buf, recOff + REC_DESC);
                int startBit = (int) (desc & 0xFF);
                int bitLen = (int) ((desc >> 8) & 0xFF);
                int type = (int) ((desc >> 16) & 0xFF);
                long recAddr = blkBase + recOff;

                // Self-check: a real signal descriptor always fits inside the 8-byte frame.
                if (bitLen == 0 || startBit + bitLen > 64) { bad++; continue; }
                ok++;

                // A RAM byte can be the target of MORE THAN ONE descriptor (platform variants
                // bind the same shadow from different bit positions). Collect first and annotate
                // per target, so a second record augments the note instead of overwriting it --
                // otherwise whichever record is scanned last silently hides the others.
                byTarget.computeIfAbsent(ram, k -> new ArrayList<>())
                        .add(new Bind(startBit, bitLen, type, recAddr));

                setPlateComment(toAddr(recAddr), String.format(
                        "COM signal descriptor -> 0x%08x, bit %d len %d type %d",
                        ram, startBit, bitLen, type));
            }
        }

        for (Map.Entry<Long, List<Bind>> e : byTarget.entrySet()) {
            long ram = e.getKey();
            List<Bind> bl = e.getValue();
            Address ramAddr;
            try {
                ramAddr = toAddr(ram);
            } catch (Exception ex) { bad++; continue; }
            if (getMemoryBlock(ramAddr) == null) { bad++; continue; }

            StringBuilder sb = new StringBuilder("COM signal binding: ");
            for (int k = 0; k < bl.size(); k++) sb.append(k > 0 ? "  |  " : "").append(bl.get(k));
            if (bl.size() > 1) sb.append("  [").append(bl.size()).append(" descriptors bind this target]");
            setEOLComment(ramAddr, sb.toString());
            commented++;

            // Never clobber a curated name from symbols_merged.csv / the A2L -- only name
            // targets Ghidra left as defaults, so step 5's names always win. A name this
            // script wrote earlier IS replaceable, so re-running on an existing project
            // converges instead of leaving a stale binding in the name.
            Symbol s = getSymbolAt(ramAddr);
            boolean ours = s != null && s.getName().startsWith("comsig_");
            if (s == null || s.getSource() == SourceType.DEFAULT || ours) {
                Bind b0 = bl.get(0);
                // Multi-bound targets get a neutral suffix rather than one arbitrary bit
                // position, so the name never asserts a binding the comment contradicts.
                String nm = bl.size() > 1
                        ? String.format("comsig_%08x_multi%d", ram, bl.size())
                        : String.format("comsig_%08x_b%dl%d", ram, b0.startBit, b0.bitLen);
                try {
                    createLabel(ramAddr, nm, true, SourceType.ANALYSIS);
                    labelled++;
                } catch (Exception ex) { /* name collision: comment already applied */ }
            }
        }

        double rate = found == 0 ? 0.0 : (100.0 * ok / found);
        long multi = byTarget.values().stream().filter(l -> l.size() > 1).count();
        println(String.format("DecodeComBindings: records=%d valid=%d (%.1f%%) rejected=%d "
                + "targets=%d multi-bound=%d labels=%d comments=%d groups=%d",
                found, ok, rate, bad, byTarget.size(), multi, labelled, commented, ctxSeen.size()));
        StringBuilder cs = new StringBuilder("DecodeComBindings: message groups (context @+0x10):");
        for (Map.Entry<Long, Integer> e : ctxSeen.entrySet())
            cs.append(String.format(" 0x%08x(%d)", e.getKey(), e.getValue()));
        println(cs.toString());
        if (found > 0 && rate < 90.0) {
            println("DecodeComBindings: WARNING low valid rate -- callback/context pair or "
                    + "record layout is probably wrong for this ECU; treat output as suspect.");
        }
    }
}
