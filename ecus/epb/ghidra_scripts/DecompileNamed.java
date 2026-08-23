// Decompile only the functions whose entry addresses are listed (one hex vaddr per line).
// Fast, focused alternative to the whole-corpus DecompileAll for a small confirmed symbol set.
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -postScript DecompileNamed.java <outDir> <addrListFile>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.*; import java.nio.file.*; import java.util.*;

public class DecompileNamed extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    String outDir=a[0]; String list=a[1];
    new File(outDir).mkdirs();
    DecompInterface di=new DecompInterface(); di.openProgram(currentProgram);
    int ok=0,fail=0;
    for (String raw: Files.readAllLines(Paths.get(list))) {
      String s=raw.trim(); if(s.isEmpty()||s.startsWith("#")) continue;
      Address at=toAddr(Long.decode(s.startsWith("0x")?s:"0x"+s));
      Function fn=getFunctionAt(at);
      if(fn==null){ println("  no function @"+s); fail++; continue; }
      DecompileResults r=di.decompileFunction(fn,120,monitor);
      String c=(r!=null&&r.decompileCompleted())?r.getDecompiledFunction().getC():null;
      if(c==null){ println("  FAIL "+fn.getName()); fail++; continue; }
      try(FileWriter w=new FileWriter(outDir+"/"+fn.getName()+".c")){ w.write(c); }
      ok++;
    }
    println("DecompileNamed: ok="+ok+" fail="+fail+" -> "+outDir);
  }
}
