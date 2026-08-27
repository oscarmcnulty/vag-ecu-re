import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
public class SweepAll extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long base=Long.decode(a[0]), end=Long.decode(a[1]), step=0x2000;
    for(long off=base; off<end; off+=step){
      Address ad=toAddr(off); int ok=0,bad=0;
      for(int i=0;i<64 && ad.getOffset()<off+step;i++){
        clearListing(ad,ad.add(3));
        Instruction ins=null; try{disassemble(ad); ins=getInstructionAt(ad);}catch(Exception e){}
        if(ins==null){bad++; ad=ad.add(2);} else {ok++; ad=ad.add(ins.getLength());}
      }
      int pct=100*bad/(ok+bad);
      println(String.format("%08x bad=%d%% %s", off, pct, pct<=15?"<== CODE?":""));
    }
  }
}
