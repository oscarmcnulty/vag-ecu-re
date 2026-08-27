// Survey the ESP8 program: memory blocks, function stats, code coverage.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;

public class EspSurvey extends GhidraScript {
    public void run() throws Exception {
        println("=== MEMORY BLOCKS ===");
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            println(String.format("  %-12s %s - %s  %6dKB  %s%s%s init=%b",
                b.getName(), b.getStart(), b.getEnd(), b.getSize()/1024,
                b.isRead()?"r":"-", b.isWrite()?"w":"-", b.isExecute()?"x":"-",
                b.isInitialized()));
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        int total=0, named=0, thunk=0;
        long codeBytes=0;
        for (Function f : fm.getFunctions(true)) {
            total++;
            if (f.isThunk()) thunk++;
            if (!f.getName().startsWith("FUN_") && !f.getName().startsWith("thunk_")) named++;
            codeBytes += f.getBody().getNumAddresses();
        }
        println("\n=== FUNCTIONS ===");
        println("  total="+total+"  named(non-FUN_)="+named+"  thunks="+thunk);
        println("  bytes in functions: "+codeBytes+" (0x"+Long.toHexString(codeBytes)+")");

        // instruction coverage
        long insns=0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) { it.next(); insns++; }
        println("  defined instructions: "+insns);

        // count ARM vs THUMB by register context would be complex; just report defined data
        long dataItems=0;
        DataIterator di = currentProgram.getListing().getDefinedData(true);
        while (di.hasNext()) { di.next(); dataItems++; }
        println("  defined data items: "+dataItems);
    }
}
