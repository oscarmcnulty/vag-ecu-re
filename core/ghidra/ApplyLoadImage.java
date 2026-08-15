// Ghidra headless postScript: materialise the RAM/scratchpad state that the *missing* boot code
// would have produced, by applying the firmware's own linker copy tables to the program image.
//
// WHY. This image is an OBD read with a blank boot sector (0x80000000-0x80004000 = 0), so the
// crt0/loader that copies .data and relocates the scratchpad code is NOT in the dump. Three
// consequences fall out of that, and all three are invisible to static analysis:
//   * every `calla 0xc00003a0..0xc0001670` (the PSPR-resident math/helper library, ~1900 call
//     sites) points at an address with no bytes behind it -> AuditIndirectBranches "OFF-IMAGE";
//   * every function-pointer table that lives in .data reads as 0 -> "UNRESOLVED" calli;
//   * the PCP2 coprocessor's code memory is never populated at all, so its firmware is unseen.
// Emulating the boot cannot fix this either: the code that would do the copying is absent from
// the dump. But the *tables* it consumes are present, and they are self-validating -- the source
// ranges chain end-to-start with no gaps, and an independent region table restates the same
// bounds. So we apply them directly instead of trying to execute a loader we do not have.
//
// Two tables exist on this image (both verified by the contiguity invariant):
//   A @0x8000e868  records {src,dst,len}, terminator 0xffffffff, then a {addr,len} zero list.
//                  srcs chain 0x800045c0 -> 0x8000e868 (i.e. up to the table itself).
//   B @0x800402c8  records {dst,srcOrFill,len}. srcs chain 0x80020098 -> 0x80027298.
//                  This is the one that carries the PSPR code and the PCP2 PRAM/CMEM images.
// Where they overlap (both write 0xc0001400/0xc0001500) the later loader wins; every PSPR entry
// point actually called from flash is below 0xc0001400, so the overlap does not affect them.
//
// CAUTION. Initialising .data makes the decompiler constant-fold RAM reads. That is exactly what
// we want for const function-pointer tables and exactly WRONG for mutable variables: a global the
// firmware writes at runtime will decompile as its power-on value. Do NOT run this against the
// pipeline's shared project -- use a throwaway copy, and treat folded RAM scalars as suspect.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ApplyLoadImage.java [--no-pspr-code]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.SourceType;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;

public class ApplyLoadImage extends GhidraScript {

    // --- the two copy tables, as read out of this image (see header for how they were validated) ---
    // {src, dst, len}
    private static final long[][] TABLE_A = {
        {0x800045c0L, 0xc0001400L, 0x00000080L},
        {0x80004640L, 0xc0001500L, 0x00000248L},
        {0x80004888L, 0xd0000ac8L, 0x00009408L},
        {0x8000dc90L, 0xd0009ed0L, 0x00000270L},
        {0x8000df00L, 0xd000a140L, 0x00000968L},
    };
    private static final long[][] TABLE_B = {
        {0x80024f90L, 0xd000bfd8L, 0x00000db0L},
        {0x80025d40L, 0xd000cd88L, 0x00001558L},
        {0x80020098L, 0xc00003a0L, 0x000012d0L},   // PSPR code
        {0x800222e8L, 0xf0060000L, 0x00002ca8L},   // PCP2 code memory (CMEM)
        {0x80021368L, 0xf0050000L, 0x00000f80L},   // PCP2 parameter RAM (PRAM)
    };
    // {addr, len} regions the loader clears (table A's zero list @0x8000e8b0 + table B's fills)
    private static final long[][] ZERO = {
        {0xd000aaa8L, 0x00001ac8L},
        {0xd000c570L, 0x00002fb8L},
        {0xf0050f80L, 0x00001080L},
    };

    private Memory mem;

    @Override
    public void run() throws Exception {
        boolean psprCode = true;
        for (String a : getScriptArgs()) if (a.equals("--no-pspr-code")) psprCode = false;
        mem = currentProgram.getMemory();

        // 1. PSPR is not in the .pspec memory map at all -> create it (32 KB, per the MPU region
        //    table @0x8003fa60 which ends the executable PSPR region at 0xc0007fff).
        if (mem.getBlock(toAddr(0xc0000000L)) == null) {
            MemoryBlock b = mem.createInitializedBlock("PSPR", toAddr(0xc0000000L), 0x8000,
                    (byte) 0, monitor, false);
            b.setRead(true); b.setWrite(true); b.setExecute(true);
            println("created PSPR block 0xc0000000 +0x8000");
        }

        // 2. verify each record against the image before writing anything
        int applied = 0, bytes = 0;
        for (long[][] tbl : new long[][][]{TABLE_A, TABLE_B}) {
            for (long[] r : tbl) {
                long src = r[0], dst = r[1], len = r[2];
                byte[] data = new byte[(int) len];
                try {
                    mem.getBytes(toAddr(src), data);
                } catch (Exception e) {
                    println(String.format("SKIP src 0x%08x +0x%x unreadable: %s", src, len, e));
                    continue;
                }
                if (writeRange(dst, data)) { applied++; bytes += (int) len; }
            }
        }
        for (long[] z : ZERO) writeRange(z[0], new byte[(int) z[1]]);
        println(String.format("applied %d copy records, 0x%x bytes", applied, bytes));

        if (!psprCode) { println("LOADIMAGEDONE"); return; }

        // 3. Every calla/call whose target now lands in PSPR was previously OFF-IMAGE. Disassemble
        //    each such target and make it a function, so the call graph reaches the helper library.
        Set<Long> psprTargets = new TreeSet<>();
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction in = it.next();
            if (!in.getFlowType().isCall() && !in.getFlowType().isJump()) continue;
            for (Address t : in.getFlows()) {
                long v = t.getOffset();
                if (v >= 0xc0000000L && v < 0xc0008000L) psprTargets.add(v);
            }
        }
        println("PSPR branch targets referenced from flash: " + psprTargets.size());
        int made = 0, dis = 0;
        for (long t : psprTargets) {
            Address a = toAddr(t);
            if (getInstructionAt(a) == null) { if (disassemble(a)) dis++; }
            if (getFunctionContaining(a) == null && getInstructionAt(a) != null) {
                Function f = createFunction(a, null);
                if (f != null) made++;
            }
        }
        // sweep: disassemble anything still undefined inside the copied code image
        AddressSet body = new AddressSet(toAddr(0xc00003a0L), toAddr(0xc000166fL));
        disassemble(toAddr(0xc00003a0L));
        println(String.format("PSPR: disassembled %d entry points, created %d functions", dis, made));

        // 4. The .data image is not pure data: it carries RAM-RESIDENT CODE. Proof on this image is
        //    that flash 0x8000d6ba maps, under table A, exactly onto 0xd00098fa -- the one RAM
        //    function the pipeline had already found (as a 1-byte "degraded" stub, because the
        //    bytes were missing). Disassemble every branch target that now lands in the copied
        //    .data so those functions become real.
        Set<Long> ramTargets = new TreeSet<>();
        it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction in = it.next();
            if (!in.getFlowType().isCall() && !in.getFlowType().isJump()) continue;
            for (Address t : in.getFlows()) {
                long v = t.getOffset();
                if (v >= 0xd0000ac8L && v < 0xd000aaa8L) ramTargets.add(v);
            }
        }
        int rmade = 0;
        for (long t : ramTargets) {
            Address a = toAddr(t);
            if (getInstructionAt(a) == null) {
                // the pipeline may already have stamped a 0-byte placeholder function here (it saw
                // the reference but had no bytes); clear it so the real code can be laid down.
                Function ex = getFunctionAt(a);
                if (ex != null) removeFunction(ex);
                try { clearListing(a, a.add(1)); } catch (Exception e) { /* nothing to clear */ }
                disassemble(a);
            }
            if (getFunctionContaining(a) == null && getInstructionAt(a) != null && createFunction(a, null) != null) rmade++;
        }
        println("RAM-resident code: " + ramTargets.size() + " branch targets in the copied .data, "
                + rmade + " functions created");
        for (long t : ramTargets) {
            Instruction in = getInstructionAt(toAddr(t));
            Function fn = getFunctionContaining(toAddr(t));
            println(String.format("  RAM 0x%08x  %-20s %s", t, fn == null ? "(none)" : fn.getName(),
                    in == null ? "(no instruction)" : in.toString()));
        }

        // 5. Sweep the copied .data for RUNS of consecutive pointers into the RAM code region.
        //    A run of N such words is a function-pointer table; on this image the largest is at
        //    0xd0009ed0 (its own copy record, src 0x8000dc90 len 0x270) and it is nothing but
        //    pointers. These are the "RAM vtables" the indirect-branch audit could never see,
        //    and every target is an entry point of code that only exists in the .data image.
        long RC_LO = 0xd0000ac8L, RC_HI = 0xd000aaa8L;
        Set<Long> vt = new TreeSet<>();
        int tables = 0;
        for (long a = RC_LO; a < RC_HI - 4; ) {
            long run = 0, p = a;
            while (p < RC_HI - 4 && isRamCodePtr(p, RC_LO, RC_HI)) { run++; p += 4; }
            if (run >= 4) {
                tables++;
                println(String.format("  vtable 0x%08x x%d", a, run));
                for (long q = a; q < p; q += 4) vt.add(mem.getInt(toAddr(q)) & 0xffffffffL);
            }
            a = run > 0 ? p : a + 4;
        }
        int vmade = 0, vgood = 0;
        for (long t : vt) {
            Address a = toAddr(t);
            if (getInstructionAt(a) == null) {
                Function ex = getFunctionAt(a);
                if (ex != null) removeFunction(ex);
                try { clearListing(a, a.add(1)); } catch (Exception e) { }
                disassemble(a);
            }
            // Ghidra's flow-following disassembler stops after the first instruction in this block,
            // so walk the body linearly until a return/indirect jump or a decode failure.
            Address cur = a;
            int steps = 0;
            while (steps++ < 512) {
                Instruction cin = getInstructionAt(cur);
                if (cin == null) { disassemble(cur); cin = getInstructionAt(cur); }
                if (cin == null) break;
                String m = cin.getMnemonicString().toLowerCase();
                if (m.equals("ret") || m.equals("rfe") || m.equals("ji") || m.startsWith("j ")) break;
                cur = cur.add(cin.getLength());
                if (cur.getOffset() >= RC_HI) break;
            }
            if (getInstructionAt(a) != null) {
                vgood++;
                if (getFunctionContaining(a) == null && createFunction(a, null) != null) vmade++;
            }
        }
        println(String.format("RAM vtables: %d tables, %d distinct targets, %d disassembled, %d functions created",
                tables, vt.size(), vgood, vmade));

        // report which PSPR entries are now real functions
        List<String> rows = new ArrayList<>();
        for (long t : psprTargets) {
            Function f = getFunctionContaining(toAddr(t));
            Instruction in = getInstructionAt(toAddr(t));
            rows.add(String.format("  0x%08x  %-22s %s", t,
                    f == null ? "(no function)" : f.getName(),
                    in == null ? "(no instruction)" : in.toString()));
        }
        for (String s : rows) println(s);
        println("LOADIMAGEDONE");
    }

    private boolean isRamCodePtr(long at, long lo, long hi) {
        try {
            MemoryBlock b = mem.getBlock(toAddr(at));
            if (b == null || !b.isInitialized()) return false;
            long v = mem.getInt(toAddr(at)) & 0xffffffffL;
            return (v & 1) == 0 && v >= lo && v < hi;
        } catch (Exception e) { return false; }
    }

    /** write data at dst, splitting/converting the covering block to initialized if needed. */
    private boolean writeRange(long dst, byte[] data) {
        try {
            Address a = toAddr(dst);
            MemoryBlock b = mem.getBlock(a);
            if (b == null) { println(String.format("SKIP dst 0x%08x: unmapped", dst)); return false; }
            if (!b.isInitialized()) {
                Address end = a.add(data.length - 1);
                // isolate exactly the range we need -- some uninit blocks here are enormous
                // (the CSFR block is 256 MB) and converting them wholesale is not viable.
                if (b.getStart().compareTo(a) < 0) { mem.split(b, a); b = mem.getBlock(a); }
                if (b.getEnd().compareTo(end) > 0) { mem.split(b, end.add(1)); b = mem.getBlock(a); }
                b = mem.convertToInitialized(b, (byte) 0);
                b.setRead(true); b.setWrite(true);
                b.setExecute(true);   // DSPR too: the .data image carries RAM-resident code
            }
            mem.setBytes(a, data);
            println(String.format("wrote 0x%08x +0x%x (block %s)", dst, data.length, b.getName()));
            return true;
        } catch (Exception e) {
            println(String.format("FAILED dst 0x%08x +0x%x: %s", dst, data.length, e));
            return false;
        }
    }
}
