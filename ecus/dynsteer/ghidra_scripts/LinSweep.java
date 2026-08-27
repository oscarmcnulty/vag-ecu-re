import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
public class LinSweep extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long start=Long.decode(a[0]); long len=Long.decode(a[1]);
    long imglo=Long.decode(a[2]), imghi=Long.decode(a[3]);
    Address ad=toAddr(start); Address end=toAddr(start+len);
    int valid=0,invalid=0,cf=0,cflocal=0,maxrun=0,run=0;
    while(ad.compareTo(end)<0){
      clearListing(ad,ad.add(3));
      Instruction ins=null;
      try{ disassemble(ad); ins=getInstructionAt(ad);}catch(Exception e){}
      if(ins==null){ invalid++; run=0; ad=ad.add(2); continue; }
      valid++; run++; if(run>maxrun)maxrun=run;
      String m=ins.getMnemonicString().toLowerCase();
      boolean isbr=m.startsWith("b")||m.startsWith("j")||m.startsWith("call")||m.contains("bl")||m.startsWith("bsr");
      if(isbr){ Address[] fl=ins.getFlows();
        if(fl!=null&&fl.length>0){ cf++; for(Address f:fl){ long t=f.getOffset(); if(t>=imglo&&t<imghi) cflocal++; } } }
      ad=ad.add(ins.getLength());
    }
    println(String.format("SWEEP valid=%d invalid=%d (%.1f%% bad) maxrun=%d cf=%d cflocal=%d lang=%s",
      valid,invalid,100.0*invalid/(valid+invalid),maxrun,cf,cflocal,currentProgram.getLanguageID()));
  }
}
