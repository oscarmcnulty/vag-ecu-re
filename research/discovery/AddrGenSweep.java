// Ghidra headless postScript: find function-pointer-table fills for RAM-dispatched code.
//
// The ACC coordinator gap code is reached ONLY via RAM function-pointer arrays (no direct CALL,
// no flash pointer). Those arrays are filled at boot by initializer code that forms each entry
// address with movh.a/lea (or lea [aBase]disp) and stores it with st.a. This scans every defined
// instruction; whenever an address register is assigned a CONSTANT that lands in a --target range,
// it reports the producing instruction (= a code entry point) and, if the next few instructions
// store that register (st.a), the store destination (= the dispatch-table slot).
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//     -scriptPath core/ghidra -postScript AddrGenSweep.java <entriesOut> <lo1> <hi1> [<lo2> <hi2> ...]
// Run SetBaseRegs.java first so a0/a1/a8 are seeded (for lea [a0]disp table stores).
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.util.SymbolicPropogator;
import ghidra.program.util.ContextEvaluatorAdapter;
import java.io.FileWriter;
import java.util.*;

public class AddrGenSweep extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = args[0];
        List<long[]> tg = new ArrayList<>();
        for (int i = 1; i + 1 < args.length; i += 2)
            tg.add(new long[]{ currentProgram.getAddressFactory().getAddress(args[i]).getOffset(),
                               currentProgram.getAddressFactory().getAddress(args[i+1]).getOffset() });
        Register[] ar = new Register[16];
        for (int i = 0; i < 16; i++) ar[i] = currentProgram.getRegister("a" + i);

        TreeSet<Long> entries = new TreeSet<>();
        // table slot (st.a dest EA) -> set of entry addresses stored there
        TreeMap<Long,TreeSet<Long>> tables = new TreeMap<>();

        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        int scanned = 0;
        while (fit.hasNext()) {
            if (monitor.isCancelled()) break;
            Function f = fit.next(); scanned++;
            SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
            try { sp.flowConstants(f.getEntryPoint(), f.getBody(), new ContextEvaluatorAdapter(), false, monitor); }
            catch (Exception e) { continue; }
            java.util.Iterator<Instruction> it =
                    currentProgram.getListing().getInstructions(f.getBody(), true);
            // remember recent (addrReg -> value) so a following st.a can be attributed
            while (it.hasNext()) {
                Instruction in = it.next();
                // For every address register, does it currently hold a target-range constant?
                for (Register a : ar) {
                    if (a == null) continue;
                    // a10 = stack pointer, a11 = return-address/link register — exclude (return
                    // addresses after `call` are not table entries; they were noise in v1).
                    String an = a.getName();
                    if (an.equals("a10") || an.equals("a11")) continue;
                    SymbolicPropogator.Value v = sp.getRegisterValue(in.getAddress(), a);
                    if (v == null || v.isRegisterRelativeValue()) continue;
                    long val = v.getValue() & 0xffffffffL;
                    long norm = val & 0xdfffffffL; // fold 0xa0 alias -> 0x80
                    for (long[] t : tg) if (norm >= t[0] && norm < t[1]) {
                        // skip addresses already inside a defined function (return-address noise / self-refs)
                        Address na = toAddr(norm);
                        if (getFunctionContaining(na) != null) break;
                        // this instruction's context has an address reg pointing at UNDEFINED gap code
                        if ((norm & 1) == 0) entries.add(norm);
                        // if THIS instruction is st.a storing that reg, capture the table slot
                        String mn = in.getMnemonicString().toLowerCase();
                        if (mn.startsWith("st.a")) {
                            // dest EA = the bracketed operand
                            for (int op = 0; op < in.getNumOperands(); op++) {
                                String rep = in.getDefaultOperandRepresentation(op);
                                if (rep == null || rep.indexOf('[') < 0) continue;
                                Register base = null; long disp = 0; int ac = 0;
                                for (Object o : in.getOpObjects(op)) {
                                    if (o instanceof Register && ((Register)o).getName().matches("a\\d+")) { base=(Register)o; ac++; }
                                    else if (o instanceof Scalar) disp = ((Scalar)o).getSignedValue();
                                }
                                if (base == null || ac != 1) continue;
                                SymbolicPropogator.Value bv = sp.getRegisterValue(in.getAddress(), base);
                                if (bv == null || bv.isRegisterRelativeValue()) continue;
                                long ea = (bv.getValue() + disp) & 0xffffffffL;
                                tables.computeIfAbsent(ea, k->new TreeSet<>()).add(norm);
                            }
                        }
                        break;
                    }
                }
            }
        }
        println("AddrGenSweep: scanned " + scanned + " fns; " + entries.size()
                + " distinct gap-code entries; " + tables.size() + " table slots");
        println("=== ENTRIES (address-taken code in target ranges) ===");
        for (long e : entries) println(String.format("  entry %08x", e));
        println("=== TABLE SLOTS (st.a dest -> stored entry) ===");
        for (Map.Entry<Long,TreeSet<Long>> e : tables.entrySet()) {
            StringBuilder sb = new StringBuilder();
            for (long v : e.getValue()) sb.append(String.format("%08x ", v));
            println(String.format("  slot %08x <- %s", e.getKey(), sb.toString().trim()));
        }
        try (FileWriter w = new FileWriter(out)) {
            for (long e : entries) w.write(String.format("0x%08x%n", e));
        }
    }
}
