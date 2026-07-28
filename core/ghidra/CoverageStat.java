// Report byte-level coverage of the flash image: how much is inside a function, how
// much is merely disassembled, how much is defined data, and -- the number that
// actually matters -- how much is UNDEFINED YET NON-ZERO, i.e. real content the
// analysis has not accounted for.
//
// Why "% of functions that decompiled cleanly" is the wrong metric: it only measures
// functions Ghidra already found. Bytes that never became a function are invisible to
// it. On Simos8.5 that blind spot was the whole problem. Erased Infineon flash reads
// 0x00, so undefined-zero bytes must be separated out too -- otherwise erased sectors
// masquerade as either coverage or as gaps depending on which way you round.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript CoverageStat.java [lo] [hi] [--cal=LO:HI] [--blocks]
// Defaults to the whole initialized image. --cal marks a region as calibration so it
// is reported separately instead of counting as a code gap. --blocks adds a per-64KB
// table showing where the unaccounted bytes actually live.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import java.util.ArrayList;
import java.util.List;

public class CoverageStat extends GhidraScript {

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    // byte classes
    private static final byte FN = 1, INSN = 2, DATA = 3, ERASED = 4, GAP = 5;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        long lo = -1, hi = -1, calLo = -1, calHi = -1;
        boolean perBlock = false;
        String dumpPath = null;
        List<String> pos = new ArrayList<>();
        for (String a : args) {
            if (a.startsWith("--cal=")) {
                String[] p = a.substring(6).split(":");
                calLo = hex(p[0]); calHi = hex(p[1]);
            } else if (a.equals("--blocks")) perBlock = true;
            else if (a.startsWith("--dump=")) dumpPath = a.substring(7);
            else pos.add(a);
        }
        if (pos.size() >= 2) { lo = hex(pos.get(0)); hi = hex(pos.get(1)); }
        if (lo < 0) {
            // default: the loaded flash image (initialized, non-alias, lowest block)
            for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
                if (b.isInitialized() && !b.getName().startsWith("alias_")) {
                    lo = b.getStart().getOffset(); hi = b.getEnd().getOffset() + 1; break;
                }
            }
        }
        int total = (int) (hi - lo);
        byte[] cls = new byte[total];
        Listing lst = currentProgram.getListing();
        Memory mem = currentProgram.getMemory();

        // 1. function bodies (may be non-contiguous, so walk the body address set)
        int fnCount = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            long ep = f.getEntryPoint().getOffset();
            if (ep < lo || ep >= hi) continue;
            fnCount++;
            for (Address a : f.getBody().getAddresses(true)) {
                long o = a.getOffset();
                if (o >= lo && o < hi) cls[(int) (o - lo)] = FN;
            }
        }
        // 2. instructions not claimed by any function
        var range = currentProgram.getAddressFactory().getAddressSet(toAddr(lo), toAddr(hi - 1));
        var ii = lst.getInstructions(range, true);
        while (ii.hasNext() && !monitor.isCancelled()) {
            Instruction in = ii.next();
            long o = in.getAddress().getOffset();
            for (int k = 0; k < in.getLength(); k++) {
                int idx = (int) (o - lo) + k;
                if (idx >= 0 && idx < total && cls[idx] == 0) cls[idx] = INSN;
            }
        }
        // 3. defined data
        var di = lst.getDefinedData(range, true);
        while (di.hasNext() && !monitor.isCancelled()) {
            Data d = di.next();
            long o = d.getAddress().getOffset();
            for (int k = 0; k < d.getLength(); k++) {
                int idx = (int) (o - lo) + k;
                if (idx >= 0 && idx < total && cls[idx] == 0) cls[idx] = DATA;
            }
        }
        // 4. everything left: erased (0x00) vs a genuine unaccounted gap
        byte[] raw = new byte[total];
        mem.getBytes(toAddr(lo), raw);
        for (int i = 0; i < total; i++) {
            if (cls[i] == 0) cls[i] = (raw[i] == 0) ? ERASED : GAP;
        }

        long[] n = new long[6];
        long[] nCal = new long[6];
        for (int i = 0; i < total; i++) {
            long va = lo + i;
            boolean isCal = calLo >= 0 && va >= calLo && va < calHi;
            (isCal ? nCal : n)[cls[i]]++;
        }
        long codeTotal = n[FN] + n[INSN] + n[DATA] + n[ERASED] + n[GAP];
        long calTotal = nCal[FN] + nCal[INSN] + nCal[DATA] + nCal[ERASED] + nCal[GAP];

        println(String.format("=== image [%08x,%08x) = %d bytes (%.2f MB), %d functions ===",
                lo, hi, total, total / 1048576.0, fnCount));
        println("");
        println(String.format("CODE/DATA REGION (%d bytes, %.1f%% of image)", codeTotal, pct(codeTotal, total)));
        report("  in-function (decompiled)", n[FN], codeTotal);
        report("  disassembled, NO function", n[INSN], codeTotal);
        report("  defined data", n[DATA], codeTotal);
        report("  erased (0x00 fill)", n[ERASED], codeTotal);
        report("  UNACCOUNTED (undefined, non-zero)", n[GAP], codeTotal);
        if (calTotal > 0) {
            println("");
            println(String.format("CALIBRATION REGION [%08x,%08x) (%d bytes, %.1f%% of image)",
                    calLo, calHi, calTotal, pct(calTotal, total)));
            report("  defined data (typed maps)", nCal[DATA], calTotal);
            report("  erased (0x00 fill)", nCal[ERASED], calTotal);
            report("  undefined, non-zero", nCal[GAP], calTotal);
            report("  in-function / disassembled", nCal[FN] + nCal[INSN], calTotal);
        }
        println("");
        long live = total - n[ERASED] - nCal[ERASED];
        println(String.format("LIVE CONTENT (excludes erased): %d bytes", live));
        report("  accounted for", live - n[GAP] - nCal[GAP], live);
        report("  NOT accounted for", n[GAP] + nCal[GAP], live);

        if (perBlock) {
            println("");
            println("=== per-64KB block (bytes) ===");
            println("  vaddr     in-fn   insn-no-fn   data   unaccounted   erased");
            for (long b = lo; b < hi; b += 0x10000) {
                long[] c = new long[6];
                for (int i = (int) (b - lo); i < Math.min(total, (int) (b - lo) + 0x10000); i++) c[cls[i]]++;
                if (c[ERASED] == 0x10000) continue;   // fully erased sector: nothing to say
                println(String.format("  %08x %7d %10d %7d %11d %8d",
                        b, c[FN], c[INSN], c[DATA], c[GAP], c[ERASED]));
            }
        }

        // every contiguous unaccounted run, with a byte sample, so the mix (padding vs
        // data table vs real code) can be quantified instead of guessed at
        if (dumpPath != null) {
            try (java.io.FileWriter fw = new java.io.FileWriter(dumpPath)) {
                fw.write("start,len,first16hex\n");
                int k = 0;
                while (k < total) {
                    if (cls[k] != GAP) { k++; continue; }
                    int s = k;
                    while (k < total && cls[k] == GAP) k++;
                    StringBuilder sb = new StringBuilder();
                    for (int q = s; q < Math.min(k, s + 16); q++) sb.append(String.format("%02x", raw[q]));
                    fw.write(String.format("0x%08x,%d,%s\n", lo + s, k - s, sb));
                }
            }
            println("unaccounted runs dumped -> " + dumpPath);
        }

        // largest contiguous unaccounted runs -- the actionable list
        println("");
        println("=== largest contiguous UNACCOUNTED runs (>=128 bytes) ===");
        List<long[]> gaps = new ArrayList<>();
        int i = 0;
        while (i < total) {
            if (cls[i] != GAP) { i++; continue; }
            int s = i;
            while (i < total && cls[i] == GAP) i++;
            if (i - s >= 128) gaps.add(new long[]{lo + s, i - s});
        }
        gaps.sort((x, y) -> Long.compare(y[1], x[1]));
        long gsum = 0; for (long[] g : gaps) gsum += g[1];
        println(String.format("  %d runs >=128 bytes, %d bytes total", gaps.size(), gsum));
        for (int k = 0; k < Math.min(gaps.size(), 25); k++) {
            println(String.format("  @%08x  len=%d", gaps.get(k)[0], gaps.get(k)[1]));
        }
    }

    private static double pct(long a, long b) { return b == 0 ? 0 : 100.0 * a / b; }

    private void report(String label, long v, long tot) {
        println(String.format("%-38s %9d  %5.1f%%", label, v, pct(v, tot)));
    }
}
