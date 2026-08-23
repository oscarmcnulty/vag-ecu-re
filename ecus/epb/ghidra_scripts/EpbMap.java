// EPB (HCS12X) reproducible memory map + PPAGE context. The FRF gives two app flash blocks that
// are BANKED 16KB pages. Ghidra's HCS12X decompiler forms global addresses (0x400000 + PPAGE*0x4000
// + off) for windowed (0x8000-0xBFFF) accesses, so pages MUST be loaded at those globals and the
// PPAGE context set per page or every cross-page flow escapes to unmapped memory (empty bodies).
// Confirmed page map: DB_4 = PPAGE 0xE0-0xE6 (global 0x780000), DB_6 = PPAGE 0xF8-0xFD (0x7e0000);
// fixed-low page 0xFD (global 0x7f4000) is also visible at local 0x4000-0x7FFF (byte-mapped alias).
// DB_4 is the -import block (baseAddr 0x780000); DB_6 is loaded here from its file.
//   -preScript EpbMap.java <DB_6_path>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.ProgramContext;
import ghidra.program.model.mem.*;
import java.math.BigInteger;
import java.nio.file.*;

public class EpbMap extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    Memory mem=currentProgram.getMemory();
    // DB_6 -> initialized block @ 0x7e0000
    byte[] db6=Files.readAllBytes(Paths.get(a[0]));
    MemoryBlock b6=mem.createInitializedBlock("DB6",toAddr(0x7e0000L),db6.length,(byte)0,monitor,false);
    mem.setBytes(toAddr(0x7e0000L),db6);
    b6.setRead(true); b6.setExecute(true);
    // registers + RAM (uninitialized)
    MemoryBlock io=mem.createUninitializedBlock("IO",toAddr(0x0),0x400,false);
    io.setRead(true); io.setWrite(true); io.setVolatile(true);
    MemoryBlock ram=mem.createUninitializedBlock("RAM",toAddr(0x400),0x3c00,false);
    ram.setRead(true); ram.setWrite(true); ram.setVolatile(true);
    // fixed-low page 0xFD visible at local 0x4000-0x7FFF (byte-mapped view of global 0x7f4000)
    MemoryBlock lo=mem.createByteMappedBlock("FIXED_LOW",toAddr(0x4000L),toAddr(0x7f4000L),0x4000,false);
    lo.setRead(true); lo.setExecute(true);
    // PPAGE context per 16KB page region so windowed refs resolve to the right page
    Register ppage=currentProgram.getRegister("PPAGE");
    ProgramContext ctx=currentProgram.getProgramContext();
    for(int p=0;p<7;p++){ long base=0x780000L+p*0x4000; ctx.setValue(ppage,toAddr(base),toAddr(base+0x3fff),BigInteger.valueOf(0xE0+p)); }
    for(int q=0;q<6;q++){ long base=0x7e0000L+q*0x4000; ctx.setValue(ppage,toAddr(base),toAddr(base+0x3fff),BigInteger.valueOf(0xF8+q)); }
    ctx.setValue(ppage,toAddr(0x4000L),toAddr(0x7fffL),BigInteger.valueOf(0xFD)); // fixed-low alias
    println("EpbMap: DB6@0x7e0000 ("+db6.length+"B), IO/RAM/FIXED_LOW mapped, PPAGE set 0xE0-0xE6,0xF8-0xFD; blocks="+mem.getBlocks().length);
  }
}
