import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.util.*;
public class FindCallers extends GhidraScript {
  public void run() throws Exception {
    Set<Long> targets = new HashSet<>();
    for(String s: getScriptArgs()) targets.add(Long.decode(s));
    Listing lis = currentProgram.getListing();
    InstructionIterator it = lis.getInstructions(true);
    while(it.hasNext()){
      Instruction in = it.next();
      Address[] flows = in.getFlows();
      if(flows==null) continue;
      for(Address f: flows){
        if(targets.contains(f.getOffset())){
          Function fn=getFunctionContaining(in.getAddress());
          println(String.format("%08x -> %08x  (%s)  in %s", in.getAddress().getOffset(), f.getOffset(), in.toString(), fn!=null?fn.getName()+"@"+fn.getEntryPoint():"<none>"));
        }
      }
    }
    println("done");
  }
}
