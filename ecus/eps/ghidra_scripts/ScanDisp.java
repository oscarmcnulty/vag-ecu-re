import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

// ScanDisp.java <tok> [tok...]
// Scan every defined instruction; print any whose toString contains a token (e.g. a gp disp),
// naming the containing function. Finds address-formation (movea gp) + gp stores that the ref
// DB may miss.
public class ScanDisp extends GhidraScript {
  public void run() throws Exception {
    String[] toks = getScriptArgs();
    Listing lst = currentProgram.getListing();
    InstructionIterator it = lst.getInstructions(true);
    int n=0;
    while (it.hasNext()) {
      Instruction in = it.next();
      String s = in.toString();
      for (String t : toks) {
        if (s.contains(t)) {
          Function f = getFunctionContaining(in.getAddress());
          String fn = f!=null ? (f.getName()+"@"+f.getEntryPoint()) : "<none>";
          println("  "+in.getAddress()+"  "+s+"   in "+fn);
          n++;
          break;
        }
      }
    }
    println("TOTAL matches: "+n);
  }
}
