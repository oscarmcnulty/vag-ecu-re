import ghidra.app.script.GhidraScript; import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*; import ghidra.program.model.scalar.Scalar; import java.util.*;
public class RefsToSet extends GhidraScript { public void run() throws Exception {
  Set<Long> T=new TreeSet<>(); for(String s:getScriptArgs()) T.add(Long.decode(s));
  FunctionManager fm=currentProgram.getFunctionManager();
  Map<Long,List<String>> hits=new TreeMap<>();
  for(Instruction ins: currentProgram.getListing().getInstructions(true))
    for(int o=0;o<ins.getNumOperands();o++) for(Object ob:ins.getOpObjects(o)) if(ob instanceof Scalar){
      long v=((Scalar)ob).getUnsignedValue();
      if(T.contains(v)){ Function f=fm.getFunctionContaining(ins.getAddress());
        hits.computeIfAbsent(v,k->new ArrayList<>()).add(String.format("%s @%s in %s", ins.toString(), ins.getAddress(), f!=null?f.getName()+"@"+f.getEntryPoint():"?")); } }
  for(long t:T){ println(String.format("== 0x%x : %d refs ==",t,hits.getOrDefault(t,List.of()).size()));
    for(String h:hits.getOrDefault(t,List.of())) println("   "+h); }
}}
