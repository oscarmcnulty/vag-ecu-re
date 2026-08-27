// UDS SID-dispatch search restricted to 4-byte ARM instructions (reliable decode).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;
public class EspFindDiag extends GhidraScript {
    public void run() throws Exception {
        int[] SIDS = {0x10,0x11,0x14,0x19,0x22,0x23,0x27,0x28,0x2e,0x2f,0x31,0x34,0x35,0x36,0x37,0x3d,0x3e,0x85};
        Set<Integer> sidset=new HashSet<>(); for(int s:SIDS) sidset.add(s);
        Map<Function,Set<Integer>> hit=new HashMap<>();
        InstructionIterator it=currentProgram.getListing().getInstructions(true);
        while(it.hasNext()){
            Instruction ins=it.next();
            if(ins.getBytes().length!=4) continue;          // ARM only
            String mn=ins.getMnemonicString().toLowerCase();
            if(!(mn.startsWith("cmp")||mn.startsWith("sub")||mn.startsWith("teq")||mn.startsWith("rsb"))) continue;
            for(int oi=0;oi<ins.getNumOperands();oi++)
                for(Object o:ins.getOpObjects(oi))
                    if(o instanceof Scalar){
                        int v=(int)((Scalar)o).getUnsignedValue();
                        if(sidset.contains(v)){
                            Function f=getFunctionContaining(ins.getAddress());
                            if(f!=null) hit.computeIfAbsent(f,k->new TreeSet<>()).add(v);
                        }
                    }
        }
        List<Map.Entry<Function,Set<Integer>>> l=new ArrayList<>(hit.entrySet());
        l.sort((a,b)->b.getValue().size()-a.getValue().size());
        println("=== ARM-only UDS SID-dispatch candidates (>=4 SIDs) ===");
        for(Map.Entry<Function,Set<Integer>> e:l){
            if(e.getValue().size()<4) continue;
            StringBuilder sb=new StringBuilder(); for(int v:e.getValue()) sb.append(String.format("%02x ",v));
            println(String.format("  %s @%s : %d SIDs [ %s]",e.getKey().getName(),e.getKey().getEntryPoint(),e.getValue().size(),sb));
        }
    }
}
