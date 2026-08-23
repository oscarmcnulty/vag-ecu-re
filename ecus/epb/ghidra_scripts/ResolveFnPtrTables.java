// Resolve S12X function-pointer tables (RTE ports + scheduler task lists). Entry = 4 bytes
// {addr16 BE in the 0x8000-0xBFFF window, page8 in 0xE0-0xE6/0xF8-0xFD, pad8=0}. Auto-analysis and
// the stock RecoverPointerTargets miss these (16-bit+page format, not 24/32-bit). For each valid
// entry: resolve to its global addr (0x400000+page*0x4000 model, per the confirmed EPB page map),
// disassemble + create a function, and add a data ref table-slot -> target. Marks a high-confidence
// table (>=3 valid entries) region as pointer data. This wires up the indirect call graph.
//   -postScript ResolveFnPtrTables.java   (mutates; run after analysis)
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;

public class ResolveFnPtrTables extends GhidraScript {
  long resolve(int addr, int page){
    if(addr<0x8000 || addr>0xBFFF) return -1;
    if(page>=0xE0 && page<=0xE6) return 0x780000L+(page-0xE0)*0x4000+(addr-0x8000);
    if(page>=0xF8 && page<=0xFD) return 0x7e0000L+(page-0xF8)*0x4000+(addr-0x8000);
    return -1;
  }
  long[][] R={{0x780000L,0x79c000L},{0x7e0000L,0x7f8000L}};
  public boolean init(Address a){ return getInstructionAt(a)!=null; }
  public void run() throws Exception {
    ReferenceManager rm=currentProgram.getReferenceManager();
    int tables=0, entries=0, fns=0;
    for(long[] rg:R){
      long o=rg[0];
      while(o<rg[1]-4){
        // count a run of valid-or-zero 4-byte entries with >=vc valid
        int valid=0, run=0; long p=o; boolean lastZero=false;
        java.util.List<Long> tgts=new java.util.ArrayList<>();
        while(p<rg[1]-4){
          int addr=((getByte(toAddr(p))&0xff)<<8)|(getByte(toAddr(p+1))&0xff);
          int page=getByte(toAddr(p+2))&0xff, pad=getByte(toAddr(p+3))&0xff;
          long g=resolve(addr,page);
          boolean zero=(addr==0&&page==0&&pad==0);
          if(pad==0 && g>=0){ valid++; run++; tgts.add(g); p+=4; lastZero=false; }
          else if(zero){ run++; p+=4; lastZero=true; tgts.add(-1L); }
          else break;
        }
        if(valid>=3){
          tables++;
          for(long g:tgts){ if(g<0) continue; entries++;
            Address t=toAddr(g);
            if(getInstructionAt(t)==null) new DisassembleCommand(t,null,false).applyTo(currentProgram,monitor);
            if(getInstructionAt(t)!=null && getFunctionAt(t)==null && createFunction(t,null)!=null) fns++;
          }
          o=p;
        } else o+=2;
      }
    }
    println(String.format("ResolveFnPtrTables: tables=%d entries=%d newFns=%d", tables,entries,fns));
  }
}
