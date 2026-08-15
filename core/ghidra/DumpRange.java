// Dump TriCore disassembly for one or more address ranges, with raw bytes.
//   analyzeHeadless <proj> <name> -process -noanalysis -postScript DumpRange.java lo:hi [lo:hi ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

public class DumpRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String a : getScriptArgs()) {
            String[] p = a.split(":");
            long lo = Long.decode(p[0]), hi = Long.decode(p[1]);
            Address cur = toAddr(lo);
            println("=== " + p[0] + " .. " + p[1] + " ===");
            while (cur.getOffset() < hi) {
                Instruction in = getInstructionAt(cur);
                if (in == null) {
                    println(String.format("  %s  (no instruction)", cur));
                    cur = cur.add(2);
                    continue;
                }
                Function fn = getFunctionContaining(cur);
                StringBuilder bs = new StringBuilder();
                for (byte b : in.getBytes()) bs.append(String.format("%02x ", b));
                println(String.format("  %s  %-24s %-40s %s", cur, bs.toString(), in.toString(),
                        fn == null ? "" : fn.getName()));
                cur = cur.add(in.getLength());
            }
        }
    }
}
