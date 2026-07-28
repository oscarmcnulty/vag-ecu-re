// Ghidra headless postScript: create functions over code that IS disassembled but
// belongs to no function ("orphan code"), so it stops being invisible to decompilation.
//
// This is a different gap from RecoverGapWalk/RecoverGapStructural, which recover
// UNDEFINED bytes. Here the bytes are already valid instructions -- auto-analysis
// disassembled them (usually by following a jump/dispatch edge) but never created a
// function, so DecompileAll never emits any C for them and they never appear in the
// manifest. They are simply absent from the corpus, with nothing reporting the loss.
// On MED17.1.1 that was 621 KB, more than half of all disassembled bytes in the
// 0x80140000-0x80310000 program blocks.
//
// Entry-point heuristic, applied per maximal run of orphan instructions:
//   - the run start, and
//   - any instruction inside the run that is the target of a call/jump reference, and
//   - any instruction immediately following a flow terminator (ret/rfe/unconditional
//     jump with no fall-through) -- i.e. where the previous function clearly ended.
// After creating a function, scanning resumes past its body, so one call claims a
// whole function rather than one instruction. The whole scan is then repeated until a
// pass claims nothing new, because each created function can expose further orphan
// code in the holes of its (usually non-contiguous) body.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ClaimOrphanCode.java <lo> <hi> [entriesOut] [-n]
// -n / --dry-run reports the runs (and what it would create) without mutating.
//@category VAG-RE
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.List;

public class ClaimOrphanCode extends GhidraScript {

    private static final int MAX_PASSES = 20;   // dry runs never converge (nothing is created)

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    /** true if control cannot fall through this instruction (so the next one starts fresh). */
    private static boolean terminates(Instruction in) {
        return !in.hasFallthrough();
    }

    private boolean isCalledOrJumped(Address a) {
        for (Reference r : getReferencesTo(a)) {
            RefType t = r.getReferenceType();
            if (t.isCall() || t.isJump()) return true;
        }
        return false;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean dry = false;
        String out = null;
        List<String> pos = new ArrayList<>();
        for (String a : args) {
            if (a.equals("-n") || a.equals("--dry-run")) dry = true;
            else if (a.startsWith("0x") || a.matches("[0-9a-fA-F]{6,}")) pos.add(a);
            else out = a;
        }
        if (pos.size() < 2) { println("usage: ClaimOrphanCode <lo> <hi> [entriesOut] [-n]"); return; }
        long lo = hex(pos.get(0)), hi = hex(pos.get(1));

        Listing lst = currentProgram.getListing();
        int runs = 0, created = 0, failed = 0;
        long orphanBytes = 0, claimedBytes = 0;
        List<String> newEntries = new ArrayList<>();

        // Creating a function can EXPOSE new orphan code: the new body is frequently
        // non-contiguous, and the holes between its ranges may hold further unclaimed
        // instructions. A single pass therefore always leaves a tail behind (measured:
        // 60 -> 40 -> 33 functions on successive manual passes). Iterate to a fixpoint.
        int pass = 0;
        for (; pass < MAX_PASSES; pass++) {
        int createdThisPass = created;
        runs = 0; orphanBytes = 0;

        Address a = toAddr(lo);
        Instruction in = lst.getInstructionAt(a);
        if (in == null) in = lst.getInstructionAfter(a);

        boolean prevTerminated = true;   // start of range counts as "fresh"
        boolean inRun = false;

        while (in != null && !monitor.isCancelled() && in.getAddress().getOffset() < hi) {
            Address ia = in.getAddress();
            Function owner = getFunctionContaining(ia);

            if (owner != null) {
                // Skip to the end of the body RANGE containing this address -- NOT to the
                // body's max address. TriCore function bodies are frequently non-contiguous
                // (out-of-line blocks), and jumping to the max address steps over any orphan
                // instructions sitting in the holes between a body's ranges, leaving them
                // silently unclaimed. That bug hid 14.5 KB on the first MED17.1.1 pass.
                inRun = false;
                prevTerminated = true;
                var rng = owner.getBody().getRangeContaining(ia);
                Address end = (rng != null) ? rng.getMaxAddress() : owner.getBody().getMaxAddress();
                in = lst.getInstructionAfter(end);
                continue;
            }

            orphanBytes += in.getLength();
            boolean startHere = !inRun || prevTerminated || isCalledOrJumped(ia);
            if (!inRun) runs++;
            inRun = true;

            if (startHere) {
                if (dry) {
                    created++;
                    newEntries.add("0x" + ia);
                } else {
                    new CreateFunctionCmd(ia).applyTo(currentProgram, monitor);
                    Function f = getFunctionAt(ia);
                    if (f != null) {
                        created++;
                        newEntries.add("0x" + ia);
                        claimedBytes += f.getBody().getNumAddresses();
                        // resume after the body we just created
                        in = lst.getInstructionAfter(f.getBody().getMaxAddress());
                        prevTerminated = true;
                        inRun = false;
                        continue;
                    }
                    failed++;
                }
            }
            prevTerminated = terminates(in);
            in = in.getNext();
        }

        if (dry || created == createdThisPass) break;   // fixpoint: nothing new claimed
        }

        if (out != null && !newEntries.isEmpty()) {
            try (FileWriter w = new FileWriter(out)) {
                w.write("# functions created over orphan (disassembled, function-less) code\n");
                for (String e : newEntries) w.write(e + "\n");
            }
        }
        println(String.format("ClaimOrphanCode [%08x,%08x): passes=%d orphan-runs=%d orphan-bytes=%d "
                + "functions-created=%d failed=%d claimed-bytes=%d%s",
                lo, hi, pass + 1, runs, orphanBytes, created, failed, claimedBytes,
                dry ? "  (DRY RUN)" : ""));
        if (pass >= MAX_PASSES - 1) println("  WARNING: hit the pass cap -- orphan code may remain");
    }
}
