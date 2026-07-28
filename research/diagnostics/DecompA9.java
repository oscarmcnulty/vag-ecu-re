// Set the a9 base-register context (+ existing a0/a1/a8) and decompile one function, to confirm that
// a9 = cal-object-table folds the ACC *(a9+off) accesses to concrete cal-object addresses.
// Args: <funcAddrHex> [a9Hex=80103464]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.lang.RegisterValue;
import java.math.BigInteger;

public class DecompA9 extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long fa=Long.parseLong(a[0],16);
    long a9=a.length>1?Long.parseLong(a[1],16):0x80103464L;
    ProgramContext ctx=currentProgram.getProgramContext();
    Address s=currentProgram.getMinAddress(), e=currentProgram.getMaxAddress();
    long[][] regs={{0,0xd000c420L},{1,0x8002f298L},{8,0xd000c420L},{9,a9}};
    for(long[] rv:regs){ Register r=ctx.getRegister("a"+rv[0]); if(r!=null) ctx.setRegisterValue(s,e,new RegisterValue(r,BigInteger.valueOf(rv[1]))); }
    println("set a9=0x"+Long.toHexString(a9)+"; decompiling 0x"+Long.toHexString(fa));
    Function f=getFunctionContaining(toAddr(fa));
    if(f==null){ println("no function at "+Long.toHexString(fa)); return; }
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    DecompileResults res=di.decompileFunction(f,60,monitor);
    String c=res.getDecompiledFunction()!=null?res.getDecompiledFunction().getC():"(null)";
    String[] lines=c.split("\n");
    println("  (decompile has "+lines.length+" lines; showing all)");
    for(int i=0;i<lines.length;i++) println("  "+lines[i]);
    di.dispose();
  }
}
