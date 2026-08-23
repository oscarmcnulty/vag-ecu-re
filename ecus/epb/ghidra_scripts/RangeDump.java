import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.app.cmd.disassemble.DisassembleCommand;

public class RangeDump extends GhidraScript {
  public void run() throws Exception {
    String[] args = getScriptArgs();
    long start = Long.decode(args[0]);
    int len = Integer.decode(args[1]);
    Address a = toAddr(start);
    Address endA = toAddr(start+len);
    // force clear + disassemble the range
    DisassembleCommand cmd = new DisassembleCommand(a, null, false);
    cmd.applyTo(currentProgram, monitor);
    while (a.getOffset() < start+len) {
      Instruction ins = getInstructionAt(a);
      if (ins==null) {
        DisassembleCommand c2 = new DisassembleCommand(a, null, false);
        c2.applyTo(currentProgram, monitor);
        ins = getInstructionAt(a);
      }
      if (ins==null) { println(String.format("%06x  .byte %02x", a.getOffset(), getByte(a)&0xff)); a=a.add(1); }
      else { println(String.format("%06x  %s", a.getOffset(), ins.toString())); a=a.add(ins.getLength()); }
    }
  }
}
