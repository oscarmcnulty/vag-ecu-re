import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

// FindIndJmp.java
// Scan every defined instruction in the program; report indirect jmp/jarl/callt-style
// computed transfers whose register operand is NOT lp (r31) -- i.e. real runtime dispatch
// sites (a statechart executor's `jmp [rN]`), not ordinary function returns (`jmp [lp]`).
// Names the containing function. Helps locate a runtime-built dispatch table.
public class FindIndJmp extends GhidraScript {
  public void run() throws Exception {
    Listing lst = currentProgram.getListing();
    InstructionIterator it = lst.getInstructions(true);
    int n=0;
    while (it.hasNext()) {
      Instruction in = it.next();
      FlowType ft = in.getFlowType();
      if (!ft.isComputed()) continue;
      String s = in.toString();
      // skip plain returns
      if (s.equals("jmp [lp]")) continue;
      Function f = getFunctionContaining(in.getAddress());
      String fn = f!=null ? (f.getName()+"@"+f.getEntryPoint()) : "<none>";
      Address[] flows = in.getFlows();
      StringBuilder t = new StringBuilder();
      if (flows!=null) for (Address a: flows) t.append(a).append(" ");
      println(String.format("%s: %-22s flow=%s targets=[%s] in %s",
              in.getAddress(), s, ft, t.toString().trim(), fn));
      n++;
    }
    println("TOTAL non-return computed transfers: "+n);
  }
}
