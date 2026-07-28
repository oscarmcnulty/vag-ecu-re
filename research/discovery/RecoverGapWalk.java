// Ghidra headless postScript: recover functions in undefined-code ranges by walking addresses
// and letting Ghidra's OWN recursive-descent disassembly + function creation determine each
// function's extent (rather than a fragile hand-rolled linear sweep). At each still-undefined
// address: disassemble (recursive descent follows real control flow and stops at ret), create a
// function, then jump past the created body to the next undefined address. For RAM-fn-pointer-
// dispatched clusters that have NO direct CALL / flash pointer / resolvable table (so neither
// call-harvest nor address-sweep can seed them).
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript RecoverGapWalk.java <entriesOut> <lo1> <hi1> [<lo2> <hi2> ...]
// Run SetBaseRegs.java first (a0/a1/a8 seeded) so decompiles resolve cleanly.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import java.io.FileWriter;
import java.util.*;

public class RecoverGapWalk extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args[0];
        List<long[]> ranges = new ArrayList<>();
        for (int i = 1; i + 1 < args.length; i += 2)
            ranges.add(new long[]{ currentProgram.getAddressFactory().getAddress(args[i]).getOffset(),
                                   currentProgram.getAddressFactory().getAddress(args[i+1]).getOffset() });
        List<Address> created = new ArrayList<>();
        int disFail = 0;
        for (long[] r : ranges) {
            long a = r[0], hi = r[1];
            int guard = 0;
            while (a < hi && guard++ < 100000) {
                Address ad = toAddr(a);
                // already covered by a function? jump to end of that function.
                Function cont = getFunctionContaining(ad);
                if (cont != null) {
                    long end = cont.getBody().getMaxAddress().getOffset();
                    a = Math.max(end + 1, a + 2);
                    continue;
                }
                Instruction in = getInstructionAt(ad);
                if (in == null) {
                    try { disassemble(ad); } catch (Exception e) {}
                    in = getInstructionAt(ad);
                }
                if (in == null) { a += 2; disFail++; continue; }  // not a valid start; try next halfword
                // create a function here; Ghidra computes the body via recursive descent
                try { new CreateFunctionCmd(ad).applyTo(currentProgram, monitor); } catch (Exception e) {}
                Function f = getFunctionAt(ad);
                if (f != null) {
                    created.add(ad);
                    long end = f.getBody().getMaxAddress().getOffset();
                    a = Math.max(end + 1, a + 2);
                } else {
                    // couldn't functionize; skip past this single instruction
                    a += in.getLength();
                }
            }
        }
        // body-size histogram to judge boundary quality
        int small = 0, mid = 0, big = 0;
        for (Address e : created) {
            long n = getFunctionAt(e).getBody().getNumAddresses();
            if (n < 512) small++; else if (n < 4000) mid++; else big++;
        }
        println("RecoverGapWalk: created " + created.size() + " functions (disFail halfwords=" + disFail + ")");
        println("RecoverGapWalk: body sizes  <512B=" + small + "  512-4000B=" + mid + "  >4000B=" + big);
        Collections.sort(created, (x,y)->Long.compareUnsigned(x.getOffset(),y.getOffset()));
        try (FileWriter w = new FileWriter(out)) {
            for (Address e : created) w.write("0x" + e.toString() + "\n");
        }
    }
}
