import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class SweepProbe extends GhidraScript {
    public void run() throws Exception {
        long base=0x80000000L, end=0x80050000L;
        long step=0x2000;
        for (long off=base; off<end; off+=step){
            Address ad=toAddr(off);
            int ok=0,bad=0,br=0,brlocal=0;
            for(int i=0;i<48;i++){
                clearListing(ad, ad.add(3));
                disassemble(ad);
                Instruction ins=getInstructionAt(ad);
                if(ins==null){bad++; ad=ad.add(2); continue;}
                ok++;
                String m=ins.toString();
                if(m.startsWith("j")||m.startsWith("call")||m.startsWith("loop")){
                    br++;
                    // local branch target within image?
                    try{ Address[] fl=ins.getFlows();
                        for(Address f: fl){ long t=f.getOffset(); if(t>=base&&t<end) brlocal++; }
                    }catch(Exception e){}
                }
                ad=ad.add(ins.getLength());
            }
            println(String.format("%08x ok=%2d bad=%2d br=%2d local=%2d", off, ok, bad, br, brlocal));
        }
    }
}
