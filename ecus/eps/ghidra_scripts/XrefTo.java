import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
public class XrefTo extends GhidraScript {
  public void run() throws Exception {
    ReferenceManager rm = currentProgram.getReferenceManager();
    for(String s: getScriptArgs()){
      Address a=toAddr(Long.decode(s));
      println("=== xrefs TO "+s+" ===");
      ReferenceIterator it = rm.getReferencesTo(a);
      int n=0;
      while(it.hasNext()){
        Reference r=it.next();
        Address from=r.getFromAddress();
        Function f=getFunctionContaining(from);
        println("  from "+from+" type="+r.getReferenceType()+" in "+(f!=null?f.getName()+"@"+f.getEntryPoint():"<none>"));
        n++;
      }
      if(n==0) println("  (none)");
    }
  }
}
