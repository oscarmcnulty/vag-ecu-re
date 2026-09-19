// Find UDS memory-service handlers: decompiled C containing the addressAndLengthFormatIdentifier
// parse -- a length nibble (>>4), an address nibble (&0xf), AND byte-wise address assembly (<<8).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
public class EspFindALFID extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long lo=Long.parseLong(a[0],16), hi=Long.parseLong(a[1],16);
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    FunctionIterator fi=currentProgram.getFunctionManager().getFunctions(true);
    int n=0;
    while(fi.hasNext()){
      Function f=fi.next(); long e=f.getEntryPoint().getOffset();
      if(e<lo||e>=hi) continue;
      DecompileResults r=di.decompileFunction(f,45,monitor);
      if(r==null||!r.decompileCompleted()) continue;
      String c=r.getDecompiledFunction().getC();
      boolean shl8 = c.contains("<< 8") || c.contains("<< 0x8");
      boolean nib  = (c.contains(">> 4")||c.contains(">> 0x4")) && (c.contains("& 0xf")||c.contains("& 0xF"));
      boolean cpy  = c.contains("mem_copy")||c.contains("memcpy")||c.contains("mem_cpy");
      if(shl8 && (nib||cpy)){
        n++;
        String tag=(nib?"NIB":"")+(cpy?"CPY":"")+(shl8?"SHL8":"");
        println("HIT @"+f.getEntryPoint()+" "+f.getName()+" ["+tag+"] len="+c.length());
      }
    }
    println("ALFID candidates: "+n);
  }
}
