// Ghidra headless: resolve MED17 calibration accesses that go through the a9 CAL-OBJECT TABLE,
// including the ones reached with a COMPUTED (runtime-indexed) offset.
//
// WHY THIS EXISTS
// ---------------
// MED17.1.1 does not address calibration off a base register the way Simos8.5 does (there a1 +
// const is the whole story, which is what core/ghidra/ResolveCalReads.java was built for). Here
// a9 = 0x80103464 is an OBJECT TABLE of 971 pointers, and a cal datum is reached in two hops:
//
//     ld.a  a12,[a9]0x3dc        ; a12 = *(0x80103840) = 0x803b4834   <- the cal OBJECT
//     ld.h  d15,[a12]0xa8        ; the datum at object+0xa8 = 0x803b48dc
//
// SymbolicPropogator cannot make that first hop -- it does not fold the load out of the table --
// so ResolveCalReads.java emits *nothing* in the ACC/TSK cluster (analysis/cal_reads.csv has 0
// rows for e.g. FUN_801418ea, which is wall-to-wall cal reads). The decompiler does fold it, so a
// regex over the decompiled C recovers the LITERAL form `PTR_DAT_<entry> + <const>`. What a regex
// structurally cannot see is the second family, which this ECU uses for its curve arrays:
//
//     ld.a   a12,[a9]0x3dc       ; a12 = cal object 0x803b4834
//     mov.d  d0,a12              ; object base moved into a DATA register
//     ld.bu  d15,0xd00029ba      ; runtime selector
//     madd   d15,d0,d15,#0x16    ; base + idx*22   <- 22-byte Kennlinie records
//     mov.a  a15,d15
//     lea    a4,[a15]0x42        ; -> curve pointer handed to Kennlinie_s16 (0xc0000638)
//
// Nothing in that chain is a `PTR_DAT_x + const`, and the address never becomes a constant, so
// both the regex sweep and any constant-only propagator drop it silently. That is the same class
// of blind spot that previously hid 277 KB of code in this image.
//
// WHAT IT DOES
// ------------
// Per function it runs its own CFG fixpoint over a small abstract domain (constant / cal-object-
// relative / cal-object-relative-plus-unknown-index / unknown) across BOTH address and data
// registers -- data registers matter because the indexing above happens in d-regs via mov.d/madd/
// mov.a. It models mov.a/mov.d/mov.aa/movh.a/lea/add.a/addih.a/sub.a/addsc.a/addsc.at/madd/msub/
// add/addi/sh and folds pointer-width loads out of FLASH only (flash is immutable, RAM is not).
// It reads ResolveDispatchTables.java's SymbolicPropogator idiom for the operand/base-register
// conventions but does not use SymbolicPropogator itself: that class keeps only constants and
// register-relative sums, and cannot carry "this register is cal object #247 plus an unknown
// index", which is exactly the fact this script exists to recover.
//
// Every ld/st/lea whose base resolves into the cal window is emitted as one CSV row:
//   function,insaddr,rw,kind,objTabOff,objAddr,disp,stride,addr,width,sign,value,mnemonic
//     rw     R load / W store / P pointer (lea) / T object-table fetch
//     kind   OBJFETCH  ld.a out of the a9 object table (the first hop itself)
//            LITERAL   cal object + constant displacement  -> addr and value are exact
//            INDEXED   cal object + constant + runtime index*stride -> addr is the ARRAY BASE,
//                      value is empty. This is the population a regex cannot see.
//            ABS       absolute cal access built with movh.a/lea or an absolute-mode ld/st
//     value  read out of the image at addr for LITERAL/ABS only. NEVER guessed: if propagation
//            cannot pin the address the row says INDEXED and the value column stays empty.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ResolveCalReadsA9.java [out.csv] \
//       [--cal=0xLO:0xHI] [--table=0xLO:0xHI] [--seed=a9:0x80103464] [0xfuncAddr ...]
//
// Defaults are MED17.1.1 8R0907115N: cal 0x80380000..0x80400000, object table
// 0x80103464..0x80104390, seeds a0=a8=0xd000c420 a1=0x8002f298 a9=0x80103464 (ecu.conf BASEREGS).
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.scalar.Scalar;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

public class ResolveCalReadsA9 extends GhidraScript {

    // ---- configuration (all overridable on the command line) -------------------------------
    long calLo = 0x80380000L, calHi = 0x80400000L;      // ecu.conf CAL_LO/CAL_HI
    long tabLo = 0x80103464L, tabHi = 0x80104390L;      // the a9 cal-object table (971 pointers)
    long flashLo = 0x80000000L, flashHi = 0x80400000L;  // immutable => safe to fold loads from
    final Map<String, Long> seeds = new HashMap<>();

    // ---- abstract value ---------------------------------------------------------------------
    // val   = the constant part of the register (an absolute address when it is a pointer)
    // obj   = val is derived from a pointer fetched out of the a9 cal-object table
    // idx   = an unknown runtime term has been added, so val is the ARRAY BASE, not the address
    static final class V {
        static final V UNK = new V();
        boolean unk = true;
        long val, objAddr, tabOff = -1, stride;
        boolean obj, idx;

        static V c(long v) { V x = new V(); x.unk = false; x.val = v; return x; }
        static V object(long ptr, long off) {
            V x = c(ptr); x.obj = true; x.objAddr = ptr; x.tabOff = off; return x;
        }
        V plus(long d) {
            if (unk) return UNK;
            V x = new V();
            x.unk = false; x.val = val + d; x.obj = obj; x.objAddr = objAddr; x.tabOff = tabOff;
            x.idx = idx; x.stride = stride;
            return x;
        }
        V indexed(long s) {                       // add an unknown runtime term of stride s
            if (unk) return UNK;
            V x = plus(0);
            if (x.stride == 0) x.stride = s;      // keep the innermost (record) stride
            x.idx = true;
            return x;
        }
        boolean same(V o) {
            if (o == null) return false;
            if (unk || o.unk) return unk && o.unk;
            return val == o.val && obj == o.obj && objAddr == o.objAddr && tabOff == o.tabOff
                    && idx == o.idx && stride == o.stride;
        }
    }

    // register file: 0..15 = a0..a15, 16..31 = d0..d15
    static final int NR = 32;
    private static int ri(String n) {
        if (n.length() < 2) return -1;
        char k = n.charAt(0);
        if (k != 'a' && k != 'd') return -1;
        try { int i = Integer.parseInt(n.substring(1)); return (i < 0 || i > 15) ? -1 : (k == 'a' ? i : 16 + i); }
        catch (Exception e) { return -1; }
    }
    private static V[] copy(V[] s) { V[] t = new V[NR]; System.arraycopy(s, 0, t, 0, NR); return t; }
    private static boolean merge(V[] dst, V[] src) {          // returns true if dst changed
        boolean ch = false;
        for (int i = 0; i < NR; i++) {
            if (dst[i].same(src[i])) continue;
            if (!dst[i].unk) { dst[i] = V.UNK; ch = true; }
        }
        return ch;
    }

    // ---- counters --------------------------------------------------------------------------
    long nFunc, nIns, nMem, nObjFetch, nLiteral, nIndexed, nAbs, nUnresBase, nStackBase, nPtrLea;
    final Set<Long> objsSeen = new HashSet<>(), tabOffsSeen = new HashSet<>();
    final TreeMap<Long, Long> indexedArrays = new TreeMap<>();   // arrayBase -> stride

    private static long hex(String s) { return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16); }
    private boolean inCal(long a) { return a >= calLo && a < calHi; }
    private boolean inFlash(long a) { return a >= flashLo && a < flashHi; }

    @Override
    public void run() throws Exception {
        seeds.put("a0", 0xd000c420L); seeds.put("a1", 0x8002f298L);
        seeds.put("a8", 0xd000c420L); seeds.put("a9", 0x80103464L);

        String outPath = null;
        List<String> fsel = new ArrayList<>();
        for (String a : getScriptArgs()) {
            if (a.startsWith("--cal=")) { String[] p = a.substring(6).split(":"); calLo = hex(p[0]); calHi = hex(p[1]); }
            else if (a.startsWith("--table=")) { String[] p = a.substring(8).split(":"); tabLo = hex(p[0]); tabHi = hex(p[1]); }
            else if (a.startsWith("--seed=")) { String[] p = a.substring(7).split(":"); seeds.put(p[0], hex(p[1])); }
            else if (a.startsWith("0x")) fsel.add(a);
            else if (outPath == null) outPath = a;
        }
        println(String.format("ResolveCalReadsA9: cal 0x%08x..0x%08x  objtable 0x%08x..0x%08x",
                calLo, calHi, tabLo, tabHi));

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

        PrintWriter pw = (outPath != null) ? new PrintWriter(new FileWriter(outPath)) : new PrintWriter(System.out);
        pw.println("function,insaddr,rw,kind,objTabOff,objAddr,disp,stride,addr,width,sign,value,mnemonic");
        for (Function f : funcs) {
            if (monitor.isCancelled()) break;
            try { doFunction(f, pw); } catch (Exception e) { println("ERR " + f.getEntryPoint() + ": " + e); }
        }
        pw.flush();
        if (outPath != null) pw.close();

        println("A9CAL: functions=" + nFunc + " instructions=" + nIns);
        println("A9CAL: memory accesses seen=" + nMem
                + "  (base unresolved=" + nUnresBase + ", stack-relative=" + nStackBase + ")");
        println("A9CAL: OBJFETCH=" + nObjFetch + " over " + tabOffsSeen.size()
                + " distinct table offsets -> " + objsSeen.size() + " distinct cal objects");
        println("A9CAL: LITERAL=" + nLiteral + "  INDEXED=" + nIndexed + "  ABS=" + nAbs
                + "  (lea pointers included: " + nPtrLea + ")");
        println("A9CAL: distinct INDEXED array bases=" + indexedArrays.size());
        int shown = 0;
        for (Map.Entry<Long, Long> e : indexedArrays.entrySet()) {
            if (shown++ >= 400) { println("A9CAL-ARRAY: ... (truncated, see CSV)"); break; }
            println(String.format("A9CAL-ARRAY: 0x%08x stride=0x%x", e.getKey(), e.getValue()));
        }
        println("A9CALDONE -> " + (outPath != null ? outPath : "stdout"));
    }

    // ---------------------------------------------------------------------------------------
    private void doFunction(Function f, PrintWriter pw) throws Exception {
        List<Instruction> ins = new ArrayList<>();
        InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) ins.add(it.next());
        if (ins.isEmpty()) return;
        nFunc++; nIns += ins.size();

        Map<Address, Integer> idx = new HashMap<>();
        for (int i = 0; i < ins.size(); i++) idx.put(ins.get(i).getAddress(), i);

        V[][] in = new V[ins.size()][];
        V[] init = new V[NR];
        for (int i = 0; i < NR; i++) init[i] = V.UNK;
        for (Map.Entry<String, Long> e : seeds.entrySet()) {
            int r = ri(e.getKey());
            if (r >= 0) init[r] = V.c(e.getValue());
        }
        in[0] = init;

        // CFG fixpoint. The lattice is per-register {bottom, one value, top}, so merging two
        // different values goes straight to top and the iteration terminates.
        ArrayList<Integer> wl = new ArrayList<>();
        wl.add(0);
        long budget = 400L * ins.size() + 5000L;
        while (!wl.isEmpty() && budget-- > 0) {
            int i = wl.remove(wl.size() - 1);
            V[] st = transfer(in[i], ins.get(i));
            for (Address s : succs(ins.get(i), f)) {
                Integer j = idx.get(s);
                if (j == null) continue;
                if (in[j] == null) { in[j] = copy(st); wl.add(j); }
                else if (merge(in[j], st)) wl.add(j);
            }
        }

        String fname = f.getName() + "@" + f.getEntryPoint();
        for (int i = 0; i < ins.size(); i++)
            if (in[i] != null) emit(pw, fname, ins.get(i), in[i]);
    }

    private List<Address> succs(Instruction i, Function f) {
        List<Address> out = new ArrayList<>(3);
        if (!i.getFlowType().isTerminal()) {
            Address ft = i.getFallThrough();
            if (ft != null) out.add(ft);
        }
        if (!i.getFlowType().isCall())
            for (Address a : i.getFlows())
                if (f.getBody().contains(a)) out.add(a);
        return out;
    }

    // ---- abstract transfer ------------------------------------------------------------------
    private V[] transfer(V[] s0, Instruction i) {
        V[] s = copy(s0);
        String mn = i.getMnemonicString().toLowerCase();

        // A CALL preserves the TriCore upper context (a10-a15, d8-d15) and the global address
        // registers a0/a1/a8/a9; the lower context (a2-a7, d0-d7) is scratch.
        if (i.getFlowType().isCall()) {
            for (int r = 2; r <= 7; r++) { s[r] = V.UNK; s[16 + r] = V.UNK; }
            for (int r = 0; r <= 7; r++) s[16 + r] = V.UNK;
            return s;
        }

        int d = dstReg(i);
        V nv = null;
        boolean modelled = true;

        switch (mn) {
            case "mov.aa": case "mov.a": case "mov.d": case "mov": case "mov.u": {
                Object o = srcObj(i, 1);
                if (o instanceof Register) nv = get(s, (Register) o);
                else if (o instanceof Scalar) nv = V.c(((Scalar) o).getSignedValue());
                else modelled = false;
                break;
            }
            case "movh.a": case "movh": {
                Scalar sc = scalarOf(i, 1);
                nv = (sc != null) ? V.c((sc.getUnsignedValue() & 0xffffL) << 16) : null;
                if (nv == null) modelled = false;
                break;
            }
            case "addih.a": case "addih": {
                V b = regVal(s, i, 1); Scalar sc = scalarOf(i, i.getNumOperands() - 1);
                nv = (b != null && sc != null) ? b.plus((sc.getUnsignedValue() & 0xffffL) << 16) : null;
                if (nv == null) modelled = false;
                break;
            }
            case "lea": {
                int mo = memOperand(i);
                if (mo == -2) { modelled = false; break; }
                if (mo < 0) { Scalar sc = scalarOf(i, 1); nv = (sc != null) ? V.c(sc.getUnsignedValue()) : null; if (nv == null) modelled = false; break; }
                Register b = regIn(i, mo);
                long disp = dispIn(i, mo);
                if (b == null) nv = V.c(disp);
                else nv = get(s, b).plus(disp);
                break;
            }
            case "add.a": case "sub.a": case "add": case "addi": case "adds": case "sub": case "subs": {
                boolean neg = mn.startsWith("sub");
                if (i.getNumOperands() == 2) {                       // dst op= src
                    V b = get(s, i, 0);
                    Object o = srcObj(i, 1);
                    if (o instanceof Scalar) nv = b.plus(neg ? -((Scalar) o).getSignedValue() : ((Scalar) o).getSignedValue());
                    else if (o instanceof Register) nv = combine(b, get(s, (Register) o), neg);
                    else modelled = false;
                } else if (i.getNumOperands() >= 3) {
                    V a = regVal(s, i, 1);
                    Object o = srcObj(i, 2);
                    if (a == null) { modelled = false; break; }
                    if (o instanceof Scalar) nv = a.plus(neg ? -((Scalar) o).getSignedValue() : ((Scalar) o).getSignedValue());
                    else if (o instanceof Register) nv = combine(a, get(s, (Register) o), neg);
                    else modelled = false;
                } else modelled = false;
                break;
            }
            case "addsc.a": case "addsc.at": {
                // a[c] = a[b] + (d[a] << n)   (addsc.at: + (d[a] & ~3))
                V b = regVal(s, i, 1);
                V ix = regVal(s, i, 2);
                Scalar sc = scalarOf(i, i.getNumOperands() - 1);
                long n = (sc != null && mn.equals("addsc.a")) ? sc.getUnsignedValue() : 0;
                if (b == null) { modelled = false; break; }
                if (ix != null && !ix.unk && !ix.obj && !ix.idx) nv = b.plus(ix.val << n);
                else nv = b.indexed(1L << n);
                break;
            }
            case "madd": case "madds": case "msub": case "msubs": {
                // d[c] = d[a] +/- (d[b] * const9)  -- how this ECU indexes arrays of records
                V a = regVal(s, i, 1);
                V b = regVal(s, i, 2);
                Scalar sc = scalarOf(i, 3);
                if (a == null || sc == null) { modelled = false; break; }
                long k = sc.getSignedValue();
                if (b != null && !b.unk && !b.obj && !b.idx) nv = a.plus(mn.startsWith("msub") ? -b.val * k : b.val * k);
                else nv = a.indexed(Math.abs(k));
                break;
            }
            default:
                modelled = false;
        }

        if (mn.startsWith("ld.")) {                       // possible pointer fetch
            nv = loadValue(s, i, mn);
            modelled = (nv != null);
        }

        if (modelled && d >= 0) { s[d] = (nv == null) ? V.UNK : nv; killPair(s, i, d); return s; }

        // Anything not modelled: every register the instruction writes becomes unknown.
        for (Object o : i.getResultObjects())
            if (o instanceof Register) killReg(s, (Register) o);
        return s;
    }

    private V combine(V a, V b, boolean neg) {
        if (a == null || b == null) return V.UNK;
        if (!b.unk && !b.obj && !b.idx) return a.plus(neg ? -b.val : b.val);
        if (!a.unk && !a.obj && !a.idx && !neg) return b.plus(a.val);
        if (!a.unk) return a.indexed(1);                 // known base + unknown term
        return V.UNK;
    }

    // ld.* -- fold ONLY pointer-width loads and ONLY out of flash. Flash is immutable so the
    // fold is sound; folding a RAM load would silently substitute a power-on value for a
    // variable the firmware writes at runtime (the same trap ecu.conf warns about for .data).
    private V loadValue(V[] s, Instruction i, String mn) {
        long[] ea = effAddr(s, i);
        if (ea == null || ea[1] != 0) return V.UNK;       // no base / indexed => unknown value
        long a = ea[0];
        if (!(mn.equals("ld.a") || mn.equals("ld.w"))) return V.UNK;
        if (!inFlash(a) || (a & 3) != 0) return V.UNK;
        try {
            long p = currentProgram.getMemory().getInt(toAddr(a)) & 0xffffffffL;
            if (a >= tabLo && a < tabHi) return V.object(p, a - tabLo);
            return V.c(p);
        } catch (Exception e) { return V.UNK; }
    }

    // ---- emission ---------------------------------------------------------------------------
    private void emit(PrintWriter pw, String fname, Instruction i, V[] s) {
        String mn = i.getMnemonicString().toLowerCase();
        boolean isLd = mn.startsWith("ld."), isSt = mn.startsWith("st.") || mn.equals("ldmst")
                || mn.startsWith("swap") || mn.startsWith("cmpswap");
        boolean isLea = mn.equals("lea");
        if (!isLd && !isSt && !isLea) return;

        int mo = memOperand(i);
        if (mo == -2) return;                             // auto-increment mode: not modelled
        Register base = (mo >= 0) ? regIn(i, mo) : null;
        long disp = (mo >= 0) ? dispIn(i, mo) : 0;
        V bv;
        if (mo < 0) {                                     // absolute-addressing form (ld.bu d,0x...)
            Long abs = absOperand(i, isSt);
            if (abs == null) return;
            bv = V.c(abs); disp = 0;
        } else if (base == null) {
            bv = V.c(disp); disp = 0;
        } else {
            bv = get(s, base);
        }

        if (isLd || isSt) {
            nMem++;
            if (bv.unk) { if (base != null && base.getName().equals("a10")) nStackBase++; else nUnresBase++; return; }
            if (base != null && base.getName().equals("a10")) { nStackBase++; return; }
        } else if (bv.unk) return;

        char rw = isLea ? 'P' : (isLd ? 'R' : 'W');
        int[] ws = widthSign(mn);
        String wcol = (ws[0] > 0) ? String.valueOf(ws[0]) : "";
        String scol = (ws[1] == 1) ? "S" : (ws[1] == 0 ? "U" : "");

        if (bv.obj) {
            long arrayBase = bv.val + disp;
            long off = arrayBase - bv.objAddr;
            if (!bv.idx) {
                // OBJFETCH rows: the ld.a out of the table itself is reported separately below.
                nLiteral++;
                if (isLea) nPtrLea++;
                String val = (isLd || isLea) ? readVal(arrayBase, ws[0], ws[1]) : "";
                pw.println(String.format("%s,%s,%c,LITERAL,0x%x,0x%08x,0x%x,,0x%08x,%s,%s,%s,%s",
                        fname, i.getAddress(), rw, bv.tabOff, bv.objAddr, off, arrayBase, wcol, scol, val, mn));
            } else {
                nIndexed++;
                if (isLea) nPtrLea++;
                indexedArrays.put(arrayBase, bv.stride);
                pw.println(String.format("%s,%s,%c,INDEXED,0x%x,0x%08x,0x%x,0x%x,0x%08x,%s,%s,,%s",
                        fname, i.getAddress(), rw, bv.tabOff, bv.objAddr, off, bv.stride, arrayBase, wcol, scol, mn));
            }
            return;
        }

        long eff = bv.val + disp;
        if (bv.idx) {                                     // computed, but not object-table based
            if (inCal(eff)) {
                nIndexed++;
                indexedArrays.put(eff, bv.stride);
                pw.println(String.format("%s,%s,%c,INDEXED,,,,0x%x,0x%08x,%s,%s,,%s",
                        fname, i.getAddress(), rw, bv.stride, eff, wcol, scol, mn));
            }
            return;
        }
        if (inCal(eff)) {
            nAbs++;
            if (isLea) nPtrLea++;
            String val = (isLd || isLea) ? readVal(eff, ws[0], ws[1]) : "";
            pw.println(String.format("%s,%s,%c,ABS,,,,,0x%08x,%s,%s,%s,%s",
                    fname, i.getAddress(), rw, eff, wcol, scol, val, mn));
        }
        // the object-table fetch itself
        if (mn.equals("ld.a") && eff >= tabLo && eff < tabHi) {
            try {
                long p = currentProgram.getMemory().getInt(toAddr(eff)) & 0xffffffffL;
                nObjFetch++; objsSeen.add(p); tabOffsSeen.add(eff - tabLo);
                pw.println(String.format("%s,%s,T,OBJFETCH,0x%x,0x%08x,,,0x%08x,4,,,%s",
                        fname, i.getAddress(), eff - tabLo, p, eff, mn));
            } catch (Exception e) { /* unreadable */ }
        }
    }

    private String readVal(long addr, int w, int sign) {
        if (w <= 0 || w > 4 || !inFlash(addr)) return "";
        try {
            Memory m = currentProgram.getMemory();
            Address a = toAddr(addr);
            long v;
            if (w == 1) v = m.getByte(a) & 0xffL;
            else if (w == 2) v = m.getShort(a) & 0xffffL;
            else v = m.getInt(a) & 0xffffffffL;
            if (sign == 1) {                              // sign-extend
                long msb = 1L << (w * 8 - 1);
                if ((v & msb) != 0) v -= (msb << 1);
            }
            return String.valueOf(v);
        } catch (Exception e) { return ""; }
    }

    // width in bytes, signedness (1 signed, 0 unsigned, -1 n/a)
    private int[] widthSign(String mn) {
        String t = mn.startsWith("ld.") || mn.startsWith("st.") ? mn.substring(3) : "";
        switch (t) {
            case "b":  return new int[]{1, 1};
            case "bu": return new int[]{1, 0};
            case "h":  return new int[]{2, 1};
            case "hu": return new int[]{2, 0};
            case "q":  return new int[]{2, 1};
            case "w":  return new int[]{4, 1};
            case "a":  return new int[]{4, 0};
            case "d": case "da": return new int[]{8, -1};
            case "t":  return new int[]{1, 0};
            default:   return new int[]{0, -1};
        }
    }

    // ---- operand helpers --------------------------------------------------------------------
    private int memOperand(Instruction i) {
        for (int op = 0; op < i.getNumOperands(); op++) {
            String r = i.getDefaultOperandRepresentation(op);
            if (r != null && r.indexOf('[') >= 0) {
                if (r.indexOf("+]") >= 0 || r.indexOf("[+") >= 0) return -2;   // auto-inc: don't model
                return op;
            }
        }
        return -1;
    }
    private Register regIn(Instruction i, int op) {
        if (op < 0) return null;
        for (Object o : i.getOpObjects(op))
            if (o instanceof Register && ((Register) o).getName().matches("a\\d+")) return (Register) o;
        return null;
    }
    private long dispIn(Instruction i, int op) {
        if (op < 0) return 0;
        for (Object o : i.getOpObjects(op))
            if (o instanceof Scalar) return ((Scalar) o).getSignedValue();
        if (regIn(i, op) != null) return 0;               // [aB] with no displacement
        for (Object o : i.getOpObjects(op))               // absolute address rendered as Address
            if (o instanceof Address) return ((Address) o).getOffset();
        return 0;
    }

    // Effective address of the memory operand under state s: {addr, indexedFlag}, null if the
    // base register does not resolve (or the addressing mode is not modelled).
    private long[] effAddr(V[] s, Instruction i) {
        int mo = memOperand(i);
        if (mo == -2) return null;
        if (mo < 0) {
            Long abs = absOperand(i, false);
            return (abs == null) ? null : new long[]{abs, 0};
        }
        Register b = regIn(i, mo);
        long disp = dispIn(i, mo);
        if (b == null) return new long[]{disp, 0};
        V bv = get(s, b);
        if (bv.unk) return null;
        return new long[]{bv.val + disp, bv.idx ? 1 : 0};
    }
    private Long absOperand(Instruction i, boolean store) {
        int lo = store ? 0 : 1, hi = store ? 0 : i.getNumOperands() - 1;
        for (int op = lo; op <= hi && op < i.getNumOperands(); op++) {
            if (regIn(i, op) != null) continue;
            for (Object o : i.getOpObjects(op)) {
                if (o instanceof Address) return ((Address) o).getOffset();
                if (o instanceof Scalar) return ((Scalar) o).getUnsignedValue();
            }
        }
        return null;
    }
    private int dstReg(Instruction i) {
        if (i.getNumOperands() == 0) return -1;
        Object[] o = i.getOpObjects(0);
        if (o.length == 1 && o[0] instanceof Register) return ri(((Register) o[0]).getName());
        return -1;
    }
    private Object srcObj(Instruction i, int op) {
        if (op >= i.getNumOperands()) return null;
        Object[] o = i.getOpObjects(op);
        return (o.length == 1) ? o[0] : null;
    }
    private Scalar scalarOf(Instruction i, int op) {
        if (op < 0 || op >= i.getNumOperands()) return null;
        for (Object o : i.getOpObjects(op)) if (o instanceof Scalar) return (Scalar) o;
        return null;
    }
    private V regVal(V[] s, Instruction i, int op) {
        Object o = srcObj(i, op);
        return (o instanceof Register) ? get(s, (Register) o) : null;
    }
    private V get(V[] s, Register r) { int k = ri(r.getName()); return (k < 0) ? V.UNK : s[k]; }
    private V get(V[] s, Instruction i, int op) {
        Object o = srcObj(i, op);
        return (o instanceof Register) ? get(s, (Register) o) : V.UNK;
    }
    private void killReg(V[] s, Register r) {
        int k = ri(r.getName());
        if (k >= 0) { s[k] = V.UNK; return; }
        for (Register c : r.getChildRegisters()) {        // register pairs (e0/e2, a-pairs)
            int j = ri(c.getName());
            if (j >= 0) s[j] = V.UNK;
        }
    }
    // a modelled instruction may still write a second register (e.g. the odd half of a pair)
    private void killPair(V[] s, Instruction i, int keep) {
        for (Object o : i.getResultObjects()) {
            if (!(o instanceof Register)) continue;
            Register r = (Register) o;
            int k = ri(r.getName());
            if (k >= 0) { if (k != keep) s[k] = V.UNK; }
            else for (Register c : r.getChildRegisters()) {
                int j = ri(c.getName());
                if (j >= 0 && j != keep) s[j] = V.UNK;
            }
        }
    }
}
