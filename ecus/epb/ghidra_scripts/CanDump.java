import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.mem.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class CanDump extends GhidraScript {
  public void run() throws Exception {
    Memory mem = currentProgram.getMemory();
    Listing lis = currentProgram.getListing();
    Address min = currentProgram.getMinAddress(), max = currentProgram.getMaxAddress();
    // Linear disassembly sweep: at each still-undefined address, try to disassemble.
    long start = min.getOffset(), end = max.getOffset();
    Address a = min;
    int placed=0;
    while (a.getOffset() < end) {
      if (getInstructionAt(a)==null && getDataAt(a)==null) {
        DisassembleCommand cmd = new DisassembleCommand(a, null, false);
        cmd.applyTo(currentProgram, monitor);
        placed++;
      }
      Instruction ins = getInstructionAt(a);
      if (ins!=null) a = a.add(ins.getLength());
      else a = a.add(1);
    }
    println("=== sweep placed ~"+placed+" starts");
    // Now scan for MSCAN reg refs and CAN-id immediates
    println("=== MSCAN reg (0x0140-0x017F) accesses ===");
    InstructionIterator ii = lis.getInstructions(true);
    while (ii.hasNext()) {
      Instruction ins = ii.next();
      for (int op=0; op<ins.getNumOperands(); op++)
        for (Object o : ins.getOpObjects(op))
          if (o instanceof Scalar) {
            long v=((Scalar)o).getUnsignedValue();
            if (v>=0x0140 && v<=0x017F)
              println(String.format("  REG 0x%03x @%06x : %s", v, ins.getAddress().getOffset(), ins.toString()));
          }
    }
    println("=== CAN-id immediates (0x0100-0x0200, 0x3C0, 0x50D) via CPD/LDD/CMP ===");
    long[] wanted={0x104,0x106,0x10d,0x109,0x10c,0x3c0,0x50d,0x100,0x101,0x102,0x103,0x105,0x10e,0x11e};
    Set<Long> ws=new HashSet<>(); for(long w:wanted) ws.add(w);
    ii = lis.getInstructions(true);
    while (ii.hasNext()) {
      Instruction ins = ii.next();
      for (int op=0; op<ins.getNumOperands(); op++)
        for (Object o : ins.getOpObjects(op))
          if (o instanceof Scalar) {
            long v=((Scalar)o).getUnsignedValue();
            if (ws.contains(v))
              println(String.format("  CANID 0x%03x @%06x : %s", v, ins.getAddress().getOffset(), ins.toString()));
          }
    }
  }
}
