// EPB (HCS12X) seed disassembly over the FLASH blocks only (0x780000-0x79c000, 0x7e0000-0x7f8000).
// No reset vector exists (S12X vector page 0xFF is the protected bootloader, absent), so auto-analysis
// has nothing to seed -- this linear-sweeps the flash placing instruction starts. Deliberately does NOT
// touch the IO/RAM/alias blocks (uninitialized) so no junk functions appear there.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.app.cmd.disassemble.DisassembleCommand;
public class SeedSweep extends GhidraScript {
  long[][] R = {{0x780000L,0x79c000L},{0x7e0000L,0x7f8000L}};
  public void run() throws Exception {
    int placed=0;
    for(long[] rg: R){ Address a=toAddr(rg[0]);
      while(a.getOffset()<rg[1]){
        if(getInstructionAt(a)==null && getDataAt(a)==null){
          new DisassembleCommand(a,null,false).applyTo(currentProgram,monitor);
          if(getInstructionAt(a)!=null) placed++;
        }
        Instruction ins=getInstructionAt(a);
        a = ins!=null ? a.add(ins.getLength()) : a.add(1);
      }
    }
    println("SeedSweep: placed "+placed+" instruction starts (flash only)");
  }
}
