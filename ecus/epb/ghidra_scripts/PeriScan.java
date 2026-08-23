import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.scalar.Scalar;

public class PeriScan extends GhidraScript {
  // labeled S12X peripheral ranges + signal struct
  long[][] R = {
    {0x0300,0x0327}, // PWM (PWME/PER/DTY)
    {0x0080,0x00AF}, // ATD0 ctrl+results (motor current / force sense)
    {0x02C0,0x02EF}, // ATD1 (some S12XE)
    {0x0000,0x003F}, // PORT A..K registers (H-bridge GPIO / enable)
    {0x2780,0x2870}, // decoded CAN signal image struct
  };
  String[] N={"PWM","ATD0","ATD1","PORT","SIGSTRUCT"};
  public void run() throws Exception {
    Listing lis=currentProgram.getListing();
    Address min=currentProgram.getMinAddress(), max=currentProgram.getMaxAddress();
    long end=max.getOffset(); Address a=min;
    while(a.getOffset()<end){
      if(getInstructionAt(a)==null && getDataAt(a)==null) new DisassembleCommand(a,null,false).applyTo(currentProgram,monitor);
      Instruction ins=getInstructionAt(a);
      if(ins!=null) a=a.add(ins.getLength()); else a=a.add(1);
    }
    InstructionIterator ii=lis.getInstructions(true);
    while(ii.hasNext()){
      Instruction ins=ii.next();
      for(int op=0;op<ins.getNumOperands();op++)
        for(Object o:ins.getOpObjects(op))
          if(o instanceof Scalar){
            long v=((Scalar)o).getUnsignedValue();
            for(int r=0;r<R.length;r++) if(v>=R[r][0]&&v<=R[r][1])
              println(String.format("%-9s 0x%04x @%06x : %s", N[r], v, ins.getAddress().getOffset(), ins.toString()));
          }
    }
  }
}
