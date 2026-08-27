// Read the 32-bit word (pointer literal) stored at each given address; print target.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
public class EspReadPtrs extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    for(String s: a){ long at=Long.parseLong(s,16);
      try{ int v=mem.getInt(sp.getAddress(at)); // BE32
        println(String.format("  [0x%08x] -> 0x%08x", at, v & 0xffffffffL));
      }catch(Exception e){ println("  [0x"+s+"] ERR "+e.getMessage()); }
    }
  }
}
