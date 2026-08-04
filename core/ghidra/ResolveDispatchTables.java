// Ghidra headless: resolve indirect call/jump targets that the decompiler could not
// ("Could not recover jumptable ... Too many branches" / "Treating indirect jump as call").
// These are the function-pointer dispatch tables through which the CAN/Com/GPTA/diagnostic
// subsystems invoke handlers indirectly, so their targets never get an incoming reference and
// stay unlinked in the static call graph.
//
// Per function, seeds a0/a1/a8 (like ResolveCalReads) and runs SymbolicPropogator, then at every
// COMPUTED call/jump it resolves the target address register two ways:
//   const  -- the register folds to a constant code pointer (a single indirect call).
//   table  -- the register is loaded from [base] where the memory base register folds to a
//             constant table address; it then reads the RUN of consecutive word-aligned code
//             pointers at that base (same test as research/discovery/gen_tablemap.py) and emits
//             each as a candidate target.
// Output CSV: function,site,kind,base,target  (base=0 for const).  With --addrefs it also creates
// a COMPUTED_CALL reference site->target so RecoverReferencedCode + DecompileAll pick the handler
// up. Default is CSV-only (no project mutation) -- inspect the CSV first, then re-run --addrefs.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ResolveDispatchTables.java [out.csv] [--addrefs] \
//       [--code=0xLO:0xHI] [0xfuncAddr ...]
//
// CAUTION (see maps/dispatch_tables.md): 20-43% of swept pointer-run entries are switch LABELS,
// not function entries. --addrefs adds references (RecoverReferencedCode then refuses erased /
// too-short targets), but do NOT blindly create functions at every emitted target.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.util.SymbolicPropogator;
import ghidra.program.util.ContextEvaluatorAdapter;
import java.io.PrintWriter;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.List;

public class ResolveDispatchTables extends GhidraScript {
    long codeLo = 0x80020000L, codeHi = 0x80200000L;   // valid indirect-target range
    int  maxRun = 128;                                 // cap pointers read from one table base
    boolean addRefs = false;

    private static long hex(String s) { return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16); }
    private boolean isCodePtr(long v) { return (v & 1) == 0 && v >= codeLo && v < codeHi; }

    @Override
    public void run() throws Exception {
        String out = null;
        List<String> fsel = new ArrayList<>();
        for (String a : getScriptArgs()) {
            if (a.equals("--addrefs")) addRefs = true;
            else if (a.startsWith("--code=")) {
                String[] p = a.substring(7).split(":");
                if (p.length != 2) { println("bad --code (want --code=0xLO:0xHI)"); return; }
                codeLo = hex(p[0]); codeHi = hex(p[1]);
            }
            else if (a.startsWith("0x")) fsel.add(a);
            else if (out == null) out = a;
        }
        Memory mem = currentProgram.getMemory();
        List<Function> funcs = new ArrayList<>();
        if (!fsel.isEmpty()) {
            for (String a : fsel) {
                Function f = getFunctionAt(currentProgram.getAddressFactory().getAddress(a));
                if (f != null) funcs.add(f);
            }
        } else {
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext()) funcs.add(it.next());
        }

        PrintWriter pw = (out != null) ? new PrintWriter(new FileWriter(out)) : new PrintWriter(System.out);
        pw.println("function,site,kind,base,target");
        int sites = 0, emitted = 0;

        for (Function f : funcs) {
            if (monitor.isCancelled()) break;
            SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
            sp.flowConstants(f.getEntryPoint(), f.getBody(), new ContextEvaluatorAdapter(), false, monitor);
            String fname = f.getName() + "@" + f.getEntryPoint();

            Instruction ins = getInstructionAt(f.getEntryPoint());
            while (ins != null && f.getBody().contains(ins.getAddress())) {
                if (ins.getFlowType().isComputed()
                        && (ins.getFlowType().isCall() || ins.getFlowType().isJump())) {
                    sites++;
                    Register treg = addrRegOperand(ins);
                    if (treg != null) {
                        // (1) constant target: the branch register folds to a code pointer.
                        SymbolicPropogator.Value tv = sp.getRegisterValue(ins.getAddress(), treg);
                        if (tv != null && !tv.isRegisterRelativeValue() && isCodePtr(tv.getValue() & 0xffffffffL)) {
                            emitted += emit(pw, fname, ins, "const", 0, tv.getValue() & 0xffffffffL);
                        }
                        // (2) the branch register is loaded from memory. Resolve the load's
                        // effective address from its base register:
                        //   base folds to a plain constant  -> single function pointer *(addr)
                        //   base is register-relative (addsc.a base + idx*scale) -> jump/dispatch
                        //     TABLE at the constant part; read the run of code pointers there.
                        long[] lr = loadAddr(sp, f, ins, treg);   // {effAddr, isTable} or null
                        if (lr != null) {
                            if (lr[1] == 0) {                     // single pointer
                                Address pa = toAddr(lr[0]);
                                if (mem.contains(pa)) {
                                    long ptr = mem.getInt(pa) & 0xffffffffL;
                                    if (isCodePtr(ptr)) emitted += emit(pw, fname, ins, "const-ptr", lr[0], ptr);
                                }
                            } else {                              // indexed table
                                int n = 0;
                                for (long p = lr[0]; n < maxRun; p += 4, n++) {
                                    Address pa = toAddr(p);
                                    if (!mem.contains(pa)) break;
                                    long ptr = mem.getInt(pa) & 0xffffffffL;
                                    if (!isCodePtr(ptr)) break;
                                    emitted += emit(pw, fname, ins, "table@0x" + Long.toHexString(lr[0]), lr[0], ptr);
                                }
                            }
                        }
                    }
                }
                ins = ins.getNext();
            }
        }
        pw.flush();
        if (out != null) pw.close();
        println("DISPATCHDONE: " + sites + " computed sites, " + emitted + " targets"
                + (addRefs ? " (references added)" : " (CSV only)"));
    }

    // the address-register (aN) operand of an indirect call/jump
    private Register addrRegOperand(Instruction ins) {
        for (int op = 0; op < ins.getNumOperands(); op++)
            for (Object o : ins.getOpObjects(op))
                if (o instanceof Register && ((Register) o).getName().matches("a\\d+"))
                    return (Register) o;
        return null;
    }

    // Walk back within the function for the load that defines treg and compute its effective
    // address. Returns {effAddr, isTable}: isTable=1 when the base register is register-relative
    // (base_const + index_reg*scale, i.e. a jump/dispatch table) so the caller reads a run;
    // isTable=0 when the base folds to a plain constant (a single function pointer). null = no
    // resolvable load found. Only flash-resident effective addresses are returned.
    private long[] loadAddr(SymbolicPropogator sp, Function f, Instruction branch, Register treg) {
        Instruction ins = branch.getPrevious();
        for (int k = 0; k < 16 && ins != null && f.getBody().contains(ins.getAddress()); k++, ins = ins.getPrevious()) {
            String mn = ins.getMnemonicString().toLowerCase();
            if (!mn.startsWith("ld")) continue;
            Register dst = (ins.getNumOperands() > 0 && ins.getOpObjects(0).length > 0
                    && ins.getOpObjects(0)[0] instanceof Register) ? (Register) ins.getOpObjects(0)[0] : null;
            if (dst == null || !dst.getName().equals(treg.getName())) continue;
            // source operand: base register (aN) + optional signed displacement scalar
            Register mbase = null; long disp = 0;
            for (int op = ins.getNumOperands() - 1; op >= 1; op--)
                for (Object o : ins.getOpObjects(op)) {
                    if (o instanceof Register && ((Register) o).getName().matches("a\\d+")) mbase = (Register) o;
                    else if (o instanceof ghidra.program.model.scalar.Scalar) disp = ((ghidra.program.model.scalar.Scalar) o).getSignedValue();
                }
            if (mbase == null) return null;
            SymbolicPropogator.Value bv = sp.getRegisterValue(ins.getAddress(), mbase);
            if (bv == null) return null;
            long eff = (bv.getValue() + disp) & 0xffffffffL;
            if (eff < codeLo || eff >= 0x80200000L) return null;   // must be flash-resident
            return new long[] { eff, bv.isRegisterRelativeValue() ? 1 : 0 };
        }
        return null;
    }

    private int emit(PrintWriter pw, String fname, Instruction ins, String kind, long base, long target) {
        pw.println(String.format("%s,%s,%s,0x%08x,0x%08x", fname, ins.getAddress(), kind, base, target));
        if (addRefs) {
            try {
                currentProgram.getReferenceManager().addMemoryReference(
                        ins.getAddress(), toAddr(target), RefType.COMPUTED_CALL, SourceType.ANALYSIS, 0);
            } catch (Exception e) { /* best-effort */ }
        }
        return 1;
    }
}
