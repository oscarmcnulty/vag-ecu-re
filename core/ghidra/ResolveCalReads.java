// Ghidra headless: resolve calibration (a1-relative) memory accesses via symbolic
// propagation, including register+immediate, pointer-table, and runtime-INDEXED arrays
// whose base is `a1 + const` (e.g. the decel-limit curve) that produce no static ref.
//
// Seeds a0/a1/a8 base registers, runs SymbolicPropogator per function, and for every
// ld/st/lea whose base register resolves to a constant in the cal window it emits:
//   FUNC@entry , insaddr , R|W|P , 0xCALADDR , mnemonic
// (R=load, W=store, P=pointer/address computed by lea into cal). CSV to stdout (CAL: prefix).
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ResolveCalReads.java [out.csv] [funcAddr ...]
// First non-0x arg = output CSV path (else stdout). 0x-args = restrict to those functions
// (else every function). CSV columns: function,insaddr,rw,caladdr,mnemonic.
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
import java.io.PrintWriter;
import java.io.FileWriter;

public class ResolveCalReads extends GhidraScript {
    // Cal window, i.e. which effective addresses count as "a calibration access".
    // Defaults are the simos85 map region; the window spans BOTH sides of the a1 base
    // (0x80048000) because e.g. C_VS_MIN_CRU_MON sits at a1-0x2940. Override per ECU
    // with --cal=0xLO:0xHI (MED17.1.1 cal lives elsewhere in its 4 MB image).
    long calLo = 0x80040000L, calHi = 0x80080000L;

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = null;
        java.util.List<String> funcAddrs = new java.util.ArrayList<>();
        for (String a : args) {
            if (a.startsWith("--cal=")) {
                String[] p = a.substring(6).split(":");
                if (p.length != 2) { println("bad --cal (want --cal=0xLO:0xHI): " + a); return; }
                calLo = hex(p[0]); calHi = hex(p[1]);
            }
            else if (a.startsWith("0x")) funcAddrs.add(a);
            else if (outPath == null) outPath = a;
        }
        println(String.format("ResolveCalReads: cal window 0x%08x..0x%08x", calLo, calHi));
        java.util.List<Function> funcs = new java.util.ArrayList<>();
        if (!funcAddrs.isEmpty()) {
            for (String a : funcAddrs) {
                Function f = getFunctionAt(currentProgram.getAddressFactory().getAddress(a));
                if (f != null) funcs.add(f);
            }
        } else {
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext()) funcs.add(it.next());
        }

        PrintWriter out = (outPath != null) ? new PrintWriter(new FileWriter(outPath))
                                            : new PrintWriter(System.out);
        out.println("function,insaddr,rw,caladdr,mnemonic");
        int emitted = 0;

        for (Function f : funcs) {
            if (monitor.isCancelled()) break;
            // a0/a1/a8 are already set in the program context by SetBaseRegs, so the
            // propagator starts from those values (plus any in-function reloads).
            SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
            Address entry = f.getEntryPoint();
            sp.flowConstants(entry, f.getBody(), new ContextEvaluatorAdapter(), false, monitor);

            String fname = f.getName() + "@" + entry;
            Instruction ins = getInstructionAt(entry);
            while (ins != null && f.getBody().contains(ins.getAddress())) {
                String mn = ins.getMnemonicString().toLowerCase();
                char rw = mn.startsWith("ld") ? 'R' : mn.startsWith("st") ? 'W'
                        : (mn.equals("lea") ? 'P' : 0);
                if (rw != 0) {
                    // memory operand is the [base]disp form; iterate operands in reverse so we
                    // take the address operand (last), not the lea/ld destination register.
                    for (int op = ins.getNumOperands() - 1; op >= 0; op--) {
                        Register base = null; Scalar disp = null;
                        for (Object o : ins.getOpObjects(op)) {
                            if (o instanceof Register && ((Register) o).getName().matches("a\\d+"))
                                base = (Register) o;
                            else if (o instanceof Scalar) disp = (Scalar) o;
                        }
                        long eff;
                        if (base != null) {
                            SymbolicPropogator.Value v = sp.getRegisterValue(ins.getAddress(), base);
                            if (v == null || v.isRegisterRelativeValue()) continue;
                            eff = (v.getValue() + (disp != null ? disp.getSignedValue() : 0))
                                  & 0xffffffffL;
                        } else if (disp != null) {          // absolute address encoded as scalar
                            eff = disp.getSignedValue() & 0xffffffffL;
                        } else continue;
                        if (eff >= calLo && eff < calHi) {
                            out.println(String.format("%s,%s,%c,0x%08x,%s",
                                    fname, ins.getAddress(), rw, eff, mn));
                            emitted++;
                            break;
                        }
                    }
                }
                ins = ins.getNext();
            }
        }
        out.flush();
        if (outPath != null) out.close();
        println("CALDONE: emitted " + emitted + " cal accesses -> "
                + (outPath != null ? outPath : "stdout"));
    }
}
