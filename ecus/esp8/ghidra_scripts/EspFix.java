// One-time cleanup: add RAM block, clear bogus code in the data region 0xa2000-0x134011.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
public class EspFix extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        // 1) RAM block (uninitialized) at 0x00400000
        if (mem.getBlock("RAM")==null) {
            MemoryBlock b = mem.createUninitializedBlock("RAM", sp.getAddress(0x00400000L), 0x80000L, false);
            b.setRead(true); b.setWrite(true); b.setExecute(false); b.setVolatile(true);
            println("added RAM block 0x00400000 +0x80000");
        }
        // 2) clear functions & code in data region [0xa2000, 0x110000)
        Address lo = sp.getAddress(0xa2000L), hi = sp.getAddress(0x110000L);
        FunctionManager fm = currentProgram.getFunctionManager();
        int removed=0;
        FunctionIterator fit = fm.getFunctions(lo, true);
        java.util.List<Address> toRemove = new java.util.ArrayList<>();
        while (fit.hasNext()) {
            Function f = fit.next();
            if (f.getEntryPoint().compareTo(hi) >= 0) break;
            toRemove.add(f.getEntryPoint());
        }
        for (Address a : toRemove) { fm.removeFunction(a); removed++; }
        AddressSet set = new AddressSet(lo, hi.subtract(1));
        currentProgram.getListing().clearCodeUnits(lo, hi.subtract(1), false);
        println("removed "+removed+" bogus functions, cleared code units in 0xa2000-0x110000");
    }
}
