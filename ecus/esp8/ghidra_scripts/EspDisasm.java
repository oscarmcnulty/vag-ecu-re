import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
public class EspDisasm extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Address start = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(Long.parseLong(a[0],16));
        int count = a.length>1? Integer.parseInt(a[1]) : 60;
        InstructionIterator it = currentProgram.getListing().getInstructions(start, true);
        int n=0;
        while (it.hasNext() && n<count) {
            Instruction ins = it.next(); n++;
            byte[] b = ins.getBytes();
            StringBuilder hx=new StringBuilder();
            for (byte x: b) hx.append(String.format("%02x",x));
            println(String.format("  %s %-8s (%dB) %s", ins.getAddress(), hx, b.length, ins.toString()));
        }
    }
}
