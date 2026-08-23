import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.AddressSet;

public class ArchProbe extends GhidraScript {
  public void run() throws Exception {
    // probe entry points (base=0, addr==file offset)
    long[] pts = {0xcec9L,0xc662L,0xc7a6L,0xcba1L,0xc9faL,0x1000L,0x4000L,0x8000L};
    for (long p : pts) {
      Address a = toAddr(p);
      DisassembleCommand cmd = new DisassembleCommand(a, null, true);
      cmd.applyTo(currentProgram, monitor);
      int good=0, len=0; StringBuilder sb=new StringBuilder();
      Address cur=a;
      for (int i=0;i<12;i++){
        Instruction ins=getInstructionAt(cur);
        if (ins==null){ sb.append(String.format(" [bad@%x]",cur.getOffset())); break; }
        good++; len+=ins.getLength();
        if(i<6) sb.append(" | ").append(ins.toString());
        cur=cur.add(ins.getLength());
      }
      println(String.format("@%06x good=%2d bytes=%3d%s",p,good,len,sb.toString()));
    }
  }
}
