import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.data.*;
import java.util.*;

public class Orient extends GhidraScript {
  public void run() throws Exception {
    Listing lst=currentProgram.getListing();
    FunctionManager fm=currentProgram.getFunctionManager();
    ReferenceManager rm=currentProgram.getReferenceManager();
    // 1) function table: entry, size, #callers
    StringBuilder fns=new StringBuilder("=== FUNCTIONS (entry,bytes,callers) ===\n");
    int n=0;
    List<Function> all=new ArrayList<>();
    for(Function f: fm.getFunctions(true)) all.add(f);
    all.sort((a,b)-> Long.compare(getRefs(rm,b.getEntryPoint()), getRefs(rm,a.getEntryPoint())));
    for(Function f: all){
      long sz=f.getBody().getNumAddresses();
      long callers=getRefs(rm,f.getEntryPoint());
      fns.append(String.format("%08x %5d %3d %s\n", f.getEntryPoint().getOffset(), sz, callers, f.getName()));
      if(++n>=60) break;
    }
    println(fns.toString());
    // 2) references INTO the cal/string region [0x50000,0x75000): which code refs strings/data there
    println("=== code refs into cal region 0x50000..0x75000 (top referenced targets) ===");
    HashMap<Long,Integer> hits=new HashMap<>();
    AddressIterator it=rm.getReferenceSourceIterator(toAddr(0x0), true);
    for(Address src: iterable(it)){
      for(Reference r: rm.getReferencesFrom(src)){
        long t=r.getToAddress().getOffset();
        if(t>=0x50000 && t<0x75000) hits.merge(t,1,Integer::sum);
      }
    }
    // print any that point at/near a defined string
    List<Map.Entry<Long,Integer>> es=new ArrayList<>(hits.entrySet());
    es.sort((a,b)->b.getValue()-a.getValue());
    int m=0;
    for(Map.Entry<Long,Integer> e: es){
      Data d=lst.getDataAt(toAddr(e.getKey()));
      String s = (d!=null && d.hasStringValue())? d.getDefaultValueRepresentation() : "";
      println(String.format("  %08x x%d %s", e.getKey(), e.getValue(), s));
      if(++m>=40) break;
    }
  }
  long getRefs(ReferenceManager rm, Address a){
    int c=0; for(Reference r: rm.getReferencesTo(a)) if(r.getReferenceType().isCall()||r.getReferenceType().isJump()) c++;
    return c;
  }
  Iterable<Address> iterable(AddressIterator it){ return ()-> new Iterator<Address>(){
    public boolean hasNext(){return it.hasNext();} public Address next(){return it.next();}};}
}
