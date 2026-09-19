import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
public class EspSeg2Probe extends GhidraScript {
  public void run() throws Exception {
    Memory mem=currentProgram.getMemory();
    for (MemoryBlock b: mem.getBlocks())
      println(String.format("BLOCK %-8s %#010x..%#010x exec=%b init=%b",
        b.getName(), b.getStart().getOffset(), b.getEnd().getOffset(), b.isExecute(), b.isInitialized()));
    // count functions in seg2 (>=0xbb000)
    FunctionIterator fi=currentProgram.getFunctionManager().getFunctions(true);
    int seg2=0,tot=0; long minS=Long.MAX_VALUE,maxS=0;
    while(fi.hasNext()){Function f=fi.next();tot++;long e=f.getEntryPoint().getOffset();
      if(e>=0xbb000){seg2++; if(e<minS)minS=e; if(e>maxS)maxS=e;}}
    println("functions total="+tot+" seg2(>=0xbb000)="+seg2+" range="+Long.toHexString(minS)+".."+Long.toHexString(maxS));
  }
}
