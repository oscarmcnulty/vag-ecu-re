// Ghidra headless postScript: resolve the computed call/jump sites that ResolveDispatchTables
// cannot, because their function pointer lives in RAM rather than in flash -- and, for the ones
// that still fail, say exactly WHY.
//
// WHY. ResolveDispatchTables refuses any effective address outside flash ("must be flash-resident"),
// which on this image discards the whole interesting set: 305 of the 325 unresolved sites are
// `calli` through a pointer read from .data. Statically those reads return nothing, so the sites
// look unresolvable and the audit has to call them runtime-only. They are not runtime-only -- they
// are *initialiser*-only. Run core/ghidra/ApplyLoadImage.java first and the .data image from flash
// is sitting in the RAM block; then the same symbolic walk that already works for flash tables
// works for RAM tables too, with no emulation involved.
//
// The second half of this script matters as much as the first. A bare count of "still unresolved"
// is not a finding; the *reason* is. Every site that does not resolve is binned into one of:
//   NOREG        the branch operand is not an address register we can track
//   NODEF        no defining load for the branch register within the look-back window
//               (the pointer arrives as a function argument -- a genuine callback, caller-dependent)
//   NOBASE       the load's base register does not fold to a constant
//
// One idiom deserves its own recogniser because it accounts for the large majority of the
// "unresolvable" sites on this image and SymbolicPropogator cannot fold it:
//     jge.u  dN,#K,<skip>          <- the bound: the table has exactly K entries
//     movh.a aX,#HI                <- (or lea aX,[a0]disp)
//     addsc.a aX,aX,dN,#S          <- aX = base + dN<<S ; propagator gives up here
//     ld.a   aY,[aX]OFF            <- table = (HI<<16)+OFF
//     ji/calli aY
// Reading it structurally recovers base AND length exactly, with no guessing about run ends.
//   EA_UNMAPPED  effective address is outside every memory block
//   EA_UNINIT    effective address is in an uninitialised block (true BSS -> written at runtime only)
//   PTR_NULL     the slot reads back 0 (BSS/zero-init -- registered at runtime)
//   PTR_NOTCODE  the slot holds a value that is not a plausible code pointer
// Only EA_UNINIT/PTR_NULL are genuinely "needs a running ECU"; the rest are analysis limits.
//
// A resolved target is only reported as trusted when it is an EXISTING function entry -- the same
// validation rule maps/dispatch_tables.md demands, because 20-43% of swept pointer-run entries are
// switch labels rather than function starts.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ResolveRamDispatch.java [out.csv] [--addrefs] [--maxrun=N]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.util.ContextEvaluatorAdapter;
import ghidra.program.util.SymbolicPropogator;

import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

public class ResolveRamDispatch extends GhidraScript {

    private boolean addRefs = false;
    private int maxRun = 64;
    private Memory mem;
    private final Set<Long> fnEntries = new LinkedHashSet<>();

    /** flash code, its uncached alias, and the PSPR-resident helper library */
    private boolean isCodePtr(long v) {
        if ((v & 1) != 0) return false;
        return (v >= 0x80004000L && v < 0x80380000L)
            || (v >= 0xa0004000L && v < 0xa0380000L)
            || (v >= 0xc00003a0L && v < 0xc0001670L);
    }
    private long canon(long v) { return (v >= 0xa0000000L && v < 0xa0400000L) ? v - 0x20000000L : v; }

    @Override
    public void run() throws Exception {
        String out = null;
        for (String a : getScriptArgs()) {
            if (a.equals("--addrefs")) addRefs = true;
            else if (a.startsWith("--maxrun=")) maxRun = Integer.parseInt(a.substring(9));
            else if (out == null) out = a;
        }
        mem = currentProgram.getMemory();
        for (Function f : currentProgram.getFunctionManager().getFunctions(true))
            fnEntries.add(f.getEntryPoint().getOffset());

        PrintWriter pw = out != null ? new PrintWriter(new FileWriter(out)) : new PrintWriter(System.out);
        pw.println("site,function,mnemonic,verdict,ea,target,targetkind");

        Map<String, Integer> tally = new LinkedHashMap<>();
        Map<Long, SymbolicPropogator> cache = new HashMap<>();
        int sites = 0, newTargets = 0, trusted = 0;

        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) break;
            Instruction in = it.next();
            if (!in.getFlowType().isComputed()) continue;
            if (!(in.getFlowType().isCall() || in.getFlowType().isJump())) continue;
            // the alias image duplicates every site; audit the cached copy only
            if (in.getAddress().getOffset() >= 0xa0000000L) continue;
            sites++;

            Function f = getFunctionContaining(in.getAddress());
            String fname = f == null ? "(none)" : f.getName();
            String mn = in.getMnemonicString();

            if (f == null) { bin(tally, "NOFUNC"); row(pw, in, fname, mn, "NOFUNC", -1, -1, ""); continue; }
            Register treg = addrRegOperand(in);
            if (treg == null) { bin(tally, "NOREG"); row(pw, in, fname, mn, "NOREG", -1, -1, ""); continue; }

            SymbolicPropogator sp = cache.get(f.getEntryPoint().getOffset());
            if (sp == null) {
                sp = new SymbolicPropogator(currentProgram);
                sp.flowConstants(f.getEntryPoint(), f.getBody(), new ContextEvaluatorAdapter(), false, monitor);
                cache.put(f.getEntryPoint().getOffset(), sp);
                if (cache.size() > 800) cache.clear();       // bound memory on a 5900-function image
            }

            // (1) the branch register itself folds to a code pointer
            SymbolicPropogator.Value tv = sp.getRegisterValue(in.getAddress(), treg);
            if (tv != null && !tv.isRegisterRelativeValue() && isCodePtr(tv.getValue() & 0xffffffffL)) {
                long t = canon(tv.getValue() & 0xffffffffL);
                bin(tally, "CONST");
                if (emit(pw, in, fname, mn, "CONST", 0, t)) { newTargets++; if (fnEntries.contains(t)) trusted++; }
                continue;
            }

            // (2) the movh.a/addsc.a indexed-table idiom -- structural, no propagation needed
            long[] idx = indexedTable(f, in, treg);         // {base, count} or null
            if (idx != null) {
                int good = 0;
                for (int i = 0; i < idx[1]; i++) {
                    long p = idx[0] + i * 4L;
                    long v;
                    MemoryBlock bb = mem.getBlock(toAddr(p));
                    if (bb == null || !bb.isInitialized()) break;
                    try { v = mem.getInt(toAddr(p)) & 0xffffffffL; } catch (Exception e) { break; }
                    if (!isCodePtr(v)) continue;
                    good++;
                    if (emit(pw, in, fname, mn, "INDEXED", p, canon(v))) {
                        newTargets++; if (fnEntries.contains(canon(v))) trusted++;
                    }
                }
                if (good > 0) { bin(tally, "INDEXED"); continue; }
                MemoryBlock bb = mem.getBlock(toAddr(idx[0]));
                String why = bb == null ? "IDX_UNMAPPED" : !bb.isInitialized() ? "IDX_UNINIT" : "IDX_NOTCODE";
                bin(tally, why); row(pw, in, fname, mn, why, idx[0], idx[1], "");
                continue;
            }

            // (3) the branch register is loaded from memory
            long[] lr = loadAddr(sp, f, in, treg);          // {ea, isTable} or null
            if (lr == null) { bin(tally, "NODEF"); row(pw, in, fname, mn, "NODEF", -1, -1, ""); continue; }
            if (lr[1] == 2) { bin(tally, "NOBASE"); row(pw, in, fname, mn, "NOBASE", -1, -1, ""); continue; }

            long ea = lr[0];
            MemoryBlock b = mem.getBlock(toAddr(ea));
            if (b == null) { bin(tally, "EA_UNMAPPED"); row(pw, in, fname, mn, "EA_UNMAPPED", ea, -1, ""); continue; }
            if (!b.isInitialized()) { bin(tally, "EA_UNINIT"); row(pw, in, fname, mn, "EA_UNINIT", ea, -1, ""); continue; }

            int n = 0, good = 0;
            for (long p = ea; n < (lr[1] == 1 ? maxRun : 1); p += 4, n++) {
                long v;
                try { v = mem.getInt(toAddr(p)) & 0xffffffffL; } catch (Exception e) { break; }
                if (!isCodePtr(v)) {
                    if (n == 0) { bin(tally, v == 0 ? "PTR_NULL" : "PTR_NOTCODE");
                        row(pw, in, fname, mn, v == 0 ? "PTR_NULL" : "PTR_NOTCODE", p, v, ""); }
                    break;
                }
                long t = canon(v);
                good++;
                if (emit(pw, in, fname, mn, lr[1] == 1 ? "TABLE" : "PTR", p, t)) {
                    newTargets++; if (fnEntries.contains(t)) trusted++;
                }
            }
            if (good > 0) bin(tally, lr[1] == 1 ? "TABLE" : "PTR");
        }
        pw.flush();
        if (out != null) pw.close();

        println("=== ResolveRamDispatch ===");
        println("  computed sites examined: " + sites);
        for (Map.Entry<String, Integer> e : tally.entrySet())
            println(String.format("  %-12s %d", e.getKey(), e.getValue()));
        println("  targets emitted: " + newTargets + "   of which existing function entries: " + trusted);
        println("RAMDISPATCHDONE");
    }

    private void bin(Map<String, Integer> m, String k) { m.merge(k, 1, Integer::sum); }

    private void row(PrintWriter pw, Instruction in, String fn, String mn, String verdict, long ea, long tgt, String kind) {
        pw.printf("0x%s,%s,%s,%s,%s,%s,%s%n", in.getAddress(), fn, mn, verdict,
                ea < 0 ? "" : String.format("0x%08x", ea),
                tgt < 0 ? "" : String.format("0x%08x", tgt), kind);
    }

    private boolean emit(PrintWriter pw, Instruction in, String fn, String mn, String verdict, long ea, long tgt) {
        Address a = toAddr(tgt);
        Function tf = getFunctionContaining(a);
        String kind = fnEntries.contains(tgt) ? "FUNC_ENTRY"
                : tf != null ? "IN_FUNC:" + tf.getName()
                : getInstructionAt(a) != null ? "BARE_CODE" : "UNDEFINED";
        row(pw, in, fn, mn, verdict, ea, tgt, kind);
        if (addRefs) {
            try {
                currentProgram.getReferenceManager().addMemoryReference(in.getAddress(), a,
                        in.getFlowType().isCall() ? RefType.COMPUTED_CALL : RefType.COMPUTED_JUMP,
                        SourceType.ANALYSIS, 0);
            } catch (Exception e) { /* best effort */ }
        }
        return true;
    }

    /**
     * Recognise  [jge.u dN,#K] / movh.a aX,#HI | lea aX,[aC]D / addsc.a aX,aX,dN,#S / ld.a treg,[aX]OFF.
     * Returns {tableBase, entryCount}. The count comes from the range guard the compiler must emit
     * before an indexed load; without a guard we fall back to scanning the run (capped at maxRun).
     */
    private long[] indexedTable(Function f, Instruction branch, Register treg) {
        // find the defining ld.a of treg
        Instruction ld = null;
        Instruction in = branch.getPrevious();
        for (int k = 0; k < 24 && in != null && f.getBody().contains(in.getAddress()); k++, in = in.getPrevious()) {
            if (!in.getMnemonicString().toLowerCase().startsWith("ld")) continue;
            Object[] o0 = in.getOpObjects(0);
            if (o0.length > 0 && o0[0] instanceof Register && ((Register) o0[0]).getName().equals(treg.getName())) {
                ld = in; break;
            }
        }
        if (ld == null) return null;
        Register lbase = null; long off = 0;
        for (int op = ld.getNumOperands() - 1; op >= 1; op--)
            for (Object o : ld.getOpObjects(op)) {
                if (o instanceof Register && ((Register) o).getName().matches("a\\d+")) lbase = (Register) o;
                else if (o instanceof Scalar) off = ((Scalar) o).getSignedValue();
            }
        if (lbase == null) return null;

        // find addsc.a lbase, src, dIdx, #S
        Instruction asc = null; Register src = null, ireg = null; long shift = 0;
        in = ld.getPrevious();
        for (int k = 0; k < 12 && in != null && f.getBody().contains(in.getAddress()); k++, in = in.getPrevious()) {
            if (!in.getMnemonicString().toLowerCase().equals("addsc.a")) continue;
            Object[] o0 = in.getOpObjects(0);
            if (!(o0.length > 0 && o0[0] instanceof Register && ((Register) o0[0]).getName().equals(lbase.getName()))) continue;
            asc = in;
            for (Object o : in.getOpObjects(1)) if (o instanceof Register) src = (Register) o;
            for (Object o : in.getOpObjects(2)) if (o instanceof Register) ireg = (Register) o;
            for (Object o : in.getOpObjects(3)) if (o instanceof Scalar) shift = ((Scalar) o).getSignedValue();
            break;
        }
        if (asc == null || src == null || shift != 2) return null;   // only word tables

        // find the constant that defines src: movh.a aX,#HI or lea aX,[aC]D with aC a known base
        long base = Long.MIN_VALUE;
        in = asc.getPrevious();
        for (int k = 0; k < 12 && in != null && f.getBody().contains(in.getAddress()); k++, in = in.getPrevious()) {
            String m = in.getMnemonicString().toLowerCase();
            Object[] o0 = in.getOpObjects(0);
            if (!(o0.length > 0 && o0[0] instanceof Register && ((Register) o0[0]).getName().equals(src.getName()))) continue;
            if (m.equals("movh.a")) {
                for (Object o : in.getOpObjects(1)) if (o instanceof Scalar) base = ((Scalar) o).getUnsignedValue() << 16;
            } else if (m.equals("lea")) {
                Register bb = null; long d = 0;
                for (int op = 1; op < in.getNumOperands(); op++)
                    for (Object o : in.getOpObjects(op)) {
                        if (o instanceof Register) bb = (Register) o;
                        else if (o instanceof Scalar) d = ((Scalar) o).getSignedValue();
                    }
                if (bb != null) {
                    java.math.BigInteger v = currentProgram.getProgramContext()
                            .getRegisterValue(bb, in.getAddress()) == null ? null
                            : currentProgram.getProgramContext().getRegisterValue(bb, in.getAddress()).getUnsignedValue();
                    if (v != null) base = (v.longValue() + d) & 0xffffffffL;
                }
            }
            break;
        }
        if (base == Long.MIN_VALUE) return null;
        long tbl = (base + off) & 0xffffffffL;

        // the bound: nearest preceding unsigned range check on the index register
        long count = -1;
        in = asc;
        for (int k = 0; k < 16 && in != null && f.getBody().contains(in.getAddress()); k++, in = in.getPrevious()) {
            String m = in.getMnemonicString().toLowerCase();
            if (!(m.startsWith("jge.u") || m.startsWith("jlt.u"))) continue;
            boolean onIdx = false; long imm = -1;
            for (int op = 0; op < in.getNumOperands(); op++)
                for (Object o : in.getOpObjects(op)) {
                    if (o instanceof Register && ireg != null && ((Register) o).getName().equals(ireg.getName())) onIdx = true;
                    else if (o instanceof Scalar) { long s = ((Scalar) o).getUnsignedValue(); if (s > 0 && s < 0x400) imm = s; }
                }
            if (onIdx && imm > 0) { count = imm; break; }
        }
        if (count < 0) count = maxRun;
        return new long[]{tbl, count};
    }

    private Register addrRegOperand(Instruction in) {
        for (int op = 0; op < in.getNumOperands(); op++)
            for (Object o : in.getOpObjects(op))
                if (o instanceof Register && ((Register) o).getName().matches("a\\d+")) return (Register) o;
        return null;
    }

    /**
     * Walk back for the load that defines treg; return {effectiveAddress, kind} where
     * kind 0 = single pointer, 1 = indexed table (base was register-relative), 2 = base unresolvable.
     * Unlike ResolveDispatchTables this does NOT require the address to be in flash.
     */
    private long[] loadAddr(SymbolicPropogator sp, Function f, Instruction branch, Register treg) {
        Instruction in = branch.getPrevious();
        for (int k = 0; k < 24 && in != null && f.getBody().contains(in.getAddress()); k++, in = in.getPrevious()) {
            String mn = in.getMnemonicString().toLowerCase();
            if (!mn.startsWith("ld")) continue;
            Register dst = (in.getNumOperands() > 0 && in.getOpObjects(0).length > 0
                    && in.getOpObjects(0)[0] instanceof Register) ? (Register) in.getOpObjects(0)[0] : null;
            if (dst == null || !dst.getName().equals(treg.getName())) continue;
            Register mbase = null; long disp = 0; boolean sawScalar = false;
            for (int op = in.getNumOperands() - 1; op >= 1; op--)
                for (Object o : in.getOpObjects(op)) {
                    if (o instanceof Register && ((Register) o).getName().matches("a\\d+")) mbase = (Register) o;
                    else if (o instanceof Scalar) { disp = ((Scalar) o).getSignedValue(); sawScalar = true; }
                }
            if (mbase == null) return sawScalar && disp != 0 ? new long[]{disp & 0xffffffffL, 0} : new long[]{0, 2};
            SymbolicPropogator.Value bv = sp.getRegisterValue(in.getAddress(), mbase);
            if (bv == null) return new long[]{0, 2};
            return new long[]{(bv.getValue() + disp) & 0xffffffffL, bv.isRegisterRelativeValue() ? 1 : 0};
        }
        return null;
    }
}
