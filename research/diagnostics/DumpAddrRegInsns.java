// Diagnostic: show how TriCore address-register loads appear in this Ghidra build.
// Prints distinct mnemonics that write an address register (a0..a15), with a few
// example instructions each, so we can fix base-register recovery.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.util.LinkedHashMap;
import java.util.Map;

public class DumpAddrRegInsns extends GhidraScript {
    @Override
    public void run() throws Exception {
        Map<String, Integer> mnem = new LinkedHashMap<>();
        Map<String, String> example = new LinkedHashMap<>();
        int a0a1a8 = 0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction ins = it.next();
            Register d = ins.getRegister(0);
            if (d == null || !d.getName().matches("a\\d+")) continue;
            String mn = ins.getMnemonicString();
            mnem.merge(mn, 1, Integer::sum);
            example.putIfAbsent(mn, ins.getAddress() + ": " + ins.toString());
            String dn = d.getName();
            if ((dn.equals("a0") || dn.equals("a1") || dn.equals("a8") || dn.equals("a9"))
                    && a0a1a8 < 25) {
                println("  [" + dn + "] " + ins.getAddress() + ": " + ins.toString()
                        + "   (ops=" + ins.getNumOperands() + ")");
                a0a1a8++;
            }
        }
        println("\n=== mnemonics that write an address register ===");
        mnem.entrySet().stream().sorted((a, b) -> b.getValue() - a.getValue())
            .forEach(e -> println(String.format("  %-12s %6d   e.g. %s",
                    e.getKey(), e.getValue(), example.get(e.getKey()))));
    }
}
