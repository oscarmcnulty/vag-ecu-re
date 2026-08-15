// Ghidra headless postScript: recover functions reachable ONLY through a function-pointer
// table, by validating each candidate table against the functions it already hits.
//
// WHY. RecoverReferencedCode seeds from references that already exist, so it cannot see a
// handler whose only entry is a slot in a dispatch table: the table is raw DATA, Ghidra makes
// no reference out of it, and the target therefore stays undefined AND unreferenced. On this
// image RecoverReferencedCode reports seeds=0 while 325 computed call sites remain unresolved
// -- that gap is exactly what this closes. It matters doubly for tables that live in RAM
// (filled at boot from a flash pointer array): the `calli` can NEVER be resolved statically,
// so the flash array is the only handle on those handlers.
//
// The danger is obvious -- any 4 bytes that happen to look like 0x800xxxxx would "recover" a
// function out of a calibration axis. So a run is only trusted when it VALIDATES ITSELF:
//
//   * a run is >= --min-run consecutive u32s that all look like code pointers (in range, even);
//   * at least --confirm (default 60%) of the run's targets must ALREADY be known functions;
//   * only then are the remaining targets created, and each is still subject to the same
//     guards RecoverReferencedCode uses: erased/all-zero targets refused, and a created
//     function rolled back unless its body decodes to >= --min bytes.
//
// A table of calibration constants cannot pass the confirm test, because none of its "targets"
// is a function. A real dispatch table passes trivially, because most of its handlers were
// already found by direct calls.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript RecoverPointerTargets.java <lo> <hi> \
//           [entriesOut] [--min-run=4] [--confirm=60] [--min=8] [--near=0x1000] [-n]
// -n / --dry-run reports what it would recover without touching the program. Run it first.
//@category VAG-RE
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public class RecoverPointerTargets extends GhidraScript {

    private long lo, hi;
    private int minRun = 4, confirmPct = 60, minBody = 8;
    private long nearWin = 0x1000;
    private boolean dry = false;

    private boolean looksCodePtr(long p) {
        return p >= lo && p < hi && (p & 1) == 0;
    }

    /** true if the address is inside an existing function (entry or body). */
    private boolean inFunction(Address a) {
        return getFunctionContaining(a) != null;
    }

    private boolean erasedAt(Address a) throws Exception {
        Memory mem = currentProgram.getMemory();
        byte[] b = new byte[8];
        try { mem.getBytes(a, b); } catch (Exception e) { return true; }
        boolean allZero = true, allFF = true;
        for (byte x : b) { if (x != 0) allZero = false; if (x != (byte) 0xff) allFF = false; }
        return allZero || allFF;
    }

    /** Create a function at `a`, rolling back if the body is too small to be real. */
    private int tryCreate(Address a) throws Exception {
        MemoryBlock b = getMemoryBlock(a);
        if (b == null || !b.isInitialized()) return 0;
        if (erasedAt(a)) return 0;
        CodeUnit cu = currentProgram.getListing().getCodeUnitAt(a);
        if (cu == null) return 0;
        if (getInstructionAt(a) == null) {
            clearListing(a);
            disassemble(a);
            Instruction in = getInstructionAt(a);
            if (in == null) return 0;
        }
        CreateFunctionCmd cmd = new CreateFunctionCmd(a);
        if (!cmd.applyTo(currentProgram, monitor)) return 0;
        Function f = getFunctionAt(a);
        if (f == null) return 0;
        long len = f.getBody().getNumAddresses();
        if (len < minBody) { removeFunctionAt(a); return 0; }
        return (int) len;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) { println("usage: RecoverPointerTargets <lo> <hi> [out] [opts]"); return; }
        lo = Long.decode(args[0]); hi = Long.decode(args[1]);
        String out = null;
        for (int i = 2; i < args.length; i++) {
            String s = args[i];
            if (s.equals("-n") || s.equals("--dry-run")) dry = true;
            else if (s.startsWith("--min-run=")) minRun = Integer.parseInt(s.substring(10));
            else if (s.startsWith("--confirm=")) confirmPct = Integer.parseInt(s.substring(10));
            else if (s.startsWith("--min=")) minBody = Integer.parseInt(s.substring(6));
            else if (s.startsWith("--near=")) nearWin = Long.decode(s.substring(7));
            else if (!s.startsWith("-")) out = s;
        }

        Memory mem = currentProgram.getMemory();
        List<long[]> run = new ArrayList<>();          // (slotAddr, target)
        Set<Address> created = new LinkedHashSet<>();
        int tables = 0, rejected = 0, candidates = 0, madeBytes = 0;

        // PASS 1 -- collect every pointer run, so pass 2 can refuse targets that land INSIDE
        // one. A slot pointing into another pointer array is a table-of-tables entry, not a
        // handler; without this guard the confirm test still passes (the enclosing run is full
        // of genuine function pointers) and we would create bogus functions over table data.
        List<List<long[]>> allRuns = new ArrayList<>();
        long addr = lo;
        while (addr < hi) {
            long p;
            try { p = mem.getInt(toAddr(addr)) & 0xffffffffL; }
            catch (Exception e) { p = 0; }
            if (looksCodePtr(p)) {
                run.add(new long[]{addr, p});
            } else if (!run.isEmpty()) {
                if (run.size() >= minRun) allRuns.add(new ArrayList<>(run));
                run.clear();
            }
            addr += 4;
        }
        if (run.size() >= minRun) allRuns.add(new ArrayList<>(run));
        for (List<long[]> r : allRuns) {
            runLo.add(r.get(0)[0]);
            runHi.add(r.get(r.size() - 1)[0] + 4);
        }

        // PASS 2 -- validate each run against the functions it already hits, then create.
        for (List<long[]> r : allRuns) processRun(r, created);

        // Stats are gathered inside processRun via the fields below.
        tables = nTables; rejected = nRejected; candidates = nCandidates; madeBytes = nBytes;

        if (out != null && !dry) {
            PrintWriter pw = new PrintWriter(out);
            pw.println("# Functions recovered from validated pointer tables. RE metadata only.");
            for (Address a : created) pw.println(a.toString());
            pw.close();
        }
        println(String.format(
            "RecoverPointerTargets [%x,%x): runs>=%d validated=%d rejected=%d "
            + "candidate-targets=%d non-code-skipped=%d created=%d bytes=%d%s",
            lo, hi, minRun, tables, rejected, candidates, nNested, created.size(), madeBytes,
            dry ? "  (DRY RUN)" : ""));
        println("RPTDONE");
    }

    private int nTables = 0, nRejected = 0, nCandidates = 0, nBytes = 0, nNested = 0;
    private final List<Long> runLo = new ArrayList<>(), runHi = new ArrayList<>();

    /**
     * true if a known function lives within `nearWin` bytes of `a`.
     *
     * Second false-positive class the run guard misses: slots pointing into the ROM constant
     * pool or into an axis-table region. Those areas contain no functions at all, whereas a
     * genuine handler is always embedded in a code neighbourhood -- its neighbours were found
     * by direct calls. Cheap, and it does not assume any fixed code/data split.
     */
    private boolean nearCode(Address a) {
        Function before = getFunctionBefore(a), after = getFunctionAfter(a);
        long db = before == null ? Long.MAX_VALUE
                : Math.abs(a.getOffset() - before.getEntryPoint().getOffset());
        long da = after == null ? Long.MAX_VALUE
                : Math.abs(after.getEntryPoint().getOffset() - a.getOffset());
        return Math.min(db, da) <= nearWin;
    }

    /** true if `p` lands inside a detected pointer run -- i.e. it is a table pointer. */
    private boolean insideAnyRun(long p) {
        for (int i = 0; i < runLo.size(); i++)
            if (p >= runLo.get(i) && p < runHi.get(i)) return true;
        return false;
    }

    private void processRun(List<long[]> run, Set<Address> created) throws Exception {
        if (run.size() < minRun) return;
        int known = 0;
        List<Address> unknown = new ArrayList<>();
        for (long[] e : run) {
            Address t = toAddr(e[1]);
            if (inFunction(t)) known++;
            else if (insideAnyRun(e[1]) || !nearCode(t)) nNested++;   // table/pool slot, not code
            else unknown.add(t);
        }
        if (known * 100 < confirmPct * run.size()) { nRejected++; return; }
        nTables++;
        nCandidates += unknown.size();
        for (Address t : unknown) {
            if (created.contains(t)) continue;
            if (dry) {
                MemoryBlock b = getMemoryBlock(t);
                if (b != null && b.isInitialized() && !erasedAt(t)) {
                    created.add(t);
                    println(String.format("  would create 0x%s (table @0x%x, %d/%d confirmed)",
                            t, run.get(0)[0], known, run.size()));
                }
                continue;
            }
            int len = tryCreate(t);
            if (len > 0) { created.add(t); nBytes += len; }
        }
    }
}
