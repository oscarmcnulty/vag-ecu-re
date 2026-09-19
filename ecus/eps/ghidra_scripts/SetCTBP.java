import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;
import ghidra.program.model.symbol.SourceType;
import java.math.BigInteger;

// SetCTBP.java -- resolve the V850 CALLT base pointer (CTBP) program-wide so that
// `callt <imm6>` instructions fold to their real targets, and re-carve the interrupt
// context-save trampoline FUN_000252f4 which a stale pass had truncated.
//
// CTBP is set once at C-init:  0x0000702a  `ldsr r10,CTBP`  with r10 computed
// PC-relative (jarl @0x6fd6 -> movhi 0x4 -> movea -0x7d64) == 0x0003F272.
// Because it is PC-derived it lands in code space (1:1 with file offset at LOADBASE=0),
// NOT the +0x12000 const-data window. Verified: the halfword table there decodes to
// valid compiler prologue/epilogue callt thunks (prepare{lp}/ctret/dispose...).
//
// V850 CALLT semantics:  target = CTBP + zero_extend( halfword[ CTBP + imm6*2 ] ).
//
// Run (after import, no analysis needed; re-run after any fresh import):
//   analyzeHeadless <proj> EPS_8R0909144F -process 8R0909144F_0507.bin -noanalysis \
//       -scriptPath ghidra_scripts -postScript SetCTBP.java
//   (then re-run DecompileAll.java to regenerate the corpus)
public class SetCTBP extends GhidraScript {
  static final long CTBP = 0x0003F272L;   // CALLT base pointer
  static final int  TABLE_ENTRIES = 0x2c; // 44 real uint16 slots; thunks begin right after
                                          // (entry[0]=CTBP+0x58=0x3f2ca). Slots >=0x2c point
                                          // back into the table => not live entries.

  public void run() throws Exception {
    ProgramContext ctx = currentProgram.getProgramContext();
    AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
    Address lo = sp.getAddress(0x0), hi = sp.getAddress(0x85fff);

    // 1. Set CTBP as a program-wide assumed register value (same mechanism as gp/tp).
    Register ctbp = ctx.getRegister("CTBP");
    if (ctbp == null) { println("ERROR: no CTBP register in this language"); return; }
    ctx.setValue(ctbp, lo, hi, BigInteger.valueOf(CTBP));
    println("CTBP = 0x" + Long.toHexString(CTBP) + " set over 0x0..0x85fff");

    // 2. Type the CALLT offset table as a uint16 array so it is not swept as code and so
    //    the entries read as data. Each entry i resolves to CTBP + entry (a code thunk).
    Address tbl = toAddr(CTBP);
    try {
      clearListing(tbl, toAddr(CTBP + TABLE_ENTRIES * 2 - 1));
      DataType u16 = UnsignedShortDataType.dataType;
      ArrayDataType arr = new ArrayDataType(u16, TABLE_ENTRIES, u16.getLength());
      createData(tbl, arr);
      createLabel(tbl, "CALLT_table", true, SourceType.USER_DEFINED);
      println("CALLT_table: " + TABLE_ENTRIES + " uint16 entries @0x" + Long.toHexString(CTBP));
    } catch (Exception e) {
      println("WARN: could not type CALLT_table: " + e);
    }

    // 3. Re-carve the interrupt context-save trampoline @0x000252f4 (a stale pass had it
    //    truncated to 30 bytes). Force a clean disassembly + function so it decodes whole.
    Address tramp = toAddr(0x000252f4L);
    try {
      Function old = getFunctionContaining(tramp);
      if (old != null && old.getEntryPoint().equals(tramp)) removeFunction(old);
      clearListing(tramp, toAddr(0x00025360L));
      disassemble(tramp);
      if (getFunctionAt(tramp) == null)
        createFunction(tramp, "irq_ctx_save_252f4");
      println("re-carved trampoline @0x252f4 (irq_ctx_save_252f4)");
    } catch (Exception e) {
      println("WARN: trampoline re-carve: " + e);
    }

    println("SetCTBP done. Re-run DecompileAll.java to refold callt sites.");
  }
}
