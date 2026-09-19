import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
public class EspMkFnAt extends GhidraScript {
  public void run() throws Exception {
    for (String s: getScriptArgs()) {
      boolean thumb=s.endsWith("t"); String hs=thumb?s.substring(0,s.length()-1):s;
      long a=Long.parseLong(hs,16);
      Address ad=currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a);
      new ArmDisassembleCommand(ad,null,thumb).applyTo(currentProgram,monitor);
      new CreateFunctionCmd(ad).applyTo(currentProgram,monitor);
      println("mk "+s+" -> fn@"+(getFunctionAt(ad)!=null?getFunctionAt(ad).getName():"none"));
    }
  }
}
