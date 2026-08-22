// Apply the boot-copied RAM .data pointer tables recovered from init stubs. Unlike a naive
// whole-RAM init (which folds every mutable scalar to its power-on value), this initializes
// ONLY the contiguous const pointer-table regions the init stubs populate, leaving the rest
// of RAM uninitialized so runtime variables stay symbolic. Analogous to ApplyLoadImage but
// SH-2A, and surgical.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ApplyRamDataImage.java <ram_bases.csv> [gap]
// CSV: ram_addr,value (hex). Clusters slots with gap<=GAP (default 0x40) into initialized
// blocks; writes each value BE-u32; adds a data ref slot->target and a pointer type.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.data.*;
import ghidra.program.model.symbol.*;
import java.nio.file.*; import java.util.*;
public class ApplyRamDataImage extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long gap = a.length>1 ? Long.decode(a[1]) : 0x40;
    List<long[]> rows=new ArrayList<>();
    for(String ln: Files.readAllLines(Paths.get(a[0]))){
      ln=ln.trim(); if(ln.isEmpty()||ln.startsWith("ram_addr")) continue;
      String[] p=ln.split(","); rows.add(new long[]{Long.decode(p[0].trim()),Long.decode(p[1].trim())});
    }
    rows.sort((x,y)->Long.compare(x[0],y[0]));
    Memory mem=currentProgram.getMemory();
    // cluster
    List<List<long[]>> cl=new ArrayList<>(); List<long[]> cur=new ArrayList<>();
    for(long[] r: rows){ if(!cur.isEmpty() && r[0]-cur.get(cur.size()-1)[0]>gap){ cl.add(cur); cur=new ArrayList<>(); } cur.add(r); }
    if(!cur.isEmpty()) cl.add(cur);
    int wrote=0, blocks=0;
    for(List<long[]> c: cl){
      long lo=c.get(0)[0], hi=c.get(c.size()-1)[0]+4;
      Address alo=toAddr(lo);
      MemoryBlock b=mem.getBlock(alo);
      if(b==null){ println("  no block covering 0x"+Long.toHexString(lo)+"; skip"); continue; }
      // split the covering uninitialized block so [lo,hi) is its own block, then initialize it
      try {
        if(b.getStart().getOffset()<lo){ mem.split(b, alo); b=mem.getBlock(alo); }
        if(b.getEnd().getOffset()>=hi){ mem.split(b, toAddr(hi)); b=mem.getBlock(alo); }
        if(!b.isInitialized()){ mem.convertToInitialized(b,(byte)0); blocks++; }
      } catch(Exception e){ println("  split/init failed @0x"+Long.toHexString(lo)+": "+e); continue; }
      for(long[] r: c){
        long v=r[1];
        mem.setBytes(toAddr(r[0]), new byte[]{(byte)(v>>24),(byte)(v>>16),(byte)(v>>8),(byte)v});
        // type as pointer + add ref
        try { clearListing(toAddr(r[0]), toAddr(r[0]+3)); createData(toAddr(r[0]), PointerDataType.dataType); } catch(Exception e){}
        wrote++;
      }
    }
    println("ApplyRamDataImage: wrote="+wrote+" ptr slots, initialized "+blocks+" table blocks, "+cl.size()+" clusters");
  }
}
