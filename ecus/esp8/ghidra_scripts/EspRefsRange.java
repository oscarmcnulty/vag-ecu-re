// Report all references into a RAM address range, with R/W type and containing function.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
public class EspRefsRange extends GhidraScript {
    public void run() throws Exception {
        String[] a=getScriptArgs();
        long lo=Long.parseLong(a[0],16), hi=Long.parseLong(a[1],16);
        AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        ReferenceManager rm=currentProgram.getReferenceManager();
        for (long t=lo;t<=hi;t++){
            Address ad=sp.getAddress(t);
            ReferenceIterator ri=rm.getReferencesTo(ad);
            while(ri.hasNext()){
                Reference r=ri.next();
                RefType rt=r.getReferenceType();
                Function f=getFunctionContaining(r.getFromAddress());
                println(String.format("  0x%08x %-6s from %s  %s", t,
                    rt.isWrite()?"WRITE":(rt.isRead()?"read":rt.getName()),
                    r.getFromAddress(), f!=null?f.getName()+"@"+f.getEntryPoint():"(no fn)"));
            }
        }
    }
}
