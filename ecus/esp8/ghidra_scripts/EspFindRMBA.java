// Decompile every function in [lo,hi]; print those whose C parses an addr-and-length
// format identifier (contains both ">> 4" and "& 0xf") or does a length-bounded copy.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
public class EspFindRMBA extends GhidraScript {
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
      boolean nib = c.contains(">> 4") && (c.contains("& 0xf")||c.contains("& 0xF"));
      boolean fmt = c.contains("0x44") || c.contains("format");
      if(nib){ n++; println("HIT nibble @"+f.getEntryPoint()+" "+f.getName()+" (len="+c.length()+")"); }
    }
    println("nibble-parse candidates: "+n);
  }
}
