import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.FlowType;
import java.util.*;
public class FullSweep extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long start=Long.decode(a[0]), len=Long.decode(a[1]);
    long lo=Long.decode(a[2]), hi=Long.decode(a[3]);
    Address ad=toAddr(start), end=toAddr(start+len);
    int valid=0,invalid=0,rets=0,calls=0;
    HashMap<Long,Integer> tgt=new HashMap<>();
    while(ad.compareTo(end)<0){
      clearListing(ad,ad.add(3));
      Instruction ins=null;
      try{disassemble(ad); ins=getInstructionAt(ad);}catch(Exception e){}
      if(ins==null){invalid++; ad=ad.add(2); continue;}
      valid++;
      FlowType ft=ins.getFlowType();
      if(ft.isTerminal()) rets++;
      if(ft.isCall()){ calls++;
        for(Address f:ins.getFlows()){ long t=f.getOffset();
          if(t>=lo&&t<hi) tgt.merge(t,1,Integer::sum); } }
      ad=ad.add(ins.getLength());
    }
    int reused=0,total=0; long maxc=0;
    for(int c:tgt.values()){ total++; if(c>=2)reused++; if(c>maxc)maxc=c;}
    println(String.format("FULL lang=%s valid=%d invalid=%d(%.0f%%) rets=%d calls=%d distinctTargets=%d reused>=2=%d maxhits=%d",
      currentProgram.getLanguageID(),valid,invalid,100.0*invalid/(valid+invalid),rets,calls,total,reused,maxc));
  }
}
