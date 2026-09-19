import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.lang.Register;
public class FindGpRef extends GhidraScript {
  public void run() throws Exception {
    // args: list of gp-offsets (signed decimal or hex) to hunt for
    long[] offs = new long[getScriptArgs().length];
    for(int i=0;i<offs.length;i++) offs[i]=Long.decode(getScriptArgs()[i]);
    Listing lis=currentProgram.getListing();
    InstructionIterator it=lis.getInstructions(true);
    while(it.hasNext()){
      Instruction in=it.next();
      String s=in.toString();
      for(long o: offs){
        String hx = (o<0?"-0x"+Long.toHexString(-o):"0x"+Long.toHexString(o))+"[gp]";
        if(s.contains(hx)){
          Function fn=getFunctionContaining(in.getAddress());
          println(String.format("%08x: %-32s in %s", in.getAddress().getOffset(), s, fn!=null?fn.getName()+"@"+fn.getEntryPoint():"<none>"));
        }
      }
    }
    println("done");
  }
}
