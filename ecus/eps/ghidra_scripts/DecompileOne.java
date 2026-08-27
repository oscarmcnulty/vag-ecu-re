import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.Function;
import ghidra.program.model.address.Address;

public class DecompileOne extends GhidraScript {
  public void run() throws Exception {
    Address a=toAddr(Long.decode(getScriptArgs()[0]));
    Function f=getFunctionContaining(a);
    if(f==null){ disassemble(a); f=createFunction(a,null); }
    if(f==null){ println("no function at "+a); return; }
    DecompInterface d=new DecompInterface();
    d.openProgram(currentProgram);
    DecompileResults r=d.decompileFunction(f,60,monitor);
    println("=== "+f.getName()+" @"+f.getEntryPoint()+" ===");
    println(r.getDecompiledFunction()==null?"<fail>":r.getDecompiledFunction().getC());
  }
}
