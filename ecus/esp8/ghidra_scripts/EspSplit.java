// Split the flat block: 0x0-0xa2000 executable code, 0xa2000+ non-executable data.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
public class EspSplit extends GhidraScript {
    public void run() throws Exception {
        Memory mem=currentProgram.getMemory();
        AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        MemoryBlock ram=mem.getBlock(sp.getAddress(0x1000));  // the flat 'ram' block
        Address split=sp.getAddress(0xa2000L);
        if (ram!=null && ram.contains(split) && ram.getStart().getOffset()==0) {
            mem.split(ram, split);
            MemoryBlock code=mem.getBlock(sp.getAddress(0x1000));
            MemoryBlock data=mem.getBlock(split);
            code.setName("CODE"); code.setExecute(true);
            data.setName("DATA"); data.setExecute(false);
            println("split done: CODE 0x0-0xa2000 (x), DATA 0xa2000+ (no-x)");
        } else println("already split or unexpected layout; blocks:");
        for (MemoryBlock b: mem.getBlocks())
            println(String.format("  %-6s %s-%s x=%b", b.getName(), b.getStart(), b.getEnd(), b.isExecute()));
    }
}
