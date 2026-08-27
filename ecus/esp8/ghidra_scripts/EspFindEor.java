// Find XOR-checksum candidates: functions with many EOR insns on byte loads.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import java.util.*;
public class EspFindEor extends GhidraScript {
    public void run() throws Exception {
        Map<Function,int[]> stat=new HashMap<>(); // [eor, ldrb]
        InstructionIterator it=currentProgram.getListing().getInstructions(true);
        while(it.hasNext()){
            Instruction ins=it.next();
            if(ins.getAddress().getOffset()>=0xa2800) continue;
            String mn=ins.getMnemonicString().toLowerCase();
            Function f=getFunctionContaining(ins.getAddress());
            if(f==null) continue;
            int[] s=stat.computeIfAbsent(f,k->new int[2]);
            if(mn.startsWith("eor")) s[0]++;
            if(mn.equals("ldrb")||mn.equals("ldrbcc")) s[1]++;
        }
        List<Map.Entry<Function,int[]>> l=new ArrayList<>(stat.entrySet());
        l.sort((a,b)->b.getValue()[0]-a.getValue()[0]);
        println("EOR-heavy functions (checksum candidates):");
        int n=0;
        for(Map.Entry<Function,int[]> e:l){
            if(e.getValue()[0]<4) break;
            println(String.format("  %s @%s : eor=%d ldrb=%d",e.getKey().getName(),
                e.getKey().getEntryPoint(),e.getValue()[0],e.getValue()[1]));
            if(++n>=15) break;
        }
    }
}
