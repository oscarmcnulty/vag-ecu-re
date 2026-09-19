import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.pcode.*;

// Find the engage-FSM master dispatcher: scan every instruction for an indirect/computed
// call or jump; report the containing function together with whether that function reads the
// state var 0xfffede5c. Also dump raw xrefs to the state var and to the down-walk entries.
public class FindDispatch extends GhidraScript {
  public void run() throws Exception {
    ReferenceManager rm = currentProgram.getReferenceManager();
    // explicit xrefs to state var + entries
    long[] xs = {0xfffede5cL,0x2b626L,0x2b66aL,0x2b8b4L,0x2be80L,0x2bd28L,0x2be3aL,0x2ba40L,0x2baacL,0x2bce8L};
    for (long a: xs){
      Address ad=toAddr(a);
      println("=== xrefsTO "+Long.toHexString(a)+" ===");
      ReferenceIterator it=rm.getReferencesTo(ad); int n=0;
      while(it.hasNext()){Reference r=it.next(); Function f=getFunctionContaining(r.getFromAddress());
        println("  from "+r.getFromAddress()+" "+r.getReferenceType()+" in "+(f!=null?f.getEntryPoint():"?")); n++;}
      if(n==0) println("  (none)");
    }
    // scan for indirect calls/jumps
    println("=== indirect call/jump sites ===");
    InstructionIterator ii=currentProgram.getListing().getInstructions(true);
    while(ii.hasNext()){
      Instruction in=ii.next();
      FlowType ft=in.getFlowType();
      if((ft.isCall()||ft.isJump()) && ft.isComputed()){
        Function f=getFunctionContaining(in.getAddress());
        String fn = f!=null?f.getEntryPoint().toString():"?";
        // does containing function read the state var? check references from function body
        boolean readsState=false;
        if(f!=null){
          AddressSetView body=f.getBody();
          Address st=toAddr(0xfffede5cL);
          ReferenceIterator rit=rm.getReferencesTo(st);
          while(rit.hasNext()){ if(body.contains(rit.next().getFromAddress())){readsState=true;break;} }
        }
        println("  "+in.getAddress()+"  "+in.toString()+"  fn="+fn+(readsState?"  <READS_STATE>":""));
      }
    }
  }
}
