// Ghidra headless postScript: recover functions that are UNDEFINED *and* UNREFERENCED, by using the
// bracketing of the surrounding code as the seed instead of a reference.
//
// WHY. Three recovery passes already exist and every one of them structurally misses this population:
//   ClaimOrphanCode        needs the bytes to be disassembled already   -> orphan-runs=0
//   RecoverReferencedCode  needs an incoming call/jump reference        -> seeds=0
//   RecoverPointerTargets  needs a pointer table that points at it      -> found 3 functions
// Code reached only through a boot-filled RAM table, or not reached at all in this calibration, has
// neither property. On MED17.1.1 that hid ~178 KB of resident TriCore code behind a coverage report
// that said "84.5% accounted", because the leftover read as "undefined data".
//
// It also hid behind a measurement artefact worth recording: CoverageStat calls an undefined byte
// ERASED when it is 0x00 and a GAP otherwise, so a single undefined *region* is reported as one
// fragment per non-zero byte. Real code is full of 0x00 (`91 10 00 fd` = movh.a), so code shatters
// into exactly the 1-2 byte fragments that look like literal-pool padding. Enumerating maximal
// undefined runs WITH the zeros folded in collapsed 37,881 "fragments" into 2,907 real runs.
//
// The seed here is positional, and it is strong: a compiler lays functions out back to back, so a
// genuine function body is preceded by a flow terminator (the previous function's `ret`/`j`/`rfe`)
// and ends exactly where the next known function begins. Measured on this image: of 465 candidate
// runs, 465 were preceded by a terminator with ZERO fall-throughs, 96.77% of their bytes decoded as
// instructions, and 2,526 of 4,264 decoded calls landed precisely on known function entries.
//
// GUARDS (each one exists because something real would otherwise be misclassified):
//   --exclude=LO:HI   Boot-copied LOAD IMAGES must be excluded by range, not by score. A copied block
//                     encodes its calls relative to its RUNTIME address, so decoded at its flash
//                     address it scores 3-17% known-call ratio -- indistinguishable from data by any
//                     scoring test, and one of those blocks is PCP2 coprocessor microcode in a
//                     different instruction set entirely. Pass every copy-table source range here.
//   --min-call-ratio  resident code calls known functions (73-100%); data does not (~0%).
//   --min-decode      fraction of the run's bytes that must decode as instructions.
//   terminator test   the byte before the run must end a flow, and the run must end on one too.
//   rollback          a created function whose body decodes to < --min bytes is removed again.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript RecoverBracketedCode.java <lo> <hi> [entriesOut] \
//           [--exclude=LO:HI ...] [--min-run=64] [--min-decode=90] [--min-call-ratio=40] \
//           [--min=16] [--min-nonzero=80] [-n]
// -n / --dry-run reports candidates without mutating. ALWAYS run that first and read the list.
//@category VAG-RE
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.FlowType;

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

public class RecoverBracketedCode extends GhidraScript {

    private long lo, hi;
    private int minRun = 64, minDecodePct = 90, minCallRatio = 40, minBody = 16, minNonZeroPct = 80;
    private boolean dry = false;
    private final List<long[]> excludes = new ArrayList<>();

    private boolean excluded(long a, long b) {
        for (long[] e : excludes) if (a < e[1] && b > e[0]) return true;   // any overlap
        return false;
    }

    /** A flow terminator is what the compiler leaves at the end of the PREVIOUS function. */
    private boolean isTerminator(Instruction in) {
        if (in == null) return false;
        FlowType ft = in.getFlowType();
        return ft.isTerminal() || (ft.isJump() && !ft.isConditional());
    }

    /** Last instruction that ends at-or-before `a`, walking back a little. */
    private Instruction instrEndingAt(Address a) {
        Instruction in = getInstructionBefore(a);
        if (in == null) return null;
        return in.getMaxAddress().add(1).equals(a) ? in : null;
    }

    private boolean undefinedAt(Address a) {
        if (getFunctionContaining(a) != null) return false;
        if (getInstructionAt(a) != null) return false;
        CodeUnit cu = currentProgram.getListing().getCodeUnitContaining(a);
        if (cu == null) return false;
        return (cu instanceof ghidra.program.model.listing.Data)
                && !((ghidra.program.model.listing.Data) cu).isDefined();
    }

    /** Trial-decode the run in a scratch pass: returns {bytesDecoded, calls, callsOnKnownEntry, endsOnTerminator}. */
    private long[] trial(Address start, long len) throws Exception {
        long decoded = 0, calls = 0, known = 0, endsTerm = 0;
        Address p = start, end = start.add(len);
        // disassemble() is destructive, so probe with the pseudo-disassembler instead.
        ghidra.app.util.PseudoDisassembler pd = new ghidra.app.util.PseudoDisassembler(currentProgram);
        while (p.compareTo(end) < 0) {
            Instruction in;
            try { in = pd.disassemble(p); } catch (Exception e) { break; }
            if (in == null) break;
            int n = in.getLength();
            decoded += n;
            FlowType ft = in.getFlowType();
            if (ft.isCall()) {
                calls++;
                for (Address t : in.getFlows()) {
                    Function f = getFunctionAt(t);
                    if (f != null) { known++; break; }
                }
            }
            endsTerm = isTerminator(in) ? 1 : 0;
            p = p.add(n);
        }
        return new long[]{decoded, calls, known, endsTerm};
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) { println("usage: RecoverBracketedCode <lo> <hi> [out] [opts]"); return; }
        lo = Long.decode(args[0]); hi = Long.decode(args[1]);
        String out = null;
        for (int i = 2; i < args.length; i++) {
            String s = args[i];
            if (s.equals("-n") || s.equals("--dry-run")) dry = true;
            else if (s.startsWith("--exclude=")) {
                String[] p = s.substring(10).split(":");
                excludes.add(new long[]{Long.decode(p[0]), Long.decode(p[1])});
            }
            else if (s.startsWith("--min-run=")) minRun = Integer.parseInt(s.substring(10));
            else if (s.startsWith("--min-decode=")) minDecodePct = Integer.parseInt(s.substring(13));
            else if (s.startsWith("--min-call-ratio=")) minCallRatio = Integer.parseInt(s.substring(17));
            else if (s.startsWith("--min=")) minBody = Integer.parseInt(s.substring(6));
            else if (s.startsWith("--min-nonzero=")) minNonZeroPct = Integer.parseInt(s.substring(14));
            else if (!s.startsWith("-")) out = s;
        }

        // --- pass 1: maximal undefined runs, zeros folded in (NOT the per-byte fragment view) ---
        List<long[]> runs = new ArrayList<>();
        long a = lo;
        while (a < hi) {
            Address ad = toAddr(a);
            MemoryBlock b = getMemoryBlock(ad);
            if (b == null || !b.isInitialized()) { a += 2; continue; }
            if (!undefinedAt(ad)) { a += 1; continue; }
            long s = a;
            while (a < hi && undefinedAt(toAddr(a))) a += 1;
            if (a - s >= minRun) runs.add(new long[]{s, a});
        }
        println("maximal undefined runs >= " + minRun + " bytes: " + runs.size());

        // --- pass 2: bracket + decode + call-ratio ---
        int nExcl = 0, nNoTerm = 0, nDecode = 0, nRatio = 0, nSparse = 0, created = 0;
        long madeBytes = 0;
        List<Address> keep = new ArrayList<>();
        for (long[] r : runs) {
            if (excluded(r[0], r[1])) { nExcl++; continue; }
            // ERASED-FLASH GUARD. Infineon erased flash reads 0x00, and 0x00 bytes decode as valid
            // TriCore instructions -- so a mostly-erased run scores ~99% "decoded" and would be
            // claimed wholesale. Without this, the tail of the code region (407,976 bytes up to the
            // cal window) came through as a single candidate. Real code is 80-100% non-zero.
            long nz = 0;
            for (long q = r[0]; q < r[1]; q++) {
                try { if (getByte(toAddr(q)) != 0) nz++; } catch (Exception e) { }
            }
            if (nz * 100 < (long) minNonZeroPct * (r[1] - r[0])) { nSparse++; continue; }
            Address start = toAddr(r[0]);
            if (!isTerminator(instrEndingAt(start))) { nNoTerm++; continue; }
            long len = r[1] - r[0];
            long[] t = trial(start, len);
            if (t[0] * 100 < (long) minDecodePct * len) { nDecode++; continue; }
            if (t[1] > 0 && t[2] * 100 < (long) minCallRatio * t[1]) { nRatio++; continue; }
            keep.add(start);
            println(String.format("  candidate 0x%s len=%d decoded=%d%% calls=%d known=%d",
                    start, len, (int) (t[0] * 100 / len), t[1], t[2]));
        }

        if (!dry) {
            for (Address s : keep) {
                if (getFunctionContaining(s) != null) continue;
                clearListing(s);
                disassemble(s);
                if (getInstructionAt(s) == null) continue;
                if (!new CreateFunctionCmd(s).applyTo(currentProgram, monitor)) continue;
                Function f = getFunctionAt(s);
                if (f == null) continue;
                long n = f.getBody().getNumAddresses();
                if (n < minBody) { removeFunctionAt(s); continue; }
                created++; madeBytes += n;
            }
            if (out != null) {
                PrintWriter pw = new PrintWriter(out);
                pw.println("# Functions recovered from bracketed undefined runs. RE metadata only.");
                for (Address s : keep) if (getFunctionAt(s) != null) pw.println(s.toString());
                pw.close();
            }
        }
        println(String.format(
            "RecoverBracketedCode [%x,%x): runs=%d excluded=%d sparse=%d no-terminator=%d low-decode=%d "
            + "low-call-ratio=%d candidates=%d created=%d bytes=%d%s",
            lo, hi, runs.size(), nExcl, nSparse, nNoTerm, nDecode, nRatio, keep.size(), created, madeBytes,
            dry ? "  (DRY RUN)" : ""));
        println("RBCDONE");
    }
}
