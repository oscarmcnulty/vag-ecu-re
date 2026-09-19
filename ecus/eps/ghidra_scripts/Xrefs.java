import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

// Xrefs.java <addr> [addr...]
// Print every reference TO each address (Ghidra's full ref DB, incl. computed jumps/data),
// naming the containing function of each source.
public class Xrefs extends GhidraScript {
  public void run() throws Exception {
    ReferenceManager rm = currentProgram.getReferenceManager();
    for (String s : getScriptArgs()) {
      Address a = toAddr(Long.decode(s));
      println("==== refs TO " + s + " (" + a + ") ====");
      ReferenceIterator it = rm.getReferencesTo(a);
      int n=0;
      while (it.hasNext()) {
        Reference r = it.next();
        Address from = r.getFromAddress();
        Function f = getFunctionContaining(from);
        String fn = f!=null ? (f.getName()+"@"+f.getEntryPoint()) : "<none>";
        println("  from " + from + "  type=" + r.getReferenceType() + "  in " + fn);
        n++;
      }
      if (n==0) println("  (no references found in DB)");
    }
  }
}
