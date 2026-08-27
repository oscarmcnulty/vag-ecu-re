// Scan the whole image for 32-bit words equal to each given constant; report location+function.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
public class EspFindConst extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long[] tgt=new long[a.length]; for(int i=0;i<a.length;i++) tgt[i]=Long.parseLong(a[i],16);
    Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    for(MemoryBlock b: mem.getBlocks()){ if(!b.isInitialized()) continue;
      long lo=b.getStart().getOffset(), hi=b.getEnd().getOffset();
      for(long o=lo;o+4<=hi+1;o+=2){ int v; try{v=mem.getInt(sp.getAddress(o));}catch(Exception e){continue;}
        long vv=v & 0xffffffffL;
        for(long t: tgt) if(vv==t){ Function f=getFunctionContaining(sp.getAddress(o));
          println(String.format("  0x%08x = 0x%08x  in %s", o, t, f!=null?f.getName()+"@"+f.getEntryPoint():"(data/no-fn)")); }
      }
    }
  }
}
