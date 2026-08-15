// Ghidra headless postScript: give a DATA type to undefined bytes that carry a positive,
// checkable data signature -- monotonic axis arrays, ASCII (plain and Bosch's bitwise-NOT
// obfuscated form), constant fills, and pointer arrays -- so they stop counting as
// "UNACCOUNTED" in CoverageStat.
//
// WHY THIS IS WRITTEN THE WAY IT IS (read before raising any threshold):
//
// The undefined-byte bucket on MED17.1.1 was originally read as "inter-function literal
// pools and alignment padding", because CoverageStat's run list is full of tiny fragments
// (7858 runs of exactly 1 byte). That reading is an ARTEFACT. CoverageStat classifies an
// undefined byte as ERASED when it is 0x00 and as a GAP when it is not, so a single
// undefined region is chopped into one fragment per non-zero byte. Enumerating maximal
// UNDEFINED runs instead (zeros included) collapses 37881 fragments into 2907 runs.
//
// Doing that reveals what the bucket actually is: 425 of those runs (277173 bytes, 71% of
// all unaccounted bytes) are WHOLE FUNCTIONS. Each sits between a function ending in
// ret/j/rfe and the next function starting at exactly the run's end; each decodes to ~100%
// instructions and terminates on a ret; and together they contain 2526 calls that land
// precisely on known function entries. They are undefined only because nothing statically
// references them -- their callers reach them through the boot-filled RAM dispatch tables
// that ecu.conf documents (the 305 unresolved `calli`). That puts them in the blind spot
// between RecoverReferencedCode (needs an existing call/jump reference: seeds=0) and
// ClaimOrphanCode (needs the bytes to be disassembled already: orphan-runs=0).
//
// So the dangerous failure mode here is not under-typing, it is TYPING CODE AS DATA, which
// is destructive and hard to undo. This script therefore:
//   - identifies data POSITIVELY (a segment is typed only if it matches a data signature),
//     never by "it wasn't claimed as code";
//   - vetoes any run whose linear decode calls known function entries at a plausible
//     density, and reports those runs as CODE-CANDIDATE instead of touching them;
//   - keeps signature thresholds where they were measured to be safe. On this image the
//     tuned settings mistype 59 bytes inside 277 KB of proven code (0.02%). Loosening
//     MIN_ASCII to 8, or admitting the 0xf0000000 CSFR range into the pointer test, was
//     measured to raise that to 286 and 578 bytes respectively -- hence the current values.
//
// BOOT-COPIED IMAGES need a second, independent guard, because the call-density veto cannot
// see them. This image copies blocks out of flash into RAM at startup and runs them there:
// a table at 0x800402ec holds (dst,src,len) records and one at 0x8000e868 holds a
// self-terminating (src,dst,len) list. A block destined for 0xc0000000 (PSPR instruction
// RAM) or 0xf0060000 (PCP code memory) is CODE lying at rest in flash. Its internal calls
// are encoded relative to its RUNTIME address, so decoded at its flash address they point
// nowhere real and the call-density veto scores it as data -- measured: the copied blocks
// score a 3-17% known-call ratio where resident code scores 73-100%. PCP code is a different
// instruction set entirely and never decodes as TriCore at all. Pass those source ranges as
// --exclude and they are left undefined. On MED17.1.1 the eight source ranges are:
//   0x800045c0:0x80004640  0x80004640:0x80004888   -> 0xc0001400/0xc0001500  PSPR code
//   0x80004888:0x8000dc90  0x8000dc90:0x8000df00
//   0x8000df00:0x8000e868                          -> 0xd00.....  .data initialiser image
//   0x80020098:0x80021368                          -> 0xc00003a0  PSPR code
//   0x80021368:0x800222e8                          -> 0xf0050000  PCP data
//   0x800222e8:0x80024f90                          -> 0xf0060000  PCP CODE
// (both chains self-validate: each src == previous src+len, and the second ends exactly at
// the table's own address). Together they hold 49174 of the unaccounted non-zero bytes.
//
// It never creates functions, only ever writes over bytes that are currently undefined and
// outside every function body, and is idempotent: a second run finds nothing left to do.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript TypeDataRegions.java <lo> <hi> \
//           [--exclude=LO:HI ...] [--report=PATH] [-n]
// -n / --dry-run reports what it would type, and the CODE-CANDIDATE runs it refuses to
// touch, without mutating. Run it first.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.ByteDataType;
import ghidra.program.model.data.CharDataType;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.data.WordDataType;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class TypeDataRegions extends GhidraScript {

    // Signature thresholds. See the header: these are measured safety points, not taste.
    private static final int MIN_FILL   = 16;  // identical non-zero bytes
    private static final int MIN_ASCII  = 12;  // printable run (8 mistypes 4.8x more code)
    private static final int MIN_MONO16 = 16;  // elements, i.e. 32 bytes
    private static final int MIN_MONO8  = 24;  // elements
    private static final int MIN_PTR    = 4;   // consecutive in-image pointers

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    private byte[] raw;
    private long base;

    private int b(long va)  { return raw[(int) (va - base)] & 0xff; }
    private int u16(long va) { return b(va) | (b(va + 1) << 8); }
    private long u32(long va) {
        return (b(va) | ((long) b(va + 1) << 8) | ((long) b(va + 2) << 16) | ((long) b(va + 3) << 24))
                & 0xffffffffL;
    }

    /** Flash image or on-chip RAM. The 0xf0000000 CSFR range is deliberately EXCLUDED: TriCore
     *  code words routinely look like CSFR addresses, and admitting it mistyped 578 code bytes. */
    private static boolean isPtr(long v) {
        return (v >= 0x80000000L && v < 0x80400000L)
            || (v >= 0xd0000000L && v < 0xd0100000L)
            || (v >= 0xd4000000L && v < 0xd4010000L);
    }

    /** Bitmap of bytes already claimed by an instruction, a defined data item, or a function
     *  body. Built from code-unit EXTENTS rather than by probing each address: Listing
     *  .getCodeUnitAt returns null for an address in the interior of a multi-byte item, so a
     *  per-address probe reads the inside of a defined array as undefined and would happily
     *  re-type the calibration maps. Building the extents once is also ~4M fewer lookups. */
    private boolean[] defined;

    private void markDefined(Listing lst, long lo, long hi) {
        defined = new boolean[(int) (hi - lo)];
        var range = currentProgram.getAddressFactory().getAddressSet(toAddr(lo), toAddr(hi - 1));
        var ii = lst.getInstructions(range, true);
        while (ii.hasNext() && !monitor.isCancelled()) {
            Instruction in = ii.next();
            long o = in.getAddress().getOffset();
            for (int k = 0; k < in.getLength(); k++) {
                int i = (int) (o - lo) + k;
                if (i >= 0 && i < defined.length) defined[i] = true;
            }
        }
        var di = lst.getDefinedData(range, true);
        while (di.hasNext() && !monitor.isCancelled()) {
            Data d = di.next();
            long o = d.getAddress().getOffset();
            for (int k = 0; k < d.getLength(); k++) {
                int i = (int) (o - lo) + k;
                if (i >= 0 && i < defined.length) defined[i] = true;
            }
        }
        for (Function f : currentProgram.getFunctionManager().getFunctions(true))
            for (Address ad : f.getBody().getAddresses(true)) {
                long o = ad.getOffset();
                if (o >= lo && o < hi) defined[(int) (o - lo)] = true;
            }
    }

    private boolean isUndef(long va) {
        int i = (int) (va - base);
        return i >= 0 && i < defined.length && !defined[i];
    }

    /** Linear TriCore decode counting calls that land on a known function entry. Zero false
     *  alarms on this image (it never flags a non-code run), so a hit is a hard veto. */
    private int callsToKnown(long s, long len, HashSet<Long> entries) {
        long p = s, end = s + len;
        int n = 0;
        while (p < end - 4) {
            int b0 = b(p);
            if (b0 == 0x6d || b0 == 0x5c || b0 == 0x61) {   // call / jl / fcall, B format
                long w = u32(p);
                long disp = ((w >> 16) & 0xFFFF) | (((w >> 8) & 0xFF) << 16);
                if ((disp & 0x800000) != 0) disp -= 0x1000000;
                if (entries.contains((p + disp * 2) & 0xffffffffL)) n++;
            }
            p += ((b0 & 1) == 0) ? 2 : 4;
        }
        return n;
    }

    private static class Seg {
        final String kind; final long start; final int len;
        Seg(String k, long s, int l) { kind = k; start = s; len = l; }
    }

    /** Split one undefined run into segments that positively match a data signature. */
    private List<Seg> classify(long s, long len) {
        List<Seg> out = new ArrayList<>();
        long p = s, end = s + len;
        while (p < end) {
            int v = b(p);
            // 0. erased flash -- skip whole zero runs (also what keeps this scan linear)
            if (v == 0) {
                long q = p;
                while (q < end && b(q) == 0) q++;
                if (q - p >= MIN_FILL) { p = q; continue; }
            }
            // 1. constant fill of a NON-ZERO byte (0xc3/0xaf pad blocks). 0x00 is erased
            //    flash and must stay erased, not become "defined data".
            if (v != 0) {
                long q = p;
                while (q < end && b(q) == v) q++;
                if (q - p >= MIN_FILL) { out.add(new Seg("FILL", p, (int) (q - p))); p = q; continue; }
            }
            // 2a. plain ASCII, NUL swallowed if present
            long q = p;
            while (q < end && b(q) >= 0x20 && b(q) <= 0x7e) q++;
            if (q - p >= MIN_ASCII) {
                int n = (int) (q - p);
                if (q < end && b(q) == 0) n++;
                out.add(new Seg("ASCII", p, n)); p += n; continue;
            }
            // 2b. bitwise-NOT obfuscated ASCII -- Bosch stores its string tables inverted
            //     (0xbd 0x90 0x8c 0x9c 0x97 0xd1 = "Bosch."), so they never match 2a.
            q = p;
            while (q < end && ((b(q) ^ 0xff) >= 0x20 && (b(q) ^ 0xff) <= 0x7e)) q++;
            if (q - p >= MIN_ASCII) {
                int n = (int) (q - p);
                if (q < end && b(q) == 0xff) n++;
                out.add(new Seg("ASCII_NOT", p, n)); p += n; continue;
            }
            // 3. monotonic non-decreasing u16 -- the breakpoint/axis arrays of a map table.
            //    Requires real variation, else an all-equal block would qualify trivially.
            if ((p & 1) == 0) {
                q = p; int prev = -1; HashSet<Integer> vals = new HashSet<>();
                while (q + 1 < end) {
                    int x = u16(q);
                    if (prev >= 0 && x < prev) break;
                    vals.add(x); prev = x; q += 2;
                }
                if (q - p >= MIN_MONO16 * 2 && vals.size() >= 8) {
                    out.add(new Seg("MONO_U16", p, (int) (q - p))); p = q; continue;
                }
            }
            // 4. monotonic non-decreasing u8 axis
            q = p; int prev = -1; HashSet<Integer> vals = new HashSet<>();
            while (q < end) {
                int x = b(q);
                if (prev >= 0 && x < prev) break;
                vals.add(x); prev = x; q++;
            }
            if (q - p >= MIN_MONO8 && vals.size() >= 8) {
                out.add(new Seg("MONO_U8", p, (int) (q - p))); p = q; continue;
            }
            // 5. run of consecutive in-image pointers
            if ((p & 3) == 0) {
                q = p; int c = 0;
                while (q + 3 < end && isPtr(u32(q))) { c++; q += 4; }
                if (c >= MIN_PTR) { out.add(new Seg("PTR", p, (int) (q - p))); p = q; continue; }
            }
            p++;
        }
        return out;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean dry = false;
        String report = null;
        List<String> pos = new ArrayList<>();
        List<long[]> excl = new ArrayList<>();
        for (String a : args) {
            if (a.equals("-n") || a.equals("--dry-run")) dry = true;
            else if (a.startsWith("--report=")) report = a.substring(9);
            else if (a.startsWith("--exclude=")) {
                String[] p = a.substring(10).split(":");
                excl.add(new long[]{hex(p[0]), hex(p[1])});
            } else pos.add(a);
        }
        if (pos.size() < 2) { println("usage: TypeDataRegions <lo> <hi> [--report=PATH] [-n]"); return; }
        long lo = hex(pos.get(0)), hi = hex(pos.get(1));

        base = lo;
        raw = new byte[(int) (hi - lo)];
        currentProgram.getMemory().getBytes(toAddr(lo), raw);

        HashSet<Long> entries = new HashSet<>();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true))
            entries.add(f.getEntryPoint().getOffset());

        Listing lst = currentProgram.getListing();
        markDefined(lst, lo, hi);

        // Fence off the boot-copied images (see header). Marking them "defined" here keeps
        // them out of the run enumeration entirely, so no signature can ever fire inside one.
        long exclBytes = 0;
        for (long[] e : excl)
            for (long q = Math.max(e[0], lo); q < Math.min(e[1], hi); q++) {
                int i = (int) (q - lo);
                if (!defined[i]) { defined[i] = true; exclBytes++; }
            }
        if (!excl.isEmpty())
            println(String.format("  excluded %d ranges (%d previously-undefined bytes fenced off "
                    + "as boot-copied images)", excl.size(), exclBytes));

        // maximal UNDEFINED runs (zeros included -- see header)
        List<long[]> runs = new ArrayList<>();
        long p = lo;
        while (p < hi && !monitor.isCancelled()) {
            if (!isUndef(p)) { p++; continue; }
            long s = p;
            while (p < hi && isUndef(p)) p++;
            runs.add(new long[]{s, p - s});
        }

        Map<String, long[]> tally = new LinkedHashMap<>();   // kind -> {bytes, nonzero, segs}
        List<String> lines = new ArrayList<>();
        List<long[]> codeCand = new ArrayList<>();
        long typedBytes = 0, typedNonZero = 0, failed = 0;
        int typedSegs = 0;

        for (long[] r : runs) {
            if (monitor.isCancelled()) break;
            long s = r[0], len = r[1];

            // veto: this run calls known functions at a code-like density -- leave it alone
            int ck = callsToKnown(s, len, entries);
            if (ck >= Math.max(1, len / 512)) { codeCand.add(new long[]{s, len, ck}); continue; }

            for (Seg g : classify(s, len)) {
                // re-check: nothing in this segment may have become defined meanwhile
                boolean clean = true;
                for (long q = g.start; q < g.start + g.len; q++)
                    if (!isUndef(q)) { clean = false; break; }
                if (!clean) continue;

                int nz = 0;
                for (long q = g.start; q < g.start + g.len; q++) if (b(q) != 0) nz++;

                if (!dry) {
                    try {
                        switch (g.kind) {
                            case "MONO_U16":
                                createData(toAddr(g.start),
                                        new ArrayDataType(WordDataType.dataType, g.len / 2, 2));
                                break;
                            case "ASCII":
                                createData(toAddr(g.start),
                                        new ArrayDataType(CharDataType.dataType, g.len, 1));
                                break;
                            case "PTR":
                                createData(toAddr(g.start),
                                        new ArrayDataType(PointerDataType.dataType, g.len / 4, 4));
                                break;
                            default:   // FILL, ASCII_NOT, MONO_U8 -- plain byte arrays
                                createData(toAddr(g.start),
                                        new ArrayDataType(ByteDataType.dataType, g.len, 1));
                        }
                    } catch (Exception e) { failed++; continue; }
                }
                // keep the bitmap in step so later segments in this pass see the new item
                for (long q = g.start; q < g.start + g.len; q++) defined[(int) (q - base)] = true;
                tally.computeIfAbsent(g.kind, k -> new long[3]);
                long[] t = tally.get(g.kind);
                t[0] += g.len; t[1] += nz; t[2]++;
                typedBytes += g.len; typedNonZero += nz; typedSegs++;
                lines.add(String.format("0x%08x,%d,%s,%d", g.start, g.len, g.kind, nz));
            }
        }

        println(String.format("TypeDataRegions [%08x,%08x): undefined-runs=%d  typed segments=%d  "
                + "bytes=%d  NON-ZERO bytes=%d  failed=%d%s",
                lo, hi, runs.size(), typedSegs, typedBytes, typedNonZero, failed, dry ? "   (DRY RUN)" : ""));
        for (Map.Entry<String, long[]> e : tally.entrySet())
            println(String.format("    %-10s segs=%-6d bytes=%-8d nonzero=%d",
                    e.getKey(), e.getValue()[2], e.getValue()[0], e.getValue()[1]));

        long ccBytes = 0; for (long[] c : codeCand) ccBytes += c[1];
        println(String.format("  CODE-CANDIDATE runs left untouched: %d (%d bytes) -- these call known "
                + "function entries; recover them as CODE, do not type them as data.",
                codeCand.size(), ccBytes));
        codeCand.sort((x, y) -> Long.compare(y[1], x[1]));
        for (int i = 0; i < Math.min(codeCand.size(), 15); i++)
            println(String.format("    @%08x len=%d callsToKnownFn=%d",
                    codeCand.get(i)[0], codeCand.get(i)[1], codeCand.get(i)[2]));

        if (report != null) {
            try (FileWriter w = new FileWriter(report)) {
                w.write("start,len,kind,nonzero\n");
                for (String l : lines) w.write(l + "\n");
                for (long[] c : codeCand)
                    w.write(String.format("0x%08x,%d,CODE_CANDIDATE,%d\n", c[0], c[1], c[2]));
            }
            println("  report -> " + report);
        }
    }
}
