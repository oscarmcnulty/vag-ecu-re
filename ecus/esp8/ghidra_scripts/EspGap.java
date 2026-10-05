// Recover code in the GAP region 0xa2000..0xbb045 (between CODE_HI and SEG2_START). EspSplit
// marked 0xa2000+ as non-exec DATA; EspSeg2 carved off 0xbb045+ (the AUTOSAR-COM stack, +3
// shift). FINDING (2026-10-01): the remaining DATA block 0xa2000..0xbb044 is NOT the diagnostic
// handler layer. It is ~90 ARM call-veneers (0xa2008..0xa2620, each `stmdb{lr};bl X;ldm{lr};bx
// lr` -> real fns in the main region), ~27 tiny Thumb funcs, and config DATA tables (SID
// permission table @0xae938, DCM/calibration descriptor array @0xa7a00+, DID tables @0xb44e4).
// None of the gap code references the SID/descriptor tables -> the KWP dispatcher is elsewhere
// and reaches the config via a RAM-stored base. This script still cleanly recovers the gap code
// for completeness, but it is not on the seed/key path. Unlike
// seg2 this region is already 4-aligned at VMA==file_offset (proven: veneers at 0xa2008 decode
// clean, SID table @file 0xae938 == VMA 0xae938), so NO move/delta is needed -- just mark the
// block executable and disassemble every ARM prologue (e92dXXXX w/ LR) and Thumb prologue
// (B5xx = push{..,lr}) in currently-unclaimed bytes. Guards skip defined data / existing code
// so the interleaved config tables are left intact. Idempotent.
// Usage: -postScript EspGap.java [LO_hex HI_hex]   (default 0xa2000 0xbb045)
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;

public class EspGap extends GhidraScript {
    public void run() throws Exception {
        long lo = 0xa2000L, hi = 0xbb045L;
        String[] a = getScriptArgs();
        if (a.length >= 2) { lo = Long.decode(a[0]); hi = Long.decode(a[1]); }
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing lst = currentProgram.getListing();

        // mark every block overlapping [lo,hi) executable (the DATA block 0xa2000..0xbb044)
        for (MemoryBlock b : mem.getBlocks()) {
            long bs = b.getStart().getOffset(), be = b.getEnd().getOffset();
            if (bs < hi && be >= lo && !b.isExecute()) {
                b.setExecute(true);
                println(String.format("marked exec: %s %#x..%#x", b.getName(), bs, be));
            }
        }
        long top = Math.min(hi, mem.getBlock(sp.getAddress(lo)).getEnd().getOffset()) - 4;

        // Undefine any data the analysis/COM-signal passes laid over this region so prologue
        // sweeps aren't skipped. Raw bytes are untouched; config tables are re-derivable and
        // will NOT be turned into functions (they don't start with e92d../B5xx prologues).
        boolean clear = !(a.length >= 3 && a[2].equalsIgnoreCase("noclear"));
        if (clear) {
            clearListing(sp.getAddress(lo), sp.getAddress(top+3));
            println(String.format("cleared listing %#x..%#x", lo, top+3));
        }

        // --- ARM prologues: e92dXXXX with bit14 (LR) set, 4-aligned, unclaimed ---
        int armScan=0, armMade=0, armFail=0;
        for (long p = (lo+3)&~3L; p <= top; p += 4) {
            Address ep = sp.getAddress(p);
            int w;
            try { w = mem.getInt(ep); } catch (Exception e) { continue; }
            if ((w & 0xffff0000) != 0xe92d0000 || (w & 0x4000) == 0) continue;
            armScan++;
            if (getFunctionAt(ep) != null) continue;
            CodeUnit cu = lst.getCodeUnitContaining(ep);
            if (cu instanceof Instruction) continue;
            if (cu instanceof Data && ((Data)cu).isDefined()) continue;
            disassemble(ep);
            new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
            if (getFunctionAt(ep) != null) armMade++; else armFail++;
        }

        // --- Thumb prologues: B5xx (push{reglist,lr}) at even VMA, unclaimed ---
        int thScan=0, thMade=0, thFail=0;
        for (long p = (lo+1)&~1L; p <= top; p += 2) {
            Address ep = sp.getAddress(p);
            int hb;
            try { hb = mem.getByte(ep) & 0xff; } catch (Exception e) { continue; }
            if (hb != 0xB5) continue;
            thScan++;
            if (getFunctionContaining(ep) != null) continue;
            CodeUnit cu = lst.getCodeUnitContaining(ep);
            if (cu instanceof Instruction) continue;
            if (cu instanceof Data && ((Data)cu).isDefined()) continue;
            boolean ok = new ArmDisassembleCommand(ep, null, true).applyTo(currentProgram, monitor);
            Instruction ins = lst.getInstructionAt(ep);
            if (ok && ins != null && ins.getMnemonicString().toLowerCase().startsWith("push")) {
                if (getFunctionAt(ep) != null || new CreateFunctionCmd(ep).applyTo(currentProgram, monitor))
                    thMade++; else thFail++;
            } else { thFail++; }
        }

        println("EspGap["+Long.toHexString(lo)+".."+Long.toHexString(hi)+"]: ARM prologues="+armScan
                +" made="+armMade+" failed="+armFail+" | Thumb prologues="+thScan
                +" made="+thMade+" failed="+thFail);
    }
}
