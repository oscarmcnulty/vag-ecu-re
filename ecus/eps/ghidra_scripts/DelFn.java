import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
public class DelFn extends GhidraScript {
  public void run() throws Exception {
    for(String s: getScriptArgs()){
      Address a=toAddr(Long.decode(s));
      Function f=getFunctionAt(a);
      if(f!=null){ Address end=f.getBody().getMaxAddress(); removeFunction(f);
        clearListing(a,end); println("deleted "+s+" (to "+end+")"); }
      else println("no function at "+s);
    }
  }
}
