import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class DisasmProbe extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        long start = Long.decode(a[0]);
        int count = a.length>1? Integer.decode(a[1]) : 60;
        Address ad = toAddr(start);
        int ok=0, bad=0;
        StringBuilder sb = new StringBuilder();
        for (int i=0;i<count;i++){
            clearListing(ad, ad.add(3));
            disassemble(ad);
            Instruction ins = getInstructionAt(ad);
            if (ins==null){ sb.append(String.format("%08x  <bad>\n", ad.getOffset())); bad++;
                ad = ad.add(2); continue; }
            byte[] by = ins.getBytes();
            StringBuilder hx = new StringBuilder();
            for (byte x: by) hx.append(String.format("%02x", x));
            sb.append(String.format("%08x  %-12s %s\n", ad.getOffset(), hx.toString(), ins.toString()));
            ok++;
            ad = ad.add(ins.getLength());
        }
        println("PROBE @"+a[0]+"  ok="+ok+" bad="+bad+"\n"+sb.toString());
    }
}
