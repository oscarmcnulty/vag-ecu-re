// Ghidra headless postScript: recover functions in undefined-code ranges by walking addresses
// and letting Ghidra's OWN recursive-descent disassembly + function creation determine each
// function's extent (rather than a fragile hand-rolled linear sweep). At each still-undefined
// address: disassemble (recursive descent follows real control flow and stops at ret), create a
// function, then jump past the created body to the next undefined address. For RAM-fn-pointer-
// dispatched clusters that have NO direct CALL / flash pointer / resolvable table (so neither
// call-harvest nor address-sweep can seed them).
//
// ERASED-FLASH GUARD -- the reason this is in core/ and the research/discovery original is not.
// Erased Infineon flash reads 0x00, and 0x0000 is a VALID TriCore 16-bit instruction. An
// unguarded walk therefore runs straight through erased sectors inventing plausible-looking
// functions: on 8R0907115N_0006 it produced 32948 functions of which 98.2% started on
// 0x00000000, "raising" coverage from 38.7% to 71.9% while finding no code whatsoever. Coverage
// inflated that way is worse than no number, because it reads as progress. So:
//   1. never SEED inside a zero run -- skip to the next non-zero byte;
//   2. after creation, reject any function whose body is >= ZERO_BODY_MAX zero bytes.
// Both counters are reported, so the guard's effect stays visible rather than implicit.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript RecoverGapWalk.java <entriesOut> <lo1> <hi1> [<lo2> <hi2> ...]
// Run SetBaseRegs.java first (a0/a1/a8 seeded) so decompiles resolve cleanly.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import java.io.FileWriter;
import java.util.*;

public class RecoverGapWalk extends GhidraScript {

    /** A seed is refused if this many bytes from it are all zero. */
    private static final int ZERO_SEED_WINDOW = 8;
    /** A created function is rolled back if at least this fraction of its body is zero. */
    private static final double ZERO_BODY_MAX = 0.95;

    private byte at(long a) {
        try { return currentProgram.getMemory().getByte(toAddr(a)); } catch (Exception e) { return -1; }
    }

    private boolean zeroRun(long a, int n) {
        for (int i = 0; i < n; i++) if (at(a + i) != 0) return false;
        return true;
    }

    private double zeroFrac(Function f) {
        long zeros = 0, seen = 0;
        for (AddressRange r : f.getBody()) {
            int n = (int) Math.min(r.getLength(), 4096);
            byte[] buf = new byte[n];
            try { currentProgram.getMemory().getBytes(r.getMinAddress(), buf); } catch (Exception e) { continue; }
            for (byte b : buf) if (b == 0) zeros++;
            seen += n;
        }
        return seen == 0 ? 0.0 : (double) zeros / seen;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args[0];
        List<long[]> ranges = new ArrayList<>();
        for (int i = 1; i + 1 < args.length; i += 2)
            ranges.add(new long[]{ currentProgram.getAddressFactory().getAddress(args[i]).getOffset(),
                                   currentProgram.getAddressFactory().getAddress(args[i+1]).getOffset() });
        List<Address> created = new ArrayList<>();
        int disFail = 0, skippedErased = 0, rejectedZeroBody = 0;

        for (long[] r : ranges) {
            long a = r[0], hi = r[1];
            int guard = 0;
            while (a < hi && guard++ < 400000) {
                Address ad = toAddr(a);
                Function cont = getFunctionContaining(ad);
                if (cont != null) {
                    long end = cont.getBody().getMaxAddress().getOffset();
                    a = Math.max(end + 1, a + 2);
                    continue;
                }
                // GUARD 1: refuse to seed inside erased flash. Walk to the next non-zero byte
                // instead of stepping a halfword at a time, so large erased sectors are cheap.
                if (zeroRun(a, ZERO_SEED_WINDOW)) {
                    long b = a;
                    while (b < hi && at(b) == 0) b++;
                    skippedErased += (int) Math.min(b - a, Integer.MAX_VALUE);
                    a = (b > a) ? b : a + 2;
                    continue;
                }
                Instruction in = getInstructionAt(ad);
                if (in == null) {
                    try { disassemble(ad); } catch (Exception e) {}
                    in = getInstructionAt(ad);
                }
                if (in == null) { a += 2; disFail++; continue; }
                try { new CreateFunctionCmd(ad).applyTo(currentProgram, monitor); } catch (Exception e) {}
                Function f = getFunctionAt(ad);
                if (f != null) {
                    // GUARD 2: recursive descent can still run OFF the end of real code into an
                    // erased tail. Judge the body, not the seed.
                    if (zeroFrac(f) >= ZERO_BODY_MAX) {
                        long end = f.getBody().getMaxAddress().getOffset();
                        try { removeFunction(f); } catch (Exception e) {}
                        rejectedZeroBody++;
                        a = Math.max(end + 1, a + 2);
                        continue;
                    }
                    created.add(ad);
                    long end = f.getBody().getMaxAddress().getOffset();
                    a = Math.max(end + 1, a + 2);
                } else {
                    a += in.getLength();
                }
            }
        }

        int small = 0, mid = 0, big = 0;
        for (Address e : created) {
            long n = getFunctionAt(e).getBody().getNumAddresses();
            if (n < 512) small++; else if (n < 4000) mid++; else big++;
        }
        println("RecoverGapWalk: created " + created.size() + " functions (disFail halfwords=" + disFail
                + " erased-bytes-skipped=" + skippedErased + " zero-body-rejected=" + rejectedZeroBody + ")");
        println("RecoverGapWalk: body sizes  <512B=" + small + "  512-4000B=" + mid + "  >4000B=" + big);
        Collections.sort(created, (x,y)->Long.compareUnsigned(x.getOffset(),y.getOffset()));
        try (FileWriter w = new FileWriter(out)) {
            for (Address e : created) w.write("0x" + e.toString() + "\n");
        }
    }
}
