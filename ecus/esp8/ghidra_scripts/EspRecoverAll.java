// Maximize function coverage in the code region: iterate (a) create functions at BL/BLX
// call targets, (b) disassemble ARM STMFD / Thumb PUSH prologues in undefined space,
// until no new functions appear. Reproducible, image-agnostic within 0x0..CODE_HI.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspRecoverAll extends GhidraScript {
  long LO=0x0, HI=0xa2800;
  Memory mem; AddressSpace sp; Listing lst;
  boolean mk(Address ad, boolean thumb){
    if(lst.getInstructionAt(ad)==null){
      if(!new ArmDisassembleCommand(ad,null,thumb).applyTo(currentProgram,monitor)) return false;
    }
    if(lst.getInstructionAt(ad)==null) return false;
    if(lst.getFunctionAt(ad)==null) return new CreateFunctionCmd(ad).applyTo(currentProgram,monitor);
    return false;
  }
  public void run() throws Exception {
    mem=currentProgram.getMemory(); sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    lst=currentProgram.getListing();
    int round=0, made;
    do {
      made=0;
      // (a) create fns at call targets not yet functions
      InstructionIterator it=lst.getInstructions(true);
      java.util.List<Address> tgts=new java.util.ArrayList<>();
      while(it.hasNext()){ Instruction ins=it.next();
        if(ins.getAddress().getOffset()>=HI) break;
        String mn=ins.getMnemonicString().toLowerCase();
        if(mn.startsWith("bl")||mn.equals("blx")){
          Reference[] rs=ins.getReferencesFrom();
          for(Reference r:rs){ if(r.getReferenceType().isCall()){
            Address t=r.getToAddress();
            if(t.getOffset()<HI && lst.getFunctionAt(t)==null && lst.getInstructionAt(t)!=null) tgts.add(t);
          }}
        }
      }
      for(Address t:tgts){ if(lst.getFunctionAt(t)==null && new CreateFunctionCmd(t).applyTo(currentProgram,monitor)) made++; }
      // (b) prologue sweep in undefined space
      for(long a=LO;a<HI;a+=2){ Address ad=sp.getAddress(a);
        if(lst.getInstructionAt(ad)!=null||lst.getDefinedDataAt(ad)!=null) continue;
        int hw; try{hw=mem.getShort(ad)&0xFFFF;}catch(Exception e){continue;}
        if((hw&0xFF00)==0xB500){ if(mk(ad,true)) made++; continue; }
        if(a%4==0){ int w; try{w=mem.getInt(ad);}catch(Exception e){continue;}
          if((w&0xFFFF0000)==0xE92D0000&&(w&0x4000)!=0){ if(mk(ad,false)) made++; } }
      }
      round++; println("round "+round+": +"+made+" functions");
    } while(made>0 && round<8);
    int tot=0; FunctionIterator fi=currentProgram.getFunctionManager().getFunctions(true);
    while(fi.hasNext()){fi.next();tot++;}
    println("total functions: "+tot);
  }
}
