// Ghidra headless postScript: recover indirectly-dispatched functions hiding in the
// UNDEFINED-code gaps that call-harvest can't reach (no direct CALL edge), then inline-scan
// them for a0/a1/a8-relative effective addresses that hit target regions of interest.
//
// Motivation: FindRefsTo / decompile-grep only see DEFINED functions. The ACC subsystem has
// multi-KB gaps of high-entropy undefined code (e.g. 0x801df978..0x801e3c58, 0x801e3db0..
// 0x801e6cc8) where a function-pointer-scheduled decel coordinator would live invisibly.
// This disassembles those ranges, creates functions at the standard TriCore prologue
// (d90f = the a15/base-reg reload every compiled fn here starts with), then runs the
// SymbolicPropogator EA pass (same as FindRefsTo) over the recovered code and reports any
// ld/st whose EA lands in a --hit range.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript RecoverGapFns.java \
//     <entriesOut> <loHi...> --hit <hlo> <hhi> [--hit <hlo> <hhi> ...]
//   loHi pairs: 0xLO 0xHI [0xLO2 0xHI2 ...]  (ranges to recover, before --hit)
// Run SetBaseRegs.java first (reproduce.sh does) so a0/a1/a8 are seeded.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.util.SymbolicPropogator;
import ghidra.program.util.ContextEvaluatorAdapter;
import java.io.FileWriter;
import java.util.*;

public class RecoverGapFns extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String entriesOut = args[0];
        List<long[]> ranges = new ArrayList<>();
        List<long[]> hits = new ArrayList<>();
        int i = 1;
        // ranges (pairs) until --hit
        List<Long> nums = new ArrayList<>();
        for (; i < args.length && !args[i].equals("--hit"); i++)
            nums.add(currentProgram.getAddressFactory().getAddress(args[i]).getOffset());
        for (int k = 0; k + 1 < nums.size(); k += 2) ranges.add(new long[]{nums.get(k), nums.get(k+1)});
        for (; i < args.length; i++) {
            if (args[i].equals("--hit")) {
                long hlo = currentProgram.getAddressFactory().getAddress(args[i+1]).getOffset();
                long hhi = currentProgram.getAddressFactory().getAddress(args[i+2]).getOffset();
                hits.add(new long[]{hlo, hhi}); i += 2;
            }
        }

        // ---- pass 1: linear disassembly sweep of each range ----
        for (long[] r : ranges) {
            for (long a = r[0]; a < r[1]; a += 2) {
                Address ad = toAddr(a);
                if (getInstructionAt(ad) != null) continue;
                if (getDataAt(ad) != null && getDataAt(ad).isDefined()) continue;
                try { disassemble(ad); } catch (Exception e) {}
            }
        }

        // ---- pass 2: create functions at d90f prologue entries not yet in a function ----
        List<Address> created = new ArrayList<>();
        for (long[] r : ranges) {
            for (long a = r[0]; a < r[1]; a += 2) {
                Address ad = toAddr(a);
                Instruction in = getInstructionAt(ad);
                if (in == null) continue;
                if (getFunctionContaining(ad) != null) continue;
                int b0 = getByte(ad) & 0xff, b1 = getByte(ad.add(1)) & 0xff;
                if (!(b0 == 0xd9 && b1 == 0x0f)) continue; // standard prologue marker
                try {
                    new CreateFunctionCmd(ad).applyTo(currentProgram, monitor);
                    if (getFunctionAt(ad) != null) created.add(ad);
                } catch (Exception e) {}
            }
        }
        println("RecoverGapFns: created " + created.size() + " functions in gaps");
        try (FileWriter w = new FileWriter(entriesOut)) {
            for (Address a : created) w.write("0x" + a.toString() + "\n");
        }

        // ---- pass 3: symbolic EA scan over the recovered functions ----
        Register[] ar = new Register[16];
        for (int k = 0; k < 16; k++) ar[k] = currentProgram.getRegister("a" + k);
        println("=== EA hits in the recovered gap code ===");
        int nhit = 0;
        for (Address entry : created) {
            Function f = getFunctionAt(entry);
            if (f == null) continue;
            SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
            try { sp.flowConstants(f.getEntryPoint(), f.getBody(), new ContextEvaluatorAdapter(), false, monitor); }
            catch (Exception e) { continue; }
            Instruction in = getInstructionAt(f.getEntryPoint());
            while (in != null && f.getBody().contains(in.getAddress())) {
                String mn = in.getMnemonicString().toLowerCase();
                boolean mem = mn.startsWith("ld") || mn.startsWith("st") || mn.startsWith("swap")
                        || mn.startsWith("ldmst") || mn.startsWith("cmpswap");
                if (mem) for (int op = 0; op < in.getNumOperands(); op++) {
                    String rep = in.getDefaultOperandRepresentation(op);
                    if (rep == null || rep.indexOf('[') < 0) continue;
                    Register base = null; long disp = 0; int ac = 0;
                    for (Object o : in.getOpObjects(op)) {
                        if (o instanceof Register && ((Register)o).getName().matches("a\\d+")) { base=(Register)o; ac++; }
                        else if (o instanceof Scalar) disp = ((Scalar)o).getSignedValue();
                    }
                    if (base == null || ac != 1) continue;
                    SymbolicPropogator.Value v = sp.getRegisterValue(in.getAddress(), base);
                    if (v == null || v.isRegisterRelativeValue()) continue;
                    long ea = (v.getValue() + disp) & 0xffffffffL;
                    for (long[] h : hits) if (ea >= h[0] && ea < h[1]) {
                        boolean st = mn.startsWith("st");
                        println(String.format("  %s EA=%08x  %s  @%s in fn %s",
                                st ? "WRITE" : "READ", ea, in.toString(), in.getAddress(), entry));
                        nhit++;
                    }
                }
                in = in.getNext();
            }
        }
        println("=== done: " + nhit + " EA hits across " + created.size() + " recovered fns ===");
    }
}
