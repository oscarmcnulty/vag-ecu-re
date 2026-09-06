// Export ESP8 function entries WITH per-function ARM/Thumb mode -> reproducible mixed-ISA manifest.
// Line format: 0xADDR,T  (Thumb)  or  0xADDR,A  (ARM). '#' comments ignored by the reader.
//   analyzeHeadless <proj> <name> -process -postScript EspExportFns.java <outFile>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.address.Address;
import java.io.FileWriter;
import java.util.*;

public class EspExportFns extends GhidraScript {
    public void run() throws Exception {
        String out = getScriptArgs().length>0 ? getScriptArgs()[0] : "function_entries.txt";
        Register tmode = currentProgram.getLanguage().getRegister("TMode");
        List<String> rows = new ArrayList<>();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        int thumb=0, arm=0;
        while (it.hasNext() && !monitor.isCancelled()) {
            Function fn = it.next();
            if (fn.isExternal()) continue;
            Address ep = fn.getEntryPoint();
            boolean isThumb=false;
            if (tmode!=null) {
                java.math.BigInteger v = currentProgram.getProgramContext().getValue(tmode, ep, false);
                isThumb = v!=null && v.intValue()==1;
            }
            if (isThumb) thumb++; else arm++;
            rows.add(String.format("0x%s,%s", ep.toString(), isThumb?"T":"A"));
        }
        Collections.sort(rows);
        try (FileWriter w = new FileWriter(out)) {
            w.write("# ESP8 function entries: 0xADDR,<T|A> (Thumb/ARM). Mixed-ISA RE metadata only.\n");
            w.write("# Recreated by EspCreateFns.java (sets TMode per Thumb entry) in reproduce.sh.\n");
            for (String r: rows) w.write(r+"\n");
        }
        println("EspExportFns: wrote "+rows.size()+" entries ("+arm+" ARM, "+thumb+" Thumb) -> "+out);
    }
}
