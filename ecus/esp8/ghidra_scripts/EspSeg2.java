// Bring the SECOND code region (above CODE_HI=0xa2000) into the project. This region
// (~file 0xbb045..0x134011, mixed ARM+Thumb, interleaved with config tables) was excluded
// as DATA. The ARM sub-blocks load at VMA = file_offset + 3 (proven: seg1/config references
// to it, e.g. 0x67ed0->0xbc5f8, 0xa7b24->0x10002c, all resolve with delta +3). We split the
// DATA block at SEG2_FILE_START and move the upper part +3 so ARM decodes 4-aligned; then
// disassemble every ARM prologue (e92dXXXX with LR) as a function. Cross-refs seg1<->seg2 and
// absolute RAM refs then resolve (relative branches survive the uniform shift; RAM addrs are
// absolute). Usage: -postScript EspSeg2.java [SEG2_FILE_START_hex]
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;

public class EspSeg2 extends GhidraScript {
    public void run() throws Exception {
        long segStart = 0xbb045L;
        if (getScriptArgs().length >= 1) segStart = Long.decode(getScriptArgs()[0]);
        long delta = 3;
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address segAddr = sp.getAddress(segStart);
        MemoryBlock blk = mem.getBlock(segAddr);
        if (blk == null) { println("no block at "+segAddr); return; }
        // split off [segStart, end) and move it +delta
        if (blk.getStart().getOffset() != segStart) {
            mem.split(blk, segAddr);
            blk = mem.getBlock(segAddr);
        }
        long len = blk.getEnd().getOffset() - blk.getStart().getOffset() + 1;
        mem.moveBlock(blk, sp.getAddress(segStart + delta), monitor);
        blk = mem.getBlock(sp.getAddress(segStart + delta));
        blk.setName("SEG2"); blk.setExecute(true);
        println(String.format("SEG2 moved: file %#x..%#x -> VMA %#x..%#x (delta +%d), len %#x",
                segStart, segStart+len, blk.getStart().getOffset(), blk.getEnd().getOffset(), delta, len));
        // scan for ARM prologues: e92dXXXX with bit14 (LR) set, at 4-aligned VMA
        long lo = blk.getStart().getOffset(), hi = blk.getEnd().getOffset()-4;
        int created=0, failed=0, scanned=0;
        for (long a = (lo+3)&~3L; a <= hi; a += 4) {
            int w = mem.getInt(sp.getAddress(a));
            if ((w & 0xffff0000) == (0xe92d0000) && (w & 0x4000) != 0) {
                scanned++;
                Address ep = sp.getAddress(a);
                if (getFunctionAt(ep) != null) continue;
                disassemble(ep);
                new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
                if (getFunctionAt(ep) != null) created++; else failed++;
            }
        }
        println("EspSeg2: ARM prologues="+scanned+" functions-created="+created+" failed="+failed);
    }
}
