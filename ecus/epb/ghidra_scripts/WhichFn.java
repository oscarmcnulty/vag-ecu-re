import ghidra.app.script.GhidraScript; import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
public class WhichFn extends GhidraScript { public void run() throws Exception {
  FunctionManager fm=currentProgram.getFunctionManager();
  for(String s:getScriptArgs()){ Address a=toAddr(Long.decode(s));
    Function f=fm.getFunctionContaining(a); Function at=fm.getFunctionAt(a);
    println(String.format("%s : containing=%s  exactEntry=%s", s,
      f!=null?f.getName()+"@"+f.getEntryPoint():"NONE", at!=null?"yes":"no")); } }
}
