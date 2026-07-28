// Ghidra headless postScript: list all references TO each given address.
//
// TWO passes:
//  [refdb] Ghidra's reference database (getReferencesTo) — catches absolute-addressed
//          accesses and anything auto-analysis resolved.
//  [sym]   A SymbolicPropogator scan over every function that resolves the effective
//          address of each ld/st from its base register (a0=0xd0008000 SDA, a1=0x80048000
//          cal, a8, or any reg formed by lea/addsc.a) + displacement. This catches the
//          **a0/a1-relative accesses the reference DB MISSES** — e.g. `st.h [a0]0x59e4`
//          = write to d000d9e4, which getReferencesTo does not index. Run SetBaseRegs.java
//          first (reproduce.sh does) so a0/a1/a8 are seeded in the context.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript FindRefsTo.java <addr1> [addr2 ...] [--refdb-only]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import ghidra.program.model.symbol.RefType;
import ghidra.program.util.SymbolicPropogator;
import ghidra.program.util.ContextEvaluatorAdapter;
import java.util.*;

public class FindRefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean symPass = true, rangeMode = false;
        List<Long> targets = new ArrayList<>();
        List<String> targetStrs = new ArrayList<>();
        List<Long> hexNums = new ArrayList<>();
        for (String a : args) {
            if (a.equals("--refdb-only")) { symPass = false; continue; }
            if (a.equals("--range")) { rangeMode = true; continue; }
            Address t = currentProgram.getAddressFactory().getAddress(a);
            if (t == null) continue;
            targets.add(t.getOffset());
            targetStrs.add(a);
            hexNums.add(t.getOffset());
        }
        // RANGE MODE: FindRefsTo 0xLO 0xHI --range -> report every a0/a1-relative ld/st whose EA
        // lands in [LO,HI), grouped by function. Maps a whole RAM region's writer/reader graph.
        if (rangeMode && hexNums.size() >= 2) {
            long lo = hexNums.get(0), hi = hexNums.get(1);
            Register[] ar = new Register[16];
            for (int i = 0; i < 16; i++) ar[i] = currentProgram.getRegister("a" + i);
            println(String.format("=== RANGE [%x,%x): a0/a1-relative ld/st EA matches ===", lo, hi));
            int hh = 0, sc = 0;
            FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
            while (fit.hasNext()) {
                if (monitor.isCancelled()) break;
                Function f = fit.next(); sc++;
                SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
                try { sp.flowConstants(f.getEntryPoint(), f.getBody(), new ContextEvaluatorAdapter(), false, monitor); }
                catch (Exception e) { continue; }
                Instruction in = getInstructionAt(f.getEntryPoint());
                TreeMap<Long,String> rows = new TreeMap<>();
                while (in != null && f.getBody().contains(in.getAddress())) {
                    String mn = in.getMnemonicString().toLowerCase();
                    boolean ld = mn.startsWith("ld")||mn.startsWith("swap")||mn.startsWith("ldmst")||mn.startsWith("cmpswap");
                    boolean st = mn.startsWith("st")||mn.startsWith("swap")||mn.startsWith("ldmst")||mn.startsWith("cmpswap");
                    if (ld || st) for (int op = 0; op < in.getNumOperands(); op++) {
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
                        if (ea >= lo && ea < hi) {
                            String rw = (st && !ld) ? "W" : (ld && !st) ? "R" : "RMW";
                            rows.put((ea<<4)|(rw.equals("W")?1:2), String.format("    %s 0x%x  %s", rw, ea, in.toString()));
                        }
                    }
                    in = in.getNext();
                }
                if (!rows.isEmpty()) {
                    println(String.format("  %s@%s:", f.getName(), f.getEntryPoint()));
                    for (String s : rows.values()) { println(s); hh++; }
                }
            }
            println("RANGE done: " + sc + " functions, " + hh + " matches");
            return;
        }

        // ---- PASS 1: reference database ----
        ReferenceManager rm = currentProgram.getReferenceManager();
        for (int k = 0; k < targets.size(); k++) {
            Address tgt = currentProgram.getAddressFactory().getAddress(targetStrs.get(k));
            println("=== refs to " + targetStrs.get(k) + " ===");
            for (Reference r : rm.getReferencesTo(tgt)) {
                Address from = r.getFromAddress();
                Function fn = getFunctionContaining(from);
                String fname = (fn == null) ? "<gap>" : (fn.getName() + "@" + fn.getEntryPoint());
                Instruction ins = getInstructionAt(from);
                println(String.format("  [refdb] from %s  %-7s  in %s   | %s",
                        from, r.getReferenceType().getName(), fname,
                        ins == null ? "?" : ins.toString()));
            }
        }
        if (!symPass) return;

        // ---- PASS 2: symbolic effective-address scan (a0/a1/a8-relative + propagated) ----
        Set<Long> tset = new HashSet<>(targets);
        Register[] aregs = new Register[16];
        for (int i = 0; i < 16; i++) aregs[i] = currentProgram.getRegister("a" + i);
        // avoid double-reporting an access the refdb already listed
        Set<String> refdbFrom = new HashSet<>();
        for (Long t : targets) {
            Address tgt = currentProgram.getAddressFactory().getAddress(String.format("0x%x", t));
            for (Reference r : rm.getReferencesTo(tgt)) refdbFrom.add(t + "@" + r.getFromAddress());
        }
        println("=== symbolic (a0/a1/a8-relative) EA matches — the refs getReferencesTo misses ===");
        int hits = 0, scanned = 0;
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Function f = it.next(); scanned++;
            SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
            Address entry = f.getEntryPoint();
            try { sp.flowConstants(entry, f.getBody(), new ContextEvaluatorAdapter(), false, monitor); }
            catch (Exception e) { continue; }
            Instruction ins = getInstructionAt(entry);
            while (ins != null && f.getBody().contains(ins.getAddress())) {
                String mn = ins.getMnemonicString().toLowerCase();
                boolean isLd = mn.startsWith("ld") || mn.startsWith("swap") || mn.startsWith("ldmst") || mn.startsWith("cmpswap");
                boolean isSt = mn.startsWith("st") || mn.startsWith("swap") || mn.startsWith("ldmst") || mn.startsWith("cmpswap");
                if (isLd || isSt) {
                    // find the memory operand: the DEREFERENCED operand (bracketed [base]disp),
                    // not an address register used as a plain value (ld.a dst / st.a src).
                    for (int op = 0; op < ins.getNumOperands(); op++) {
                        String rep = ins.getDefaultOperandRepresentation(op);
                        if (rep == null || rep.indexOf('[') < 0) continue;
                        Register base = null; long disp = 0; int aregCount = 0;
                        for (Object o : ins.getOpObjects(op)) {
                            if (o instanceof Register) {
                                Register rg = (Register) o;
                                if (rg.getName().matches("a\\d+")) { base = rg; aregCount++; }
                            } else if (o instanceof Scalar) disp = ((Scalar) o).getSignedValue();
                        }
                        if (base == null || aregCount != 1) continue;   // skip indexed [a+a] / non-memory
                        SymbolicPropogator.Value v = sp.getRegisterValue(ins.getAddress(), base);
                        if (v == null || v.isRegisterRelativeValue()) continue;
                        long ea = (v.getValue() + disp) & 0xffffffffL;
                        if (tset.contains(ea)) {
                            String key = ea + "@" + ins.getAddress();
                            if (refdbFrom.contains(key)) continue;   // already in refdb pass
                            String rw = (isSt && !isLd) ? "WRITE" : (isLd && !isSt) ? "READ" : "RMW";
                            println(String.format("  [sym] to 0x%x  %-5s  in %s@%s (base %s)   | %s",
                                ea, rw, f.getName(), entry, base.getName(), ins.toString()));
                            hits++;
                        }
                    }
                }
                ins = ins.getNext();
            }
        }
        println("FindRefsTo: symbolic pass scanned " + scanned + " functions, " + hits + " new (non-refdb) EA matches");
    }
}
