// Ghidra headless postScript: print disassembly for an address range (disassembling if needed).
//   analyzeHeadless <proj> <name> -process -postScript DumpDisasm.java <startAddr> <endAddr>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class DumpDisasm extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Address a = currentProgram.getAddressFactory().getAddress(args[0]);
        Address end = currentProgram.getAddressFactory().getAddress(args[1]);
        disassemble(a);
        while (a != null && a.compareTo(end) < 0) {
            Instruction ins = getInstructionAt(a);
            if (ins == null) {
                disassemble(a);
                ins = getInstructionAt(a);
            }
            if (ins == null) { println(a + ": <no insn>"); a = a.add(2); continue; }
            StringBuilder refs = new StringBuilder();
            for (Address r : ins.getReferencesFrom().length > 0 ? new Address[]{ins.getReferencesFrom()[0].getToAddress()} : new Address[0]) {
                refs.append(" -> ").append(r);
            }
            println(a + ":  " + ins + refs);
            a = ins.getMaxAddress().add(1);
        }
    }
}
