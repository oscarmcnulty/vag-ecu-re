import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;

// Force-disassemble and print instructions over regions passed as args:
//   -scriptPath ... -postScript DumpRegion.java 0x1a600 0x1ac00 0x259ca 0x25a80
public class DumpRegion extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    Listing lis = currentProgram.getListing();
    for (int i = 0; i + 1 < a.length; i += 2) {
      long lo = Long.decode(a[i]);
      long hi = Long.decode(a[i + 1]);
      println("==== region 0x" + Long.toHexString(lo) + " .. 0x" + Long.toHexString(hi) + " ====");
      // clear any data defs and force-disassemble
      Address alo = toAddr(lo), ahi = toAddr(hi);
      try { clearListing(alo, ahi); } catch (Exception e) { println("clear err "+e); }
      Address cur = alo;
      while (cur.getOffset() < hi) {
        try { disassemble(cur); } catch (Exception e) {}
        Instruction ins = getInstructionAt(cur);
        if (ins == null) { cur = cur.add(2); continue; }
        StringBuilder sb = new StringBuilder();
        sb.append(String.format("%08x: ", cur.getOffset()));
        sb.append(ins.toString());
        Address ft = ins.getFallThrough();
        Address[] flows = ins.getFlows();
        if (flows != null && flows.length > 0) {
          sb.append("   flow->");
          for (Address f : flows) sb.append(" " + f);
        }
        println(sb.toString());
        cur = cur.add(ins.getLength());
      }
    }
  }
}
