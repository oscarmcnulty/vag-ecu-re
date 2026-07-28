// Ghidra headless postScript: structurally recover functions in a range of UNDEFINED code
// that is dispatched only via RAM fn-pointer arrays (no direct CALL, no flash pointer, so
// call-graph harvest can't reach it). Linear-disassembles the range, then declares a new
// function entry at: the range start, any branch/call target inside the range, and every
// instruction that immediately follows a flow terminator (ret/rfe/uncond j with no
// fallthrough). Creates functions at those entries.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript RecoverGapStructural.java <entriesOut> <lo1> <hi1> [<lo2> <hi2> ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;
import java.io.FileWriter;
import java.util.*;

public class RecoverGapStructural extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String entriesOut = args[0];
        List<long[]> ranges = new ArrayList<>();
        for (int i = 1; i + 1 < args.length; i += 2) {
            long lo = currentProgram.getAddressFactory().getAddress(args[i]).getOffset();
            long hi = currentProgram.getAddressFactory().getAddress(args[i+1]).getOffset();
            ranges.add(new long[]{lo, hi});
        }
        TreeSet<Long> callTargets = new TreeSet<>();   // intra-range direct CALL targets (clean entries)
        TreeSet<Long> afterRet = new TreeSet<>();       // first instr after a real return (RAM-dispatched heads)
        for (long[] r : ranges) {
            long lo = r[0], hi = r[1];
            Address alo = toAddr(lo), ahi = toAddr(hi);
            // remove any pre-existing (e.g. prior-run) functions in the range so bodies recompute clean
            List<Function> old = new ArrayList<>();
            FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(alo, true);
            while (fit.hasNext()) { Function f = fit.next(); if (f.getEntryPoint().getOffset() >= hi) break; old.add(f); }
            for (Function f : old) try { removeFunction(f); } catch (Exception e) {}
            try { clearListing(alo, ahi.subtract(1)); } catch (Exception e) {}
            // PHASE A: force-disassemble every undefined 2-byte offset in the range (recursive descent
            // fills contiguous runs; the 2-byte step re-seeds across ret-gaps that no flow reaches).
            for (long a = lo; a < hi; a += 2) {
                Address ad = toAddr(a);
                if (getInstructionAt(ad) != null) continue;
                try { disassemble(ad); } catch (Exception e) {}
            }
            afterRet.add(lo);  // range start is an entry
        }
        // PHASE B: iterate ALL disassembled instructions in the ranges via the listing; the instruction
        // AFTER every ret/rfe/ji is a function entry, and every intra-range CALL target is an entry.
        for (long[] r : ranges) {
            Address alo = toAddr(r[0]), ahi = toAddr(r[1]);
            ghidra.program.model.address.AddressSet set =
                    new ghidra.program.model.address.AddressSet(alo, ahi.subtract(1));
            java.util.Iterator<Instruction> it = currentProgram.getListing().getInstructions(set, true);
            boolean prevRet = false;
            while (it.hasNext()) {
                Instruction ins = it.next();
                long addr = ins.getAddress().getOffset();
                if (prevRet) afterRet.add(addr);
                for (Reference rf : ins.getReferencesFrom()) {
                    if (rf.getReferenceType().isCall()) {
                        long t = rf.getToAddress().getOffset();
                        for (long[] rr : ranges) if (t >= rr[0] && t < rr[1]) callTargets.add(t);
                    }
                }
                String mn = ins.getMnemonicString().toLowerCase();
                prevRet = mn.equals("ret") || mn.equals("ret16") || mn.equals("rfe")
                        || mn.equals("rfm") || mn.startsWith("ji");
            }
        }
        // Entry priority: CALL targets (Ghidra computes clean bodies) first, then after-ret heads for
        // code no CALL reaches. Skip any candidate that already fell inside a created function's body.
        TreeSet<Long> entries = new TreeSet<>();
        entries.addAll(callTargets);
        entries.addAll(afterRet);
        List<Address> created = new ArrayList<>();
        for (long e : entries) {
            Address ep = toAddr(e);
            if (getFunctionContaining(ep) != null) continue;   // covered by an already-created body
            if (getInstructionAt(ep) == null) continue;
            try { new CreateFunctionCmd(ep).applyTo(currentProgram, monitor); } catch (Exception ex) {}
            if (getFunctionAt(ep) != null) created.add(ep);
        }
        println("RecoverGapStructural: callTargets=" + callTargets.size() + " afterRet=" + afterRet.size()
                + " created=" + created.size());
        // report body sizes (instruction count) to gauge boundary quality
        int big = 0;
        for (Address a : created) {
            Function f = getFunctionAt(a);
            long n = f == null ? 0 : f.getBody().getNumAddresses();
            if (n > 4000) big++;
        }
        println("RecoverGapStructural: functions with >4000 body bytes (possible over-merge): " + big);
        try (FileWriter w = new FileWriter(entriesOut)) {
            for (Address a : created) w.write("0x" + a.toString() + "\n");
        }
    }
}
