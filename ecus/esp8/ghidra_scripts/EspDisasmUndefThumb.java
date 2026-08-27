import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspDisasmUndefThumb extends GhidraScript {
  public void run() throws Exception {
    long LO=0x0, HI=0xa2800; int made=0;
    Listing lst=currentProgram.getListing(); Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    long a=LO;
    while(a<HI){ Address ad=sp.getAddress(a); CodeUnit cu=lst.getCodeUnitAt(ad);
      if(cu instanceof Data && !((Data)cu).isDefined()){
        long start=a; while(a<HI){ CodeUnit c2=lst.getCodeUnitAt(sp.getAddress(a)); if(c2 instanceof Data && !((Data)c2).isDefined()) a++; else break; }
        long len=a-start;
        if(len>=12){
          // Thumb prologue B5xx at even offsets
          for(long o=start;o+2<=start+len;o+=2){ int hw; try{hw=mem.getShort(sp.getAddress(o))&0xFFFF;}catch(Exception e){break;}
            if((hw&0xFF00)==0xB500){ Address ta=sp.getAddress(o);
              if(new ArmDisassembleCommand(ta,null,true).applyTo(currentProgram,monitor) && lst.getInstructionAt(ta)!=null){
                if(lst.getFunctionAt(ta)==null && new CreateFunctionCmd(ta).applyTo(currentProgram,monitor)) made++; } break; } }
        }
      } else a+=Math.max(1,cu!=null?cu.getLength():1);
    }
    println("thumb residual: fns="+made);
  }
}
