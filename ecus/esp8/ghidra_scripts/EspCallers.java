import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class EspCallers extends GhidraScript {
  public void run() throws Exception {
    long t=Long.parseLong(getScriptArgs()[0],16);
    Address ad=currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(t);
    ReferenceIterator ri=currentProgram.getReferenceManager().getReferencesTo(ad);
    while(ri.hasNext()){ Reference r=ri.next();
      if(!r.getReferenceType().isCall()) continue;
      Function f=getFunctionContaining(r.getFromAddress());
      println("  call from "+r.getFromAddress()+"  "+(f!=null?f.getName()+"@"+f.getEntryPoint():"(no fn)")); }
  }
}
