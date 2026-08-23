import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;
public class FindConsumers extends GhidraScript { public void run() throws Exception {
  long[] targets={0x2800,0x2801,0x2804,0x2805,0x2806,0x2807,0x283d,0x283e,0x283f,0x27fc,0x283b};
  Set<Long> T=new HashSet<>(); for(long t:targets) T.add(t);
  Map<Long,TreeMap<Long,String>> hits=new HashMap<>(); // target -> (funcEntry-> )
  Listing lis=currentProgram.getListing(); FunctionManager fm=currentProgram.getFunctionManager();
  InstructionIterator ii=lis.getInstructions(true);
  while(ii.hasNext()){ Instruction ins=ii.next();
    for(int o=0;o<ins.getNumOperands();o++) for(Object ob:ins.getOpObjects(o)) if(ob instanceof Scalar){
      long v=((Scalar)ob).getUnsignedValue();
      if(T.contains(v)){ Function f=fm.getFunctionContaining(ins.getAddress());
        long fe=f!=null?f.getEntryPoint().getOffset():0;
        String nm=f!=null?f.getName():"?";
        hits.computeIfAbsent(v,k->new TreeMap<>()).put(fe, nm+" @"+ins.getAddress());
      }
    }
  }
  for(long t:targets){ TreeMap<Long,String> m=hits.get(t);
    println(String.format("== 0x%04x : %d ref-fns ==", t, m==null?0:m.size()));
    if(m!=null) for(Map.Entry<Long,String> e:m.entrySet()) println(String.format("   fn 0x%06x  %s", e.getKey(), e.getValue()));
  }
}}
