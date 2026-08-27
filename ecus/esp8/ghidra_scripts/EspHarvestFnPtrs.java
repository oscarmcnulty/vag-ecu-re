// Recover indirect-call targets: scan the whole image for words that are valid code
// addresses (4-aligned=ARM, odd=Thumb) pointing into undefined code-like bytes; disasm+create fn.
// Also directly disassemble code-like undefined ranges. Iterate to convergence.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspHarvestFnPtrs extends GhidraScript {
  long CODE_HI=0xa2800, IMG_HI=0x134011;
  Memory mem; AddressSpace sp; Listing lst;
  boolean isUndefCode(long t){
    if(t<0||t>=CODE_HI) return false;
    Address ad=sp.getAddress(t&~1L);
    if(lst.getInstructionAt(ad)!=null) return false;
    if(lst.getDefinedDataAt(ad)!=null) return false;
    try{ int w=mem.getInt(sp.getAddress(t&~3L)); return true; }catch(Exception e){ return false; }
  }
  boolean make(long t){
    boolean thumb=(t&1)!=0; Address ad=sp.getAddress(t&~1L);
    if(lst.getInstructionAt(ad)==null){
      if(!new ArmDisassembleCommand(ad,null,thumb).applyTo(currentProgram,monitor)) return false;
      if(lst.getInstructionAt(ad)==null) return false;
    }
    if(lst.getFunctionAt(ad)==null) return new CreateFunctionCmd(ad).applyTo(currentProgram,monitor);
    return false;
  }
  public void run() throws Exception {
    mem=currentProgram.getMemory(); sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    lst=currentProgram.getListing();
    int round=0, made;
    do { made=0;
      // harvest fn-pointer-like words across the whole image
      for(long o=0;o+4<=IMG_HI;o+=4){
        int w; try{w=mem.getInt(sp.getAddress(o));}catch(Exception e){continue;}
        long t=w & 0xFFFFFFFFL;
        // ARM target (4-aligned, even) or Thumb target (odd)
        boolean armT=(t&3)==0, thumbT=(t&1)==1;
        if((armT||thumbT) && isUndefCode(t)){ if(make(t)) made++; }
      }
      round++; println("harvest round "+round+": +"+made);
    } while(made>0 && round<6);
    // count
    int tot=0; FunctionIterator fi=currentProgram.getFunctionManager().getFunctions(true);
    while(fi.hasNext()){fi.next();tot++;}
    println("total functions: "+tot);
  }
}
