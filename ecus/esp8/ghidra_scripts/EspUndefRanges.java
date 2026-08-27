// List undefined ranges in the code region, classify code-like vs data-like.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
public class EspUndefRanges extends GhidraScript {
  public void run() throws Exception {
    long LO=0x0, HI=0xa2800;
    Listing lst=currentProgram.getListing();
    Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    long a=LO; int nRanges=0; long codeLike=0, dataLike=0;
    while(a<HI){
      Address ad=sp.getAddress(a);
      CodeUnit cu=lst.getCodeUnitAt(ad);
      if(cu instanceof Data && !((Data)cu).isDefined()){
        long start=a;
        while(a<HI){ Address x=sp.getAddress(a); CodeUnit c2=lst.getCodeUnitAt(x);
          if(c2 instanceof Data && !((Data)c2).isDefined()) a+=1; else break; }
        long len=a-start;
        if(len>=8){
          // classify: fraction of 0xE-top-nibble ARM words + Thumb push density
          int arm=0,n=0,ram=0;
          for(long o=start;o+4<=start+len;o+=4){ int w=mem.getInt(sp.getAddress(o)); n++;
            if((w>>>28)==0xE) arm++; if((w&0xFFFF0000)==0x00400000 || (0x400000<=w&&w<0x480000)) ram++; }
          String cls = (n>0 && arm*100/n>25)?"CODE?":((n>0&&ram*100/Math.max(1,n)>30)?"PTRTAB":"data");
          if(cls.equals("CODE?")) codeLike+=len; else dataLike+=len;
          if(len>=32) println(String.format("  0x%06x +0x%-5x %s (arm%%=%d ram%%=%d)", start, len, cls, n>0?arm*100/n:0, n>0?ram*100/n:0));
          nRanges++;
        }
      } else a+=Math.max(1,cu!=null?cu.getLength():1);
    }
    println(String.format("undef ranges>=8B: %d; code-like ~%d bytes, data-like ~%d bytes", nRanges, codeLike, dataLike));
  }
}
