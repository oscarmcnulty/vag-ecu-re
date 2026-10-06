// Bring the SECOND code region (above CODE_HI=0xa2000) into the project. This region
// (~file 0xbb045..0x134011, mixed ARM+Thumb, interleaved with config tables) was excluded
// as DATA. The ARM sub-blocks load at VMA = file_offset + 3 (proven: seg1/config references
// to it, e.g. 0x67ed0->0xbc5f8, 0xa7b24->0x10002c, all resolve with delta +3). We split the
// DATA block at SEG2_FILE_START and move the upper part +3 so ARM decodes 4-aligned; then
// disassemble every ARM prologue (e92dXXXX with LR) as a function AND every Thumb prologue
// (B5xx = push {..,lr}) as a Thumb function, AND every interwork veneer (4778 46c0 + ARM B).
// An optional SEG2_CODE_END (file offset) splits the block further: the upper part becomes
// non-executable SEG2_DATA so the auto-analyzer doesn't create phantom functions in config tables.
// Cross-refs seg1<->seg2 and absolute RAM refs resolve (relative branches survive the uniform
// shift; RAM addrs are absolute). Idempotent: re-running skips the move if SEG2 already exists.
// Usage: -postScript EspSeg2.java [SEG2_FILE_START_hex [SEG2_CODE_END_hex]]
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.Register;
import java.math.BigInteger;

public class EspSeg2 extends GhidraScript {
    public void run() throws Exception {
        long segStart = 0xbb045L;
        if (getScriptArgs().length >= 1) segStart = Long.decode(getScriptArgs()[0]);
        long delta = 3;
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing lst = currentProgram.getListing();
        Register tmode = currentProgram.getLanguage().getRegister("TMode");

        // --- idempotent split+move: skip if a SEG2 block already exists (re-run on live project) ---
        MemoryBlock seg2 = null;
        for (MemoryBlock b : mem.getBlocks()) if ("SEG2".equals(b.getName())) { seg2 = b; break; }
        if (seg2 == null) {
            Address segAddr = sp.getAddress(segStart);
            MemoryBlock blk = mem.getBlock(segAddr);
            if (blk == null) { println("no block at "+segAddr); return; }
            if (blk.getStart().getOffset() != segStart) { mem.split(blk, segAddr); blk = mem.getBlock(segAddr); }
            long len = blk.getEnd().getOffset() - blk.getStart().getOffset() + 1;
            mem.moveBlock(blk, sp.getAddress(segStart + delta), monitor);
            seg2 = mem.getBlock(sp.getAddress(segStart + delta));
            seg2.setName("SEG2"); seg2.setExecute(true);
            println(String.format("SEG2 moved: file %#x..%#x -> VMA %#x..%#x (delta +%d), len %#x",
                    segStart, segStart+len, seg2.getStart().getOffset(), seg2.getEnd().getOffset(), delta, len));
        } else {
            seg2.setExecute(true);
            println("SEG2 already present at "+seg2.getStart()+" (skipping split/move)");
        }

        long lo = seg2.getStart().getOffset(), hi = seg2.getEnd().getOffset()-4;

        // --- optional code/data split: mark the config-table tail as non-executable ---
        if (getScriptArgs().length >= 2) {
            long codeEndFile = Long.decode(getScriptArgs()[1]);
            long codeEndVma = codeEndFile + delta;
            if (codeEndVma > lo && codeEndVma <= hi) {
                MemoryBlock seg2data = null;
                for (MemoryBlock b : mem.getBlocks()) if ("SEG2_DATA".equals(b.getName())) { seg2data = b; break; }
                if (seg2data == null) {
                    Address splitAddr = sp.getAddress(codeEndVma);
                    mem.split(seg2, splitAddr);
                    seg2data = mem.getBlock(splitAddr);
                    seg2data.setName("SEG2_DATA");
                    seg2data.setExecute(false);
                    seg2 = mem.getBlock(sp.getAddress(lo));
                    println(String.format("SEG2 code/data split at VMA %#x: code %#x..%#x, data %#x..%#x",
                            codeEndVma, lo, codeEndVma-1, codeEndVma, seg2data.getEnd().getOffset()));
                } else {
                    println("SEG2_DATA already present (skipping code/data split)");
                }
                hi = codeEndVma - 5;
            }
        }

        // --- ARM prologues: e92dXXXX with bit14 (LR) set, at 4-aligned VMA ---
        int armScan=0, armMade=0, armFail=0;
        for (long a = (lo+3)&~3L; a <= hi; a += 4) {
            int w = mem.getInt(sp.getAddress(a));
            if ((w & 0xffff0000) == 0xe92d0000 && (w & 0x4000) != 0) {
                armScan++;
                Address ep = sp.getAddress(a);
                if (getFunctionAt(ep) != null) continue;
                disassemble(ep);
                new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
                if (getFunctionAt(ep) != null) armMade++; else armFail++;
            }
        }

        // --- Thumb prologues: B5xx (push {reglist, lr}) at even VMA, in UNCLAIMED bytes ---
        int thScan=0, thMade=0, thFail=0;
        for (long a = (lo+1)&~1L; a <= hi; a += 2) {
            if ((mem.getByte(sp.getAddress(a)) & 0xff) != 0xB5) continue;
            thScan++;
            Address ep = sp.getAddress(a);
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

        // --- Interwork veneers: Thumb BX PC (4778) + NOP (46c0) + ARM B/BL (ea/eb) ---
        // Thumb->ARM trampolines generated by the linker for cross-ISA calls (ARMv4T has no BLX).
        int vScan=0, vMade=0, vFail=0;
        for (long a = (lo+1)&~1L; a <= hi-8; a += 2) {
            if ((mem.getShort(sp.getAddress(a)) & 0xffff) != 0x4778) continue;
            if ((mem.getShort(sp.getAddress(a+2)) & 0xffff) != 0x46c0) continue;
            long armAddr = a + 4;
            if ((armAddr & 3) != 0) continue;
            if (armAddr > hi - 4) continue;
            int w = mem.getInt(sp.getAddress(armAddr));
            int op = (w >>> 24) & 0xff;
            if (op != 0xea && op != 0xeb) continue;
            vScan++;
            Address ep = sp.getAddress(a);
            if (getFunctionAt(ep) != null || getFunctionContaining(ep) != null) continue;
            CodeUnit cu = lst.getCodeUnitContaining(ep);
            if (cu instanceof Instruction) continue;
            if (cu instanceof Data && ((Data)cu).isDefined()) continue;
            if (tmode != null) {
                try { currentProgram.getProgramContext().setValue(tmode, ep, ep, BigInteger.ONE); } catch(Exception e){}
            }
            boolean ok = new ArmDisassembleCommand(ep, null, true).applyTo(currentProgram, monitor);
            if (ok && (getFunctionAt(ep) != null || new CreateFunctionCmd(ep).applyTo(currentProgram, monitor)))
                vMade++; else vFail++;
        }

        println("EspSeg2: ARM prologues="+armScan+" made="+armMade+" failed="+armFail
                +" | Thumb prologues="+thScan+" made="+thMade+" failed="+thFail
                +" | veneers="+vScan+" made="+vMade+" failed="+vFail);
    }
}
