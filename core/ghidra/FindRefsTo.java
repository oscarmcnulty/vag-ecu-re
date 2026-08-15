// Ghidra headless postScript: list every reference to an address, with the referring function
// and whether it is a READ or a WRITE.
//
// WHY. Tracing a signal backwards repeatedly hits "who writes this RAM word?". Grepping the
// decompiles answers that only for direct `DAT_x = ...` stores; anything reached through a base
// pointer or a struct offset is invisible there but IS in Ghidra's reference model. This closes
// that gap without re-decompiling anything.
//
//   analyzeHeadless <proj> <name> -process -postScript FindRefsTo.java 0xd00084e2 [0xd00084e4 ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class FindRefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) { println("usage: FindRefsTo <addr> [addr...]"); return; }
        for (String a : args) {
            Address target = toAddr(Long.decode(a));
            println("=== refs to " + target + " ===");
            int n = 0;
            ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(target);
            while (it.hasNext()) {
                Reference r = it.next();
                Address from = r.getFromAddress();
                Function fn = getFunctionContaining(from);
                RefType rt = r.getReferenceType();
                String kind = rt.isWrite() ? "WRITE" : (rt.isRead() ? "read " : rt.toString());
                Instruction in = getInstructionAt(from);
                println(String.format("  %s  %-5s  fn=%-28s  %s", from, kind,
                        fn == null ? "(none)" : fn.getName() + "@" + fn.getEntryPoint(),
                        in == null ? "" : in.toString()));
                n++;
            }
            println("  total: " + n + (n == 0 ? "  (no disassembled code references this address)" : ""));
        }
    }
}
