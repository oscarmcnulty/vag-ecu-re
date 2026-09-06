import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import java.util.*;

public class EspEpb extends GhidraScript {
  AddressSpace sp; ReferenceManager rm; DecompInterface di;
  Address a(long v){ return sp.getAddress(v); }

  void refs(long lo,long hi){
    for(long t=lo;t<=hi;t++){
      ReferenceIterator ri=rm.getReferencesTo(a(t));
      while(ri.hasNext()){ Reference r=ri.next(); RefType rt=r.getReferenceType();
        Function f=getFunctionContaining(r.getFromAddress());
        println(String.format("  0x%08x %-6s from %s  %s", t,
          rt.isWrite()?"WRITE":(rt.isRead()?"read":rt.getName()),
          r.getFromAddress(), f!=null?f.getName()+"@"+f.getEntryPoint():"(no fn)"));
      }
    }
  }
  void decomp(long v){
    Function f=getFunctionContaining(a(v));
    if(f==null){ println("// no func @"+Long.toHexString(v)); return; }
    println("// ======== "+f.getName()+" @"+f.getEntryPoint()+" ========");
    DecompileResults r=di.decompileFunction(f,90,monitor);
    if(r!=null&&r.decompileCompleted()) println(r.getDecompiledFunction().getC());
    else println("// decompile failed");
  }
  public void run() throws Exception {
    sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    rm=currentProgram.getReferenceManager();
    di=new DecompInterface(); di.openProgram(currentProgram);
    String[] args=getScriptArgs();
    if(args.length>0 && args[0].equals("refs")){
      for(int i=1;i<args.length;i++){ long v=Long.parseLong(args[i],16);
        println("### REFS to 0x"+Long.toHexString(v)); refs(v,v); }
    } else if(args.length>0 && args[0].equals("refsrange")){
      long lo=Long.parseLong(args[1],16), hi=Long.parseLong(args[2],16);
      println("### REFS range"); refs(lo,hi);
    } else {
      for(String s:args) decomp(Long.parseLong(s,16));
    }
  }
}
