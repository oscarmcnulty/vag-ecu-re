import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;
import java.util.*;
public class EspHunt extends GhidraScript {
    public void run() throws Exception {
        AddressFactory af=currentProgram.getAddressFactory();
        // (a) UDS SID dispatch (any instr size now that Thumb is decoded)
        int[] SIDS={0x10,0x11,0x14,0x19,0x22,0x23,0x27,0x28,0x2e,0x2f,0x31,0x34,0x35,0x36,0x37,0x3d,0x3e,0x85};
        Set<Integer> ss=new HashSet<>(); for(int s:SIDS) ss.add(s);
        Map<Function,Set<Integer>> hit=new HashMap<>();
        InstructionIterator it=currentProgram.getListing().getInstructions(true);
        while(it.hasNext()){
            Instruction ins=it.next();
            String mn=ins.getMnemonicString().toLowerCase();
            if(!(mn.startsWith("cmp")||mn.startsWith("sub")||mn.startsWith("teq"))) continue;
            for(int oi=0;oi<ins.getNumOperands();oi++) for(Object o:ins.getOpObjects(oi))
                if(o instanceof Scalar){ int v=(int)((Scalar)o).getUnsignedValue();
                    if(ss.contains(v)){ Function f=getFunctionContaining(ins.getAddress());
                        if(f!=null) hit.computeIfAbsent(f,k->new TreeSet<>()).add(v);}}
        }
        List<Map.Entry<Function,Set<Integer>>> l=new ArrayList<>(hit.entrySet());
        l.sort((a,b)->b.getValue().size()-a.getValue().size());
        println("=== UDS SID-dispatch candidates (>=5 SIDs) ===");
        for(Map.Entry<Function,Set<Integer>> e:l){ if(e.getValue().size()<5) continue;
            StringBuilder sb=new StringBuilder(); for(int v:e.getValue()) sb.append(String.format("%02x ",v));
            println(String.format("  %s @%s : %d [ %s]",e.getKey().getName(),e.getKey().getEntryPoint(),e.getValue().size(),sb));}
        // (c) xrefs to ESP_05 table entry 0xb33dc and ID-array 0xafb08
        for(long a: new long[]{0xb33dcL,0xb33d0L,0xafb08L,0xafae0L}){
            Address ad=af.getDefaultAddressSpace().getAddress(a);
            ReferenceIterator ri=currentProgram.getReferenceManager().getReferencesTo(ad);
            int n=0; StringBuilder sb=new StringBuilder();
            while(ri.hasNext()){ Reference r=ri.next(); n++;
                Function f=getFunctionContaining(r.getFromAddress());
                sb.append(" "+r.getFromAddress()+(f!=null?"("+f.getName()+")":"")); }
            println(String.format("xrefs to 0x%06x: %d%s", a, n, sb));
        }
    }
}
