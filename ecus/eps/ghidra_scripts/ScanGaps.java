import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;

// ScanGaps.java <lo> <hi> <tlo> <thi>
// Force-disassemble [lo,hi); report every instruction (esp. jarl/jr/jmp/switch) whose
// flow target lands in [tlo,thi]. Finds an uncarved dispatcher that transfers into a
// known function cluster. Also flags reads/writes of hca_engage_fsm_state (-0x21a4[gp]).
public class ScanGaps extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    long lo = Long.decode(a[0]), hi = Long.decode(a[1]);
    long tlo = Long.decode(a[2]), thi = Long.decode(a[3]);
    Address cur = toAddr(lo), end = toAddr(hi);
    while (cur.getOffset() < hi) {
      Instruction in = getInstructionAt(cur);
      if (in == null) { try { disassemble(cur); } catch (Exception e) {} in = getInstructionAt(cur); }
      if (in == null) { cur = cur.add(2); continue; }
      Address[] flows = in.getFlows();
      boolean hit = false;
      if (flows != null) for (Address f : flows) {
        long t = f.getOffset();
        if (t >= tlo && t <= thi) hit = true;
      }
      String s = in.toString();
      boolean comp = in.getFlowType().isComputed() && !s.equals("jmp [lp]");
      if (hit || comp || s.startsWith("switch") || s.contains("-0x21a4[gp]")) {
        Function fn = getFunctionContaining(cur);
        StringBuilder t = new StringBuilder();
        if (flows != null) for (Address f : flows) t.append(f).append(" ");
        println(String.format("%08x: %-30s flow=[%s] fn=%s", cur.getOffset(), s, t.toString().trim(),
                fn != null ? fn.getName() + "@" + fn.getEntryPoint() : "<none>"));
      }
      cur = cur.add(in.getLength());
    }
    println("scan done " + Long.toHexString(lo) + ".." + Long.toHexString(hi));
  }
}
