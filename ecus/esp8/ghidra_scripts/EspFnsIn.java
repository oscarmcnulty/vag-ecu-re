import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
public class EspFnsIn extends GhidraScript {
    public void run() throws Exception {
        String[] a=getScriptArgs();
        long lo=Long.parseLong(a[0],16), hi=Long.parseLong(a[1],16);
        AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        FunctionIterator it=currentProgram.getFunctionManager().getFunctions(sp.getAddress(lo),true);
        while(it.hasNext()){ Function f=it.next();
            if(f.getEntryPoint().getOffset()>=hi) break;
            println(String.format("  %s @%s  size=0x%x", f.getName(), f.getEntryPoint(), f.getBody().getNumAddresses())); }
    }
}
