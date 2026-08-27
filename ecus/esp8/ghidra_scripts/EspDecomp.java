// Decompile addresses passed as args to stdout.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;

public class EspDecomp extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        AddressFactory af = currentProgram.getAddressFactory();
        for (String a : args) {
            Address ad = af.getDefaultAddressSpace().getAddress(Long.parseLong(a,16));
            Function f = getFunctionContaining(ad);
            if (f==null) { println("// no func at "+a); continue; }
            println("// ======== "+f.getName()+" @"+f.getEntryPoint()+" ========");
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            if (r!=null && r.decompileCompleted())
                println(r.getDecompiledFunction().getC());
            else println("// decompile failed: "+(r!=null?r.getErrorMessage():"null"));
        }
    }
}
