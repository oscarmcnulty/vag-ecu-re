// Ghidra headless postScript: turn UNDEFINED bytes into functions, but only where there
// is positive evidence that the bytes are code -- namely an incoming call/jump reference.
//
// This is the safe counterpart to RecoverGapWalk.java. RecoverGapWalk disassembles gaps
// blind, which on a TriCore image is actively harmful: erased Infineon flash reads 0x00,
// 0x00 bytes decode to valid-looking instructions, and a blind walk therefore converts
// erased sectors into thousands of junk functions. Measured on MED17.1.1: 32948 functions
// created, 1.1 MB of 0x00 fill reclassified as "code", average body ~6 bytes.
//
// Here the seed is a reference that ALREADY exists in the program: something branches or
// calls into this address, so it is code by construction. Additionally:
//   - all-zero (erased) targets are refused outright;
//   - a created function is KEPT only if its body decodes to at least `--min` bytes,
//     otherwise it is rolled back, so a bad seed cannot leave debris behind.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript RecoverReferencedCode.java <lo> <hi> \
//           [entriesOut] [--min=8] [-n]
// -n / --dry-run reports what it would recover (use this first: it also tells you how much
// of the unaccounted space is referenced at all, i.e. the realistic ceiling).
//@category VAG-RE
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.symbol.ReferenceManager;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeSet;

public class RecoverReferencedCode extends GhidraScript {

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    private boolean undefinedAt(Listing lst, Address a) {
        CodeUnit cu = lst.getCodeUnitAt(a);
        if (cu == null) return false;
        if (cu instanceof ghidra.program.model.listing.Instruction) return false;
        return !(cu instanceof Data && ((Data) cu).isDefined());
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean dry = false;
        int min = 8;
        String out = null;
        List<String> pos = new ArrayList<>();
        for (String a : args) {
            if (a.equals("-n") || a.equals("--dry-run")) dry = true;
            else if (a.startsWith("--min=")) min = Integer.parseInt(a.substring(6));
            else if (a.startsWith("0x") || a.matches("[0-9a-fA-F]{6,}")) pos.add(a);
            else out = a;
        }
        if (pos.size() < 2) {
            println("usage: RecoverReferencedCode <lo> <hi> [entriesOut] [--min=N] [-n]");
            return;
        }
        long lo = hex(pos.get(0)), hi = hex(pos.get(1));
        Listing lst = currentProgram.getListing();
        ReferenceManager rm = currentProgram.getReferenceManager();

        // collect undefined addresses that something calls or jumps to
        TreeSet<Long> seeds = new TreeSet<>();
        ReferenceIterator it = rm.getReferenceIterator(toAddr(lo));
        while (it.hasNext() && !monitor.isCancelled()) {
            Reference r = it.next();
            Address to = r.getToAddress();
            long t = to.getOffset();
            if (t < lo) continue;
            if (t >= hi) break;
            RefType ty = r.getReferenceType();
            if (!ty.isCall() && !ty.isJump()) continue;
            if (!undefinedAt(lst, to)) continue;
            seeds.add(t);
        }

        int created = 0, refusedErased = 0, rolledBack = 0;
        long bytes = 0;
        List<String> entries = new ArrayList<>();
        byte[] probe = new byte[4];

        for (long t : seeds) {
            if (monitor.isCancelled()) break;
            Address a = toAddr(t);
            try {
                currentProgram.getMemory().getBytes(a, probe);
                boolean allZero = true;
                for (byte b : probe) if (b != 0) { allZero = false; break; }
                if (allZero) { refusedErased++; continue; }   // erased flash, not code
            } catch (Exception e) { continue; }

            if (dry) { created++; entries.add("0x" + a); continue; }

            disassemble(a);
            new CreateFunctionCmd(a).applyTo(currentProgram, monitor);
            Function f = getFunctionAt(a);
            if (f == null) continue;
            long sz = f.getBody().getNumAddresses();
            if (sz < min) {                       // implausibly small -> undo, leave no debris
                removeFunction(f);
                rolledBack++;
                continue;
            }
            created++; bytes += sz; entries.add("0x" + a);
        }

        if (out != null && !entries.isEmpty()) {
            try (FileWriter w = new FileWriter(out)) {
                w.write("# functions recovered from undefined bytes that had a call/jump reference\n");
                for (String e : entries) w.write(e + "\n");
            }
        }
        println(String.format("RecoverReferencedCode [%08x,%08x): referenced-undefined seeds=%d "
                + "created=%d bytes=%d refused-erased=%d rolled-back=%d%s",
                lo, hi, seeds.size(), created, bytes, refusedErased, rolledBack,
                dry ? "  (DRY RUN)" : ""));
    }
}
