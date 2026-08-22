// Apply a statically-recovered RAM init image (const base pointers installed by boot init stubs)
// into the RAM block so the decompiler folds *(base+off) indirection to concrete addresses.
// Input CSV: ram_addr,value (hex). Writes value as big-endian u32 at ram_addr, marking the
// bytes initialized. Pointer-valued (const base) installs ONLY -- do not feed mutable scalars.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.*;
import java.nio.file.*; import java.util.*;
public class ApplyRamImage extends GhidraScript {
  public void run() throws Exception {
    String csv=getScriptArgs()[0];
    Memory mem=currentProgram.getMemory();
    int applied=0, made=0;
    boolean big=currentProgram.getLanguage().isBigEndian();
    for(String ln: Files.readAllLines(Paths.get(csv))){
      ln=ln.trim(); if(ln.isEmpty()||ln.startsWith("ram_addr")) continue;
      String[] p=ln.split(","); if(p.length<2) continue;
      long ra=Long.decode(p[0].trim()), val=Long.decode(p[1].trim());
      Address a=toAddr(ra);
      MemoryBlock b=mem.getBlock(a);
      if(b==null){ continue; }
      if(!b.isInitialized()){
        // convert the covering uninitialized block to initialized once
        try { mem.convertToInitialized(b,(byte)0); made++; } catch(Exception e){}
      }
      byte[] be=new byte[]{(byte)(val>>24),(byte)(val>>16),(byte)(val>>8),(byte)val};
      mem.setBytes(a, be);
      applied++;
    }
    println("ApplyRamImage: applied="+applied+" blocks-initialized="+made);
  }
}
