import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspDisasmUndef extends GhidraScript {
  public void run() throws Exception {
    long LO=0x0, HI=0xa2800; int made=0, disasm=0;
    Listing lst=currentProgram.getListing(); Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    long a=LO;
    while(a<HI){
      Address ad=sp.getAddress(a); CodeUnit cu=lst.getCodeUnitAt(ad);
      if(cu instanceof Data && !((Data)cu).isDefined()){
        long start=a;
        while(a<HI){ CodeUnit c2=lst.getCodeUnitAt(sp.getAddress(a)); if(c2 instanceof Data && !((Data)c2).isDefined()) a++; else break; }
        long len=a-start;
        if(len>=16){
          // ARM% test
          int arm=0,n=0; for(long o=start;o+4<=start+len;o+=4){ int w; try{w=mem.getInt(sp.getAddress(o));}catch(Exception e){break;} n++; if((w>>>28)==0xE) arm++; }
          if(n>0 && arm*100/n>=50){
            long s4=(start+3)&~3L; Address sa=sp.getAddress(s4);
            if(new ArmDisassembleCommand(sa,null,false).applyTo(currentProgram,monitor)){ disasm++;
              if(lst.getFunctionAt(sa)==null && new CreateFunctionCmd(sa).applyTo(currentProgram,monitor)) made++; }
          }
        }
      } else a+=Math.max(1,cu!=null?cu.getLength():1);
    }
    println("direct-disasm undef code ranges: disasm="+disasm+" fns="+made);
  }
}
