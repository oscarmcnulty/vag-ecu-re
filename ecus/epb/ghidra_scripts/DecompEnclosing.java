import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.app.decompiler.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
public class DecompEnclosing extends GhidraScript {
  Address fnStart(Address a) throws Exception { // scan back to prev RTS(0x3D)/RTC(0x0A) boundary within 0x400 bytes
    long lim=a.getOffset()-0x600;
    Address p=a;
    while(p.getOffset()>lim){ int b=getByte(p.subtract(1))&0xff; if(b==0x3D||b==0x0A) return p; p=p.subtract(1); }
    return a.subtract(0x40);
  }
  public void run() throws Exception {
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    for(String s:getScriptArgs()){
      Address a=toAddr(Long.decode(s));
      Function f=getFunctionContaining(a);
      if(f==null){ Address st=fnStart(a); new DisassembleCommand(st,null,true).applyTo(currentProgram,monitor); f=getFunctionAt(st); if(f==null) f=createFunction(st,null); }
      if(f==null){ println("== no fn for "+s+" =="); continue; }
      DecompileResults r=di.decompileFunction(f,90,monitor);
      String c=(r!=null&&r.decompileCompleted())?r.getDecompiledFunction().getC():"<null>";
      println("//==== enclosing "+s+" -> "+f.getName()+" @"+f.getEntryPoint()+" ====");
      println(c);
    }
  }
}
