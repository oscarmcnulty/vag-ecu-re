import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class FindCallers extends GhidraScript { public void run() throws Exception {
  FunctionManager fm=currentProgram.getFunctionManager();
  ReferenceManager rm=currentProgram.getReferenceManager();
  for(String s:getScriptArgs()){
    Address t=toAddr(Long.decode(s));
    println("== callers of "+s+" ==");
    for(Reference r:rm.getReferencesTo(t)){
      if(!r.getReferenceType().isCall() && !r.getReferenceType().isJump() && !r.getReferenceType().isData()) continue;
      Function f=fm.getFunctionContaining(r.getFromAddress());
      println(String.format("   %-5s from %s  in fn %s", r.getReferenceType(), r.getFromAddress(),
        f!=null?(f.getName()+"@"+f.getEntryPoint()):"?"));
    }
  }
}}
