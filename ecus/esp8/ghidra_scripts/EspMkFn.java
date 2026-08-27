import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspMkFn extends GhidraScript {
  public void run() throws Exception {
    for(String a:getScriptArgs()){
      Address ad=currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(Long.parseLong(a,16));
      boolean thumb=(ad.getOffset()&1)!=0; if(thumb) ad=ad.subtract(1);
      if(currentProgram.getListing().getInstructionAt(ad)==null){
        new ArmDisassembleCommand(ad,null,thumb).applyTo(currentProgram,monitor);
        if(currentProgram.getListing().getInstructionAt(ad)==null) new ArmDisassembleCommand(ad,null,!thumb).applyTo(currentProgram,monitor);
      }
      if(currentProgram.getListing().getFunctionAt(ad)==null) new CreateFunctionCmd(ad).applyTo(currentProgram,monitor);
      println("  "+a+" -> "+(currentProgram.getListing().getFunctionAt(ad)!=null?"function":"failed"));
    }
  }
}
