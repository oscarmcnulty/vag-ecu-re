import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
public class Disasm extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs(); long s=Long.parseLong(a[0],16), e=Long.parseLong(a[1],16);
    Address ad=currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(s);
    while(ad.getOffset()<e){
      Instruction in=getInstructionAt(ad);
      if(in==null){ ad=ad.add(2); continue; }
      println(String.format("%x: %s",ad.getOffset(),in.toString()));
      ad=ad.add(in.getLength());
    }
  }
}
