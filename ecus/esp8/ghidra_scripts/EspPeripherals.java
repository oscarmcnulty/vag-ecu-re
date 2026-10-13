// EspPeripherals.java — datasheet-driven MMIO decompile aids for ESP8.
//
// Platform = TI TMS470R1x / SM470R1B1M (big-endian ARM7TDMI). Peripheral frame base
// addresses are from the SM470R1B1M-HT datasheet (SPNS155I, Table 8-7); the HECC register
// layout is the standard TI HECC map (SPNU197e) and matches the offsets the CAN ISR polls.
// This script:
//   1) creates a volatile, uninitialized PERIPH block (0xFFF00000 +0x100000) so the MMIO base
//      labels applied by ApplySymbols (periph_*, hecc_*, esc_valve_mmio) resolve to real memory
//      — Ghidra then forms data xrefs and the decompiler can substitute the names.
//   2) defines a HECC control-register struct + a 32-entry HECC mailbox-RAM struct, and types
//      the literal-pool words that hold the HECC control / mailbox-RAM bases with them, so the
//      CAN ISRs decompile as hecc1->CANTA / mbox[n].MID instead of *(DAT_xxxx + off).
//   3) types every other literal-pool word whose value is a known peripheral frame base as a
//      plain pointer named p_<module>.
//   4) labels the ARM exception/interrupt vectors at 0x0..0x1c.
//
// Every mutation is individually try/caught; the script always completes so it cannot abort
// reproduce.sh. Run AFTER ApplySymbols (so the base labels already exist) and BEFORE the
// decompile step. Idempotent: re-running only fills gaps.
//   analyzeHeadless <proj> <name> -process <prog> -noanalysis -scriptPath <esp> \
//       -postScript EspPeripherals.java [codeLo codeHi seg2Lo seg2Hi]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.SourceType;

public class EspPeripherals extends GhidraScript {

    // frame base -> index into TAG (SM470R1B1M-HT datasheet SPNS155I, Table 8-7)
    private static final long[][] BASES = {
        {0xfff7d400L, 0}, {0xfff7d500L, 1}, {0xfff7d600L, 2},
        {0xfff7e400L, 3}, {0xfff7e600L, 4}, {0xfff7e800L, 5}, {0xfff7ea00L, 6},
        {0xfff7ec00L, 7}, {0xfff7f000L, 8}, {0xfff7f0a0L, 9}, {0xfff7f400L, 10},
        {0xfff7f800L, 11}, {0xfff7fc00L, 12}, {0xfffff700L, 13},
    };
    private static final String[] TAG = {
        "valve_spi2_d400", "valve_i2c5_d500", "valve_rsvd_d600",
        "hecc1_ram", "hecc2_ram", "hecc1_ctrl", "hecc2_ctrl",
        "gio", "mibadc", "pump_motor", "sci1",
        "spi1", "het", "msm",
    };

    private String tagFor(long v) {
        for (long[] b : BASES) if (b[0] == v) return TAG[(int) b[1]];
        return null;
    }

    // Standard TI HECC control-frame registers (offset, name)
    private static final Object[][] HECC_REGS = {
        {0x00, "CANME"}, {0x04, "CANMD"}, {0x08, "CANTRS"}, {0x0C, "CANTRR"},
        {0x10, "CANTA"}, {0x14, "CANAA"}, {0x18, "CANRMP"}, {0x1C, "CANRML"},
        {0x20, "CANRFP"}, {0x24, "CANGAM"}, {0x28, "CANMC"}, {0x2C, "CANBTC"},
        {0x30, "CANES"}, {0x34, "CANTEC"}, {0x38, "CANREC"}, {0x3C, "CANGIF0"},
        {0x40, "CANGIM"}, {0x44, "CANGIF1"}, {0x48, "CANMIM"}, {0x4C, "CANMIL"},
        {0x50, "CANOPC"}, {0x54, "CANTIOC"}, {0x58, "CANRIOC"},
    };

    @Override
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        DataTypeManager dtm = currentProgram.getDataTypeManager();

        // 1) volatile PERIPH block so MMIO labels/xrefs resolve
        try {
            if (mem.getBlock("PERIPH") == null) {
                MemoryBlock b = mem.createUninitializedBlock(
                        "PERIPH", sp.getAddress(0xFFF00000L), 0x100000L, false);
                b.setRead(true); b.setWrite(true); b.setExecute(false); b.setVolatile(true);
                println("added PERIPH block 0xFFF00000 +0x100000 (volatile MMIO)");
            }
        } catch (Exception e) { println("PERIPH block: " + e.getMessage()); }

        // datatypes for pointer typing: HECC control, HECC mailbox-RAM, generic
        DataType ptrGeneric = new PointerDataType();
        DataType heccPtr = ptrGeneric, mboxPtr = ptrGeneric;
        try {
            StructureDataType hecc = new StructureDataType("HECC", 0x100);
            for (Object[] r : HECC_REGS)
                hecc.replaceAtOffset((Integer) r[0], DWordDataType.dataType, 4, (String) r[1], null);
            DataType heccT = dtm.addDataType(hecc, DataTypeConflictHandler.REPLACE_HANDLER);
            heccPtr = new PointerDataType(heccT);

            StructureDataType mb = new StructureDataType("HECC_MBOX", 0x10);
            mb.replaceAtOffset(0x0, DWordDataType.dataType, 4, "MID", null);  // msg identifier
            mb.replaceAtOffset(0x4, DWordDataType.dataType, 4, "MCF", null);  // msg control field
            mb.replaceAtOffset(0x8, DWordDataType.dataType, 4, "MDL", null);  // data low
            mb.replaceAtOffset(0xC, DWordDataType.dataType, 4, "MDH", null);  // data high
            DataType mbT = dtm.addDataType(mb, DataTypeConflictHandler.REPLACE_HANDLER);
            DataType mbArr = dtm.addDataType(
                    new ArrayDataType(mbT, 32, mbT.getLength()), DataTypeConflictHandler.REPLACE_HANDLER);
            mboxPtr = new PointerDataType(mbArr);
            println("EspPeripherals: defined HECC + HECC_MBOX[32] datatypes");
        } catch (Exception e) {
            println("HECC struct (falling back to generic pointers): " + e.getMessage());
        }

        // 2+3) type literal-pool peripheral-base constants as pointers
        String[] a = getScriptArgs();
        long[][] regions = {
            { a.length > 0 ? Long.decode(a[0]) : 0x0L,     a.length > 1 ? Long.decode(a[1]) : 0xa2000L  },
            { a.length > 2 ? Long.decode(a[2]) : 0xbb045L, a.length > 3 ? Long.decode(a[3]) : 0x10a000L },
        };
        Listing lst = currentProgram.getListing();
        int typed = 0, heccTyped = 0;
        for (long[] r : regions) {
            long lo = (r[0] + 3) & ~3L, hi = r[1];
            for (long off = lo; off + 4 <= hi; off += 4) {
                Address p = sp.getAddress(off);
                long v;
                try { v = mem.getInt(p) & 0xffffffffL; }
                catch (Exception e) { continue; }
                String tag = tagFor(v);
                if (tag == null) continue;
                if (getInstructionContaining(p) != null) continue; // never touch code
                DataType dt = ptrGeneric;
                if (v == 0xfff7e800L || v == 0xfff7ea00L) { dt = heccPtr; }
                else if (v == 0xfff7e400L || v == 0xfff7e600L) { dt = mboxPtr; }
                try {
                    lst.clearCodeUnits(p, p.add(3), false);
                    createData(p, dt);
                    createLabel(p, "p_" + tag, true, SourceType.USER_DEFINED);
                    setEOLComment(p, "-> " + String.format("0x%08x", v) + " (" + tag + ")");
                    typed++;
                    if (dt == heccPtr || dt == mboxPtr) heccTyped++;
                } catch (Exception e) { /* leave this word as-is */ }
            }
        }
        println("EspPeripherals: typed " + typed + " literal-pool MMIO pointers (" + heccTyped + " HECC-typed)");

        // 4) ARM exception/interrupt vectors (datasheet memory map 0x0..0x23)
        String[][] vec = {
            {"0x0",  "vec_reset"}, {"0x4",  "vec_undef"}, {"0x8",  "vec_swi"},
            {"0xc",  "vec_prefetch_abort"}, {"0x10", "vec_data_abort"},
            {"0x18", "vec_irq"}, {"0x1c", "vec_fiq"},
        };
        int vl = 0;
        for (String[] vv : vec) {
            try {
                createLabel(sp.getAddress(Long.decode(vv[0])), vv[1], true, SourceType.USER_DEFINED);
                vl++;
            } catch (Exception e) { /* skip */ }
        }
        println("EspPeripherals: labeled " + vl + " ARM vectors");
    }
}
