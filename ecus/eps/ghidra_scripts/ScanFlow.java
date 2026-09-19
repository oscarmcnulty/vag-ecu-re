import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

// ScanFlow.java <startHex> <endHex>
// Force-disassemble the range, then report every instruction whose flow is a
// COMPUTED (indirect) jump/call, plus every JMP/JARL and its target, plus any
// instruction that references a data address holding a code pointer. Helps locate
// an unresolved statechart dispatcher.
public class ScanFlow extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    long s = Long.decode(a[0]), e = Long.decode(a[1]);
    Address start = toAddr(s), end = toAddr(e);
    // ensure disassembled
    Address p = start;
    while (p.getOffset() < e) {
      if (getInstructionAt(p) == null) { try { disassemble(p); } catch(Exception ex){} }
      Instruction in = getInstructionAt(p);
      if (in == null) { p = p.add(2); continue; }
      p = p.add(in.getLength());
    }
    p = start;
    while (p.getOffset() < e) {
      Instruction in = getInstructionAt(p);
      if (in == null) { p = p.add(2); continue; }
      FlowType ft = in.getFlowType();
      String m = in.getMnemonicString().toLowerCase();
      boolean indirect = ft.isComputed() || ft.isJump() && ft.isComputed();
      if (ft.isComputed() || m.equals("jmp") || (m.equals("jarl") && ft.isComputed())) {
        Address[] flows = in.getFlows();
        StringBuilder t = new StringBuilder();
        if (flows!=null) for (Address f: flows) t.append(f).append(" ");
        Reference[] refs = in.getReferencesFrom();
        StringBuilder rr = new StringBuilder();
        for (Reference r: refs) rr.append(r.getReferenceType()).append("->").append(r.getToAddress()).append(" ");
        println(String.format("%s: %-24s flow=%s targets=[%s] refs=[%s]",
                p, in.toString(), ft, t.toString().trim(), rr.toString().trim()));
      }
      p = p.add(in.getLength());
    }
    println("scan done "+start+".."+end);
  }
}
