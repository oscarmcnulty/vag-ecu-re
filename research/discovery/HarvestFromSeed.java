// Ghidra headless postScript: recover a cluster of indirectly-dispatched functions by
// seeding at known entry points and transitively following DIRECT CALL edges, creating a
// function at every call target. Recovers intra-cluster code that global call-harvest
// misses because the cluster's outermost entries are reached only via RAM-initialized
// fn-pointer arrays (no flash CALL/pointer), while the inner functions ARE directly called
// from their siblings once the outer entry is disassembled.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript HarvestFromSeed.java <entriesOut> <seed1> [seed2 ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.RefType;
import java.io.FileWriter;
import java.util.*;

public class HarvestFromSeed extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String entriesOut = args[0];
        ArrayDeque<Address> work = new ArrayDeque<>();
        Set<Long> seen = new HashSet<>();
        for (int i = 1; i < args.length; i++) {
            Address a = currentProgram.getAddressFactory().getAddress(args[i]);
            if (a != null) work.add(a);
        }
        List<Address> created = new ArrayList<>();
        int visited = 0;
        while (!work.isEmpty()) {
            if (monitor.isCancelled()) break;
            Address ep = work.poll();
            if (!seen.add(ep.getOffset())) continue;
            visited++;
            // ensure code + a function at this entry
            if (getInstructionAt(ep) == null) {
                try { disassemble(ep); } catch (Exception e) { continue; }
            }
            if (getInstructionAt(ep) == null) continue;
            Function f = getFunctionAt(ep);
            if (f == null) {
                try { new CreateFunctionCmd(ep).applyTo(currentProgram, monitor); } catch (Exception e) {}
                f = getFunctionAt(ep);
                if (f != null) created.add(ep);
            }
            if (f == null) continue;
            // Iterate the WHOLE function body via Ghidra's listing (Ghidra computed the body by
            // recursive descent, so this covers branch arms + code after rets, not just fallthrough),
            // collecting every direct CALL target. Those targets are clean function entries; recurse.
            java.util.Iterator<Instruction> it =
                    currentProgram.getListing().getInstructions(f.getBody(), true);
            while (it.hasNext()) {
                Instruction in = it.next();
                for (Reference r : in.getReferencesFrom()) {
                    if (r.getReferenceType().isCall()) {
                        Address t = r.getToAddress();
                        if (t != null && t.isMemoryAddress() && !seen.contains(t.getOffset())) work.add(t);
                    }
                }
            }
        }
        println("HarvestFromSeed: visited=" + visited + " newFunctions=" + created.size());
        Collections.sort(created, (x,y)->Long.compareUnsigned(x.getOffset(),y.getOffset()));
        try (FileWriter w = new FileWriter(entriesOut)) {
            for (Address a : created) w.write("0x" + a.toString() + "\n");
        }
        for (Address a : created) println("  new fn " + a);
    }
}
