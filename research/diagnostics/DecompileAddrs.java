// Ghidra headless postScript: decompile specific addresses (creating a function if
// none exists at the address) to <outDir>/<addr>.c. For CAN handler fn-pointers that
// auto-analysis never turned into functions.
//   analyzeHeadless <proj> <name> -process -postScript DecompileAddrs.java <outDir> <addr1> <addr2> ...
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.app.cmd.function.CreateFunctionCmd;
import java.io.File;
import java.io.FileWriter;

public class DecompileAddrs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args.length > 0 ? args[0] : "decompiles_extra";
        new File(outDir).mkdirs();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        for (int i = 1; i < args.length; i++) {
            String a = args[i];
            Address ep = currentProgram.getAddressFactory().getAddress(a);
            Function fn = getFunctionAt(ep);
            if (fn == null) {
                // disassemble + create a function at this address
                disassemble(ep);
                CreateFunctionCmd cmd = new CreateFunctionCmd(ep);
                cmd.applyTo(currentProgram, monitor);
                fn = getFunctionAt(ep);
            }
            if (fn == null) { println("FAIL create fn @ " + a); continue; }
            DecompileResults r = dec.decompileFunction(fn, 90, monitor);
            String addr = fn.getEntryPoint().toString();
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                try (FileWriter w = new FileWriter(new File(outDir, addr + ".c"))) {
                    w.write(r.getDecompiledFunction().getC());
                }
                println("OK " + addr);
            } else {
                println("FAIL decompile @ " + addr);
            }
        }
    }
}
