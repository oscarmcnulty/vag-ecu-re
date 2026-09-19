import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
public class DisasmRange extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    Address start=toAddr(Long.decode(a[0]));
    Address end=toAddr(Long.decode(a[1]));
    Address cur=start;
    while(cur.compareTo(end)<0){
      Instruction in=getInstructionAt(cur);
      if(in==null){ println(cur+": <no instr>"); cur=cur.add(2); continue;}
      println(cur+": "+in);
      cur=cur.add(in.getLength());
    }
  }
}
