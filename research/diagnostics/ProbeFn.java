// Diagnostic: for each address arg, report instruction/function/containing state + call refs out.
//   analyzeHeadless <proj> <name> -process -postScript ProbeFn.java <addr1> [addr2 ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

public class ProbeFn extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String a : getScriptArgs()) {
            Address ad = currentProgram.getAddressFactory().getAddress(a);
            Instruction in = getInstructionAt(ad);
            Function at = getFunctionAt(ad);
            Function cont = getFunctionContaining(ad);
            println("== " + a + " ==");
            println("  instrAt=" + (in == null ? "null" : in.toString()));
            println("  funcAt=" + (at == null ? "null" : at.getName()));
            println("  containedIn=" + (cont == null ? "null"
                    : cont.getName() + " [" + cont.getEntryPoint() + ".." + cont.getBody().getMaxAddress()
                      + "] bytes=" + cont.getBody().getNumAddresses()));
            if (at != null) {
                int calls = 0;
                java.util.Iterator<Instruction> it =
                        currentProgram.getListing().getInstructions(at.getBody(), true);
                while (it.hasNext()) {
                    Instruction ins = it.next();
                    for (Reference r : ins.getReferencesFrom())
                        if (r.getReferenceType().isCall()) {
                            println("    CALL -> " + r.getToAddress());
                            calls++;
                        }
                }
                println("  totalCallRefs=" + calls);
            }
        }
    }
}
