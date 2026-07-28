// Ghidra headless postScript: export every function entry point (address only) to a
// version-controllable manifest. This is RE metadata (addresses), NOT decompiled code:
// it lets `CreateFunctions.java` recreate the exact function set so DecompileAll
// regenerates the analysis state without committing any derived source.
//   analyzeHeadless <proj> <name> -process -postScript ExportFunctions.java <outFile>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ExportFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args.length > 0 ? args[0] : "function_entries.txt";
        List<String> addrs = new ArrayList<>();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Function fn = it.next();
            if (fn.isExternal()) continue;
            addrs.add("0x" + fn.getEntryPoint().toString());
        }
        Collections.sort(addrs);
        try (FileWriter w = new FileWriter(out)) {
            w.write("# Function entry points (one hex vaddr per line). RE metadata only.\n");
            w.write("# Regenerate the labeled project: CreateFunctions.java reads this,\n");
            w.write("# then ApplySymbols.java applies names/comments from symbols_merged.csv.\n");
            for (String a : addrs) w.write(a + "\n");
        }
        println("ExportFunctions: wrote " + addrs.size() + " entries -> " + out);
    }
}
