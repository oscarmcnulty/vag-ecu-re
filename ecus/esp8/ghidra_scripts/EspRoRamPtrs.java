// Mark the ApplyRamDataImage-initialized pointer-table RAM blocks READ-ONLY (non-write) so the
// ARM decompiler constant-folds *(base) -> target (it won't fold a writable RAM read). Only the
// small initialized pointer-table blocks are touched; the big uninit RAM stays rw.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.*;
public class EspRoRamPtrs extends GhidraScript {
  public void run() throws Exception {
    Memory mem=currentProgram.getMemory(); int ro=0;
    for (MemoryBlock b: mem.getBlocks()){
      long s=b.getStart().getOffset();
      // initialized blocks inside RAM (0x400000-0x40ffff) that ApplyRamDataImage created
      if (s>=0x400000 && s<0x410000 && b.isInitialized() && b.isWrite()){
        b.setWrite(false); ro++;
        println(String.format("  RO: %s %s-%s", b.getName(), b.getStart(), b.getEnd()));
      }
    }
    println("EspRoRamPtrs: set "+ro+" initialized RAM ptr blocks read-only");
  }
}
