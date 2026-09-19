// Find the UDS SID dispatcher: a function whose decompiled C compares a value against several
// UDS service IDs including 0x22 (proven supported via the DID table). Report the SID set seen.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.util.*;
public class EspFindDispatch extends GhidraScript {
  static int[] SIDS={0x10,0x11,0x14,0x19,0x22,0x23,0x27,0x28,0x2e,0x2f,0x31,0x34,0x35,0x36,0x37,0x3d,0x3e,0x85,0x86,0x87,0x3b,0x83,0x84};
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long lo=Long.parseLong(a[0],16), hi=Long.parseLong(a[1],16);
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    FunctionIterator fi=currentProgram.getFunctionManager().getFunctions(true);
    while(fi.hasNext()){
      Function f=fi.next(); long e=f.getEntryPoint().getOffset();
      if(e<lo||e>=hi) continue;
      DecompileResults r=di.decompileFunction(f,45,monitor);
      if(r==null||!r.decompileCompleted()) continue;
      String c=r.getDecompiledFunction().getC();
      // must reference 0x22 (proven) as a comparison-ish token
      if(!(c.contains("0x22")||c.contains("== 0x22"))) continue;
      TreeSet<Integer> seen=new TreeSet<>();
      for(int s:SIDS){ if(c.contains(String.format("0x%x",s))) seen.add(s); }
      if(seen.size()>=6){
        StringBuilder sb=new StringBuilder();
        for(int s:seen) sb.append(String.format("0x%x ",s));
        println("DISP? @"+f.getEntryPoint()+" "+f.getName()+" sids{ "+sb+"} len="+c.length());
      }
    }
    println("done");
  }
}
