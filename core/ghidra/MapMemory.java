// Ghidra headless preScript: build the TriCore memory map that a raw BinaryLoader import
// lacks -- the non-cached flash alias plus RAM/peripheral space.
//
// Why this matters: TriCore maps the SAME physical flash twice, cached at 0x80000000 and
// non-cached at 0xA0000000, and ECU code freely mixes the two (a jump table built with
// movh.a 0xa006 lands in the alias). With only the 0x8... block loaded, every such flow
// dies as "Could not follow disassembly flow into non-existing memory at a00602d8" and the
// decompiler truncates the body. Likewise, loads of RAM globals report "Unable to read
// bytes at ram:d0004cb8" unless an (uninitialized) RAM block exists. Mapping the alias
// BYTE-MAPPED (not a copy) keeps a single source of truth for the bytes.
//
// Run as a -preScript on the import so the blocks exist before auto-analysis:
//   analyzeHeadless <proj> <name> -import <bin> -processor tricore:LE:32:tc176x \
//       -loader BinaryLoader -loader-baseAddr 0x80000000 \
//       -preScript MapMemory.java --alias=0xa0000000:0x80000000:0x400000 \
//                                 --uninit=0xd0000000:0x00100000:RAM:rw \
//                                 --uninit=0xf0000000:0x10000000:CSFR:rwv
// Args (repeatable, order-independent):
//   --alias=<start>:<src>:<len>            byte-mapped view of an existing block
//   --uninit=<start>:<len>[:name[:flags]]  uninitialized block; flags subset of r,w,x,v
//                                          (v = volatile, for memory-mapped peripherals)
// Existing/overlapping blocks are skipped with a message rather than clobbered.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

public class MapMemory extends GhidraScript {

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    private Address addr(long v) {
        return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v);
    }

    /**
     * Name of the first existing block intersecting [start,start+len), else null.
     * Creating an overlapping block throws, so callers skip -- but report WHAT it hit:
     * the TriCore .pspec already declares LDRAM/PRAM/CSFR, so a "skip" there is
     * expected and not a problem, whereas a skip on the flash alias would be a bug.
     */
    private String occupiedBy(Address start, long len) {
        Address end = start.add(len - 1);
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            if (b.getStart().compareTo(end) <= 0 && b.getEnd().compareTo(start) >= 0) {
                return b.getName() + " @" + b.getStart() + ".." + b.getEnd();
            }
        }
        return null;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length == 0) {
            println("MapMemory: nothing to do. usage: --alias=<start>:<src>:<len> "
                  + "--uninit=<start>:<len>[:name[:flags]]");
            return;
        }
        Memory mem = currentProgram.getMemory();

        for (String a : args) {
            try {
                if (a.startsWith("--alias=")) {
                    String[] p = a.substring(8).split(":");
                    if (p.length != 3) { println("bad --alias (want start:src:len): " + a); continue; }
                    Address start = addr(hex(p[0])), src = addr(hex(p[1]));
                    long len = hex(p[2]);
                    String hit = occupiedBy(start, len);
                    if (hit != null) { println("skip alias @" + start + " -- overlaps " + hit); continue; }
                    String name = String.format("alias_%08x", hex(p[0]));
                    MemoryBlock b = mem.createByteMappedBlock(name, start, src, len, false);
                    b.setRead(true); b.setWrite(false); b.setExecute(true);
                    b.setComment("non-cached alias of " + src + " (byte-mapped, not a copy)");
                    println(String.format("alias  %s..%s -> %s (0x%x bytes)",
                            start, start.add(len - 1), src, len));

                } else if (a.startsWith("--uninit=")) {
                    String[] p = a.substring(9).split(":");
                    if (p.length < 2) { println("bad --uninit (want start:len[:name[:flags]]): " + a); continue; }
                    Address start = addr(hex(p[0]));
                    long len = hex(p[1]);
                    String name = p.length > 2 && !p[2].isEmpty() ? p[2]
                                : String.format("mem_%08x", hex(p[0]));
                    String flags = p.length > 3 ? p[3].toLowerCase() : "rw";
                    String hit = occupiedBy(start, len);
                    if (hit != null) { println("skip " + name + " @" + start + " -- overlaps " + hit
                            + " (expected: the TriCore .pspec already declares RAM/CSFR)"); continue; }
                    MemoryBlock b = mem.createUninitializedBlock(name, start, len, false);
                    b.setRead(flags.contains("r")); b.setWrite(flags.contains("w"));
                    b.setExecute(flags.contains("x")); b.setVolatile(flags.contains("v"));
                    println(String.format("uninit %s %s..%s (0x%x bytes, %s)",
                            name, start, start.add(len - 1), len, flags));

                } else {
                    println("MapMemory: ignoring unknown arg " + a);
                }
            } catch (Exception e) {
                println("MapMemory: FAILED on " + a + " -- " + e.getMessage());
            }
        }
        println("MapMemory: blocks now = " + mem.getBlocks().length);
    }
}
