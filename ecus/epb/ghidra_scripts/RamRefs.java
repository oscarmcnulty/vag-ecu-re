import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.scalar.Scalar;

public class RamRefs extends GhidraScript {
  public void run() throws Exception {
    Listing lis=currentProgram.getListing();
    Address min=currentProgram.getMinAddress(), max=currentProgram.getMaxAddress();
    long end=max.getOffset();
    Address a=min;
    while(a.getOffset()<end){
      if(getInstructionAt(a)==null && getDataAt(a)==null){
        new DisassembleCommand(a,null,false).applyTo(currentProgram,monitor);
      }
      Instruction ins=getInstructionAt(a);
      if(ins!=null) a=a.add(ins.getLength()); else a=a.add(1);
    }
    // scan for operand scalars in RX-buffer + actuator RAM ranges of interest
    String[] argv=getScriptArgs();
    long lo=Long.decode(argv[0]), hi=Long.decode(argv[1]);
    InstructionIterator ii=lis.getInstructions(true);
    while(ii.hasNext()){
      Instruction ins=ii.next();
      for(int op=0;op<ins.getNumOperands();op++)
        for(Object o:ins.getOpObjects(op))
          if(o instanceof Scalar){
            long v=((Scalar)o).getUnsignedValue();
            if(v>=lo && v<=hi)
              println(String.format("REF 0x%04x @%06x : %s", v, ins.getAddress().getOffset(), ins.toString()));
          }
    }
  }
}
