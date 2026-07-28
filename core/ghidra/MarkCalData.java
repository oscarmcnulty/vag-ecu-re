// Ghidra headless postScript: data-type the calibration region so the "undefined" coverage number
// reflects only real CODE, and so a subsequent code-recovery pass won't disassemble maps as garbage.
//
// For each still-undefined gap in the given range(s), decide CODE vs DATA by a robust discriminator:
// linear-decode the gap (TriCore len = 2 if byte0 even else 4) and count CALL/JL/FCALL (op 0x6d/0x5c/
// 0x61) whose B-format target is a KNOWN function entry. Real code calls known functions; calibration
// maps essentially never produce a valid call to a real entry. Gaps with >=1 such call are LEFT
// undefined (candidate code for the recovery pass); gaps with 0 are DEFINED as data (s16 word array,
// the dominant cal element type) so they count as "defined data", not "undefined".
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript MarkCalData.java <lo1> <hi1> [<lo2> <hi2> ...] [--dry]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.WordDataType;
import ghidra.program.model.data.ByteDataType;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.Memory;
import java.util.*;

public class MarkCalData extends GhidraScript {
    long BASE = 0x80000000L, LO = 0x80020000L, HI = 0x80200000L;

    boolean isDefined(Address a) {
        CodeUnit cu = currentProgram.getListing().getCodeUnitAt(a);
        if (cu == null) return true; // treat unmapped as "stop"
        if (cu instanceof ghidra.program.model.listing.Instruction) return true;
        if (cu instanceof Data && ((Data)cu).isDefined()) return true;
        return false;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean dry = false;
        List<long[]> ranges = new ArrayList<>();
        List<Long> nums = new ArrayList<>();
        for (String a : args) {
            if (a.equals("--dry")) { dry = true; continue; }
            nums.add(currentProgram.getAddressFactory().getAddress(a).getOffset());
        }
        for (int i = 0; i + 1 < nums.size(); i += 2) ranges.add(new long[]{nums.get(i), nums.get(i+1)});

        // known function entry set
        HashSet<Long> entries = new HashSet<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true))
            entries.add(f.getEntryPoint().getOffset());

        Memory mem = currentProgram.getMemory();
        long dataBytes = 0, codeBytes = 0; int dataGaps = 0, codeGaps = 0;
        List<long[]> codeCand = new ArrayList<>();

        for (long[] r : ranges) {
            long a = r[0], hi = r[1];
            while (a < hi) {
                Address ad = toAddr(a);
                if (isDefined(ad)) { a += 2; continue; }
                // find gap extent [a, g)
                long g = a;
                while (g < hi && !isDefined(toAddr(g))) g += 1;
                long len = g - a;
                if (len < 8) { a = g; continue; }
                // discriminator: count calls-to-known-fn by linear decode
                int callsKnown = 0, steps = 0;
                long p = a;
                while (p < g - 4 && steps < 20000) {
                    int b0 = mem.getByte(toAddr(p)) & 0xff;
                    if (b0 == 0x6d || b0 == 0x5c || b0 == 0x61) {
                        // B-format: W little-endian; disp24 = (W>>16)&0xFFFF | ((W>>8)&0xFF)<<16
                        long W = (mem.getByte(toAddr(p)) & 0xffL)
                               | ((mem.getByte(toAddr(p+1)) & 0xffL) << 8)
                               | ((mem.getByte(toAddr(p+2)) & 0xffL) << 16)
                               | ((mem.getByte(toAddr(p+3)) & 0xffL) << 24);
                        long disp = ((W >> 16) & 0xFFFF) | (((W >> 8) & 0xFF) << 16);
                        if ((disp & 0x800000) != 0) disp -= 0x1000000;
                        long tgt = (p + disp * 2) & 0xffffffffL;
                        if (entries.contains(tgt)) callsKnown++;
                    }
                    p += ((b0 & 1) == 0) ? 2 : 4;
                    steps++;
                }
                // Require call-to-known-fn DENSITY, not a single hit: a 4000-entry map will have a
                // coincidental match, but real code calls known fns densely. Threshold scales with size.
                long need = Math.max(3, len / 256);
                if (callsKnown >= need) { codeGaps++; codeBytes += len; codeCand.add(new long[]{a, len, callsKnown}); }
                else {
                    dataGaps++; dataBytes += len;
                    if (!dry) {
                        // define as s16 word array (trailing odd byte as byte array)
                        long wlen = len & ~1L;
                        try {
                            clearListing(toAddr(a), toAddr(a + len - 1));
                            if (wlen >= 2)
                                createData(toAddr(a), new ArrayDataType(WordDataType.dataType, (int)(wlen/2), 2));
                            if (wlen < len)
                                createData(toAddr(a + wlen), new ArrayDataType(ByteDataType.dataType, (int)(len - wlen), 1));
                        } catch (Exception e) { /* leave undefined on failure */ }
                    }
                }
                a = g;
            }
        }
        println(String.format("MarkCalData: DATA gaps=%d (%d bytes) defined%s; CODE-candidate gaps=%d (%d bytes) left undefined",
                dataGaps, dataBytes, dry ? " [DRY]" : "", codeGaps, codeBytes));
        println("=== CODE-candidate gaps in range (calls-to-known-fn >=1) ===");
        codeCand.sort((x,y)->Long.compare(y[1],x[1]));
        for (long[] c : codeCand)
            println(String.format("  @%08x len=%d callsKnown=%d", c[0], c[1], c[2]));
    }
}
