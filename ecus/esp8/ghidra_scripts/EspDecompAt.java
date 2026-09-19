// For each addr arg, find the enclosing function by scanning back for an ARM/Thumb prologue,
// create it if needed, and decompile. Handles seg2 (VMA=file+3) code.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
public class EspDecompAt extends GhidraScript {
  public void run() throws Exception {
    Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    for(String s:getScriptArgs()){
      long site=Long.parseLong(s,16);
      Function f=getFunctionContaining(sp.getAddress(site));
      if(f==null){
        // scan back up to 0x600 bytes for ARM prologue e92d.... (4-aligned) or Thumb push b5xx (2-aligned)
        long found=0; boolean thumb=false;
        for(long a=site & ~1; a>site-0x600; a-=2){
          try{
            int hw=mem.getShort(sp.getAddress(a))&0xffff;
            if((a%4)==0){ int w=mem.getInt(sp.getAddress(a)); if((w>>>16)==0xe92d && (w&0x4000)!=0){found=a;thumb=false;break;} }
            if((hw&0xff00)==0xb500){found=a;thumb=true;break;}
          }catch(Exception e){}
        }
        if(found!=0){
          new ArmDisassembleCommand(sp.getAddress(found),null,thumb).applyTo(currentProgram,monitor);
          new CreateFunctionCmd(sp.getAddress(found)).applyTo(currentProgram,monitor);
          f=getFunctionContaining(sp.getAddress(site));
        }
      }
      if(f==null){ println("// site "+s+": no function found"); continue; }
      println("// ==== site "+s+" -> "+f.getName()+" @"+f.getEntryPoint()+" ====");
      DecompileResults r=di.decompileFunction(f,60,monitor);
      if(r!=null&&r.decompileCompleted()) println(r.getDecompiledFunction().getC());
      else println("// decompile failed");
    }
  }
}
