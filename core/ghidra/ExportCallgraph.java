// Ghidra headless postScript: export a SHALLOW call graph + cal-region data reads
// so core/pipeline can build a bounded (few-hop) neighbor-context block per function
// for the LLM annotation pass. Kept intentionally shallow: we emit only the direct
// edges; the annotator walks at most a hop or two so it grounds names on real
// neighbors instead of hallucinating a domain from deep, weakly-related callers.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ExportCallgraph.java <outPrefix> [loHex] [hiHex]
//
// Outputs:
//   <outPrefix>_edges.csv      caller_addr,caller_name,callee_addr,callee_name
//   <outPrefix>_cal_reads.csv  func_addr,func_name,cal_addr,cal_symbol
// (callers are recovered in Python by inverting the edge list.)
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.Symbol;
import java.io.FileWriter;

public class ExportCallgraph extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String prefix = args.length > 0 ? args[0] : "callgraph";
        long lo = args.length > 1 ? Long.decode(args[1]) : 0x80040000L;
        long hi = args.length > 2 ? Long.decode(args[2]) : 0x80070000L;

        ReferenceManager rm = currentProgram.getReferenceManager();
        int edges = 0, reads = 0;

        try (FileWriter ew = new FileWriter(prefix + "_edges.csv");
             FileWriter cw = new FileWriter(prefix + "_cal_reads.csv")) {
            ew.write("caller_addr,caller_name,callee_addr,callee_name\n");
            cw.write("func_addr,func_name,cal_addr,cal_symbol\n");

            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext() && !monitor.isCancelled()) {
                Function fn = it.next();
                String fa = fn.getEntryPoint().toString();
                String fname = fn.getName();

                // direct call edges (unique callees; callers = inverted edge list)
                for (Function callee : fn.getCalledFunctions(monitor)) {
                    ew.write(String.format("%s,%s,%s,%s\n",
                        fa, fname, callee.getEntryPoint(), callee.getName()));
                    edges++;
                }

                // cal-region data reads inside this function's body -> naming evidence
                AddressSetView body = fn.getBody();
                var fromIt = rm.getReferenceSourceIterator(body, true);
                while (fromIt.hasNext() && !monitor.isCancelled()) {
                    Address from = fromIt.next();
                    for (Reference ref : rm.getReferencesFrom(from)) {
                        if (ref.getReferenceType().isCall()) continue; // edges handled above
                        Address to = ref.getToAddress();
                        if (to == null || !to.isMemoryAddress()) continue;
                        long off = to.getOffset();
                        if (off < lo || off >= hi) continue;
                        Symbol s = getSymbolAt(to);
                        String sym = s != null ? s.getName() : "";
                        cw.write(String.format("%s,%s,%s,%s\n", fa, fname, to, sym));
                        reads++;
                    }
                }
            }
        }
        println("ExportCallgraph: " + edges + " call edges, " + reads +
                " cal reads in [" + Long.toHexString(lo) + "," + Long.toHexString(hi) +
                ") -> " + prefix + "_{edges,cal_reads}.csv");
    }
}
