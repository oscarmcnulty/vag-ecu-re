// Resolve S12X indexed-dispatch tables and inject them into the Ghidra program so the decompiler
// follows the dispatch. Two parts:
//  (1) For every indexed-indirect CALL (0x4B + [n16,X/Y/SP] postbyte) whose n16 lands in the
//      fixed-low page (0x4000-0x7FFF -> global 0x7F4000+), treat n16 as a dispatch-table base.
//  (2) Densely scan the fixed-low page for {addr16 BE (0x4000-0xBFFF), page8 (0xE0-0xE6/0xF8-0xFD),
//      pad8=0} entries; each resolves to a global code addr. Create a function at each target and,
//      for entries inside a table referenced by a CALL site, add a CALL reference site->target so
//      the call graph (and decompile) includes the dispatched SWCs.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import java.util.*;

public class EpbResolveDispatch extends GhidraScript {
  long resolve(int a,int pg){
    if(a<0x8000||a>0xBFFF) return -1;
    if(pg>=0xE0&&pg<=0xE6) return 0x780000L+(pg-0xE0)*0x4000+(a-0x8000);
    if(pg>=0xF8&&pg<=0xFD) return 0x7e0000L+(pg-0xF8)*0x4000+(a-0x8000);
    return -1;
  }
  int u8(long a){ try{return getByte(toAddr(a))&0xff;}catch(Exception e){return -1;} }
  public void run() throws Exception {
    ReferenceManager rm=currentProgram.getReferenceManager();
    long LO=0x7f4000L, HI=0x7f8000L;
    // 1) collect indexed-CALL sites (0x4B + [n16,r]) referencing fixed-low table bases
    Map<Long,List<Address>> tableSites=new HashMap<>();
    for(Instruction ins: currentProgram.getListing().getInstructions(true)){
      Address a=ins.getAddress(); int op=u8(a.getOffset());
      if(op==0x4B){ int pb=u8(a.getOffset()+1);
        if((pb&0xE7)==0xE2||(pb&0xE7)==0xE3){ int n16=(u8(a.getOffset()+2)<<8)|u8(a.getOffset()+3);
          if(n16>=0x4000&&n16<=0x7FFF){ long base=0x7F4000L+(n16-0x4000); tableSites.computeIfAbsent(base,k->new ArrayList<>()).add(a); } } }
    }
    // 1b) [n16,PC] code-page jump tables: table = site+4 + signext16(n16)
    List<long[]> pcTables=new ArrayList<>();
    for(Instruction ins: currentProgram.getListing().getInstructions(true)){
      Address a=ins.getAddress(); if(u8(a.getOffset())!=0x4B) continue;
      int pb=u8(a.getOffset()+1);
      if(pb==0xFA||pb==0xFB){ int n16=(u8(a.getOffset()+2)<<8)|u8(a.getOffset()+3);
        int sn=(n16>0x7fff)?n16-0x10000:n16; long tbl=a.getOffset()+4+sn;
        pcTables.add(new long[]{tbl, a.getOffset()}); }
    }
    int pcFns=0,pcRefs=0;
    for(long[] pt: pcTables){ long tbl=pt[0]; Address site=toAddr(pt[1]);
      for(int k=0;k<24;k++){ long q=tbl+k*4; int a=(u8(q)<<8)|u8(q+1),pg=u8(q+2),pad=u8(q+3);
        long g=resolve(a,pg); if(g<0||pad!=0) break;
        Address t=toAddr(g); if(getInstructionAt(t)==null) new DisassembleCommand(t,null,false).applyTo(currentProgram,monitor);
        if(getInstructionAt(t)!=null && getFunctionAt(t)==null && createFunction(t,null)!=null) pcFns++;
        rm.addMemoryReference(site,t,RefType.COMPUTED_CALL,SourceType.ANALYSIS,0); pcRefs++; } }
    println("EpbResolveDispatch: PC-tables="+pcTables.size()+" pcFns="+pcFns+" pcRefs="+pcRefs);
    // 2) dense scan fixed-low page for {addr16,page,pad} entries
    int fns=0, refs=0, entries=0;
    for(long p=LO;p<HI-3;p++){
      int a=(u8(p)<<8)|u8(p+1), pg=u8(p+2), pad=u8(p+3);
      long g=resolve(a,pg);
      if(g<0||pad!=0) continue;
      entries++;
      Address t=toAddr(g);
      if(getInstructionAt(t)==null) new DisassembleCommand(t,null,false).applyTo(currentProgram,monitor);
      if(getInstructionAt(t)!=null && getFunctionAt(t)==null && createFunction(t,null)!=null) fns++;
      // if this slot is within 0x100 bytes after a CALL-table base, add a call ref from the site
      for(Map.Entry<Long,List<Address>> e: tableSites.entrySet()){
        if(p>=e.getKey() && p<e.getKey()+0x200){
          for(Address site: e.getValue()){ rm.addMemoryReference(site,t,RefType.COMPUTED_CALL,SourceType.ANALYSIS,0); refs++; }
        }
      }
    }
    println(String.format("EpbResolveDispatch: table-sites=%d fixed-low entries=%d newFns=%d callRefs=%d",
      tableSites.size(), entries, fns, refs));
  }
}
