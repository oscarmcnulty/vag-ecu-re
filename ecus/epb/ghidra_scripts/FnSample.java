import ghidra.app.script.GhidraScript; import ghidra.program.model.listing.*;
import ghidra.app.decompiler.*; import ghidra.program.model.address.Address;
public class FnSample extends GhidraScript { public void run() throws Exception {
  FunctionManager fm=currentProgram.getFunctionManager();
  long b0=0,b1=0,b2=0,b3=0; // byte totals per bucket
  for(Function f: fm.getFunctions(true)){ long s=f.getBody().getNumAddresses();
    if(s<=6)b0+=s; else if(s<32)b1+=s; else if(s<128)b2+=s; else b3+=s; }
  println(String.format("bytes  <=6:%d  7-31:%d  32-127:%d  >=128:%d", b0,b1,b2,b3));
  // sample-decompile up to 20 tiny (<=6B) fns, count how many are 'bad instruction'/empty vs real
  DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
  int n=0,bad=0,real=0;
  for(Function f: fm.getFunctions(true)){ if(f.getBody().getNumAddresses()>6) continue; if(n>=25) break; n++;
    DecompileResults r=di.decompileFunction(f,20,monitor);
    String c=(r!=null&&r.decompileCompleted())?r.getDecompiledFunction().getC():null;
    boolean isbad = c==null || c.contains("Bad instruction") || c.contains("halt_baddata") || c.trim().endsWith("{ }");
    if(isbad) bad++; else real++;
    if(n<=8) println(String.format("  tiny @%s (%dB): %s", f.getEntryPoint(), f.getBody().getNumAddresses(), c==null?"<null>":c.replaceAll("\\s+"," ").replaceAll("/\\*.*?\\*/","").trim().substring(0,Math.min(90,c.replaceAll("\\s+"," ").trim().length()))));
  }
  println(String.format("tiny sample n=%d real=%d bad=%d", n,real,bad));
}}
