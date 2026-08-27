// Generic per-variant prep: map a RAM block, report where code actually lives, and
// (optionally) clear analyzer-fabricated code in the data region.
//   args: <ramBase> <ramSize> [<dataLo> <dataHi>]      (all hex, no 0x)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import java.util.*;

public class EspPrep extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        long ramBase = Long.parseLong(a[0],16), ramSize = Long.parseLong(a[1],16);
        if (mem.getBlock("RAM")==null) {
            MemoryBlock b = mem.createUninitializedBlock("RAM", sp.getAddress(ramBase), ramSize, false);
            b.setRead(true); b.setWrite(true); b.setExecute(false); b.setVolatile(true);
            println("EspPrep: added RAM "+Long.toHexString(ramBase)+" +"+Long.toHexString(ramSize));
        } else println("EspPrep: RAM block already present");

        FunctionManager fm = currentProgram.getFunctionManager();
        TreeMap<Long,Integer> hist = new TreeMap<>();
        int n=0;
        for (Function f : fm.getFunctions(true)) {
            long e = f.getEntryPoint().getOffset();
            if (e >= ramBase) continue;
            hist.merge(e>>16, 1, Integer::sum); n++;
        }
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<Long,Integer> e : hist.entrySet())
            sb.append(String.format("%x:%d ", e.getKey()<<16, e.getValue()));
        println("EspPrep: "+n+" flash functions by 64KB bucket: "+sb);

        if (a.length >= 4) {
            Address lo = sp.getAddress(Long.parseLong(a[2],16)), hi = sp.getAddress(Long.parseLong(a[3],16));
            List<Address> rm = new ArrayList<>();
            FunctionIterator it = fm.getFunctions(lo, true);
            while (it.hasNext()) { Function f=it.next(); if (f.getEntryPoint().compareTo(hi)>=0) break; rm.add(f.getEntryPoint()); }
            for (Address ad : rm) fm.removeFunction(ad);
            currentProgram.getListing().clearCodeUnits(lo, hi.subtract(1), false);
            println("EspPrep: removed "+rm.size()+" functions and cleared code in "+lo+"-"+hi);
        }
    }
}
