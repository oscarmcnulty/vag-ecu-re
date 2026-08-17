// Find every instruction whose *effective address* falls in a target window, whether the
// address is built as "lea aX,[a0]off" + "st.b [aX]#disp" (a base+displacement pair that
// Ghidra's reference model does not attribute to the final target) or encoded directly in
// the instruction (TriCore ABS/ABSB format: `ld.bu d15,0xd000017a`, `st.b 0xd0002238,d15`,
// `st.t 0xd0000074,#0x6,#0x1`).
//
// WHY. FindRefsTo only sees refs Ghidra created. A store through a struct/array base
// (lea to the base, then a displaced st.b) leaves no reference on the target byte, so a
// backwards trace of "who writes this RAM byte?" comes up empty even though the writer is
// fully disassembled. This does a linear, per-function constant-propagation of the address
// registers (seeded with the known base registers) and reports every computed EA in range.
//
// 2026-08 FIX -- three defects, all of which produced WRONG NEGATIVES/POSITIVES:
//   (a) ABSOLUTE-MODE BLIND SPOT. Only base+disp forms were modelled, so every ABS-format
//       access was invisible. 0xd00000e0 reported ZERO writers while the decompiled C shows
//       sixteen functions writing it (all via `st.t 0xd00000e0,#n,#v`). TriCore ABS encodes
//       EA = {off18[17:14], 14'b0, off18[13:0]}, i.e. ABS can only reach the low 16 KB of
//       each 256 MB segment -- so this blind spot hit exactly 0xd0000000..0xd0003fff of RAM,
//       which is where this ECU keeps its bit-flag globals. Forms present in this image
//       (enumerated, not assumed): ld.{a,b,bu,h,hu,w} dN,ABS / st.{a,b,d,h,w} ABS,rN /
//       st.t ABS,#bit,#val / lea aN,ABS.
//   (b) INDEXED FALSE POSITIVE. The old code reported the *arithmetic* site (`addsc.a`) as a
//       hit whenever the base register was near the window. The RAM jump-table dispatchers
//       FUN_8001e2c0 / FUN_8001e522 do `movh.a a15,#0xd000; addsc.a a15,a15,d15,#2;
//       ld.a a15,[a15]0x4980; ji a15` -- base 0xd0000000, so every query in
//       0xd0000000..0xd00001ff got two bogus INDEXED hits. Fixed by RESOLVING the
//       displacement: the index flag now rides on the register and INDEXED is reported at
//       the MEMORY OPERAND (EA = 0xd0000000 + 0x4980 = the real table 0xd0004980), not at
//       the addsc.a. Cost: an indexed pointer that escapes into a call without a modelled
//       access is now only reported by the a4..a7 argument check below.
//   (c) ACCESS WIDTH / CALL CLOBBER. A hit is now reported when [EA, EA+width) *intersects*
//       the window (an `st.w 0xd0005e34` writes 0xd0005e37 too), and a2..a7 are invalidated
//       across a call (TriCore saves only the UPPER context A10-A15/D8-D15; A0/A1/A8/A9 are
//       global). Both directions of correctness: (c1) finds writers the old tool missed,
//       (c2) removes EAs propagated through a call that cannot survive it.
//
// KINDS (new `kind=` column; everything else in the line is unchanged):
//   ABS   address is in the instruction -- exact, no propagation involved. Strongest evidence.
//   BASE  base register + displacement, base fully resolved. Exact modulo the linear scan.
//   IDX   as BASE but the base carries an unknown runtime index (addsc.a/add.a/sub.a), so the
//         printed EA is the *element-0* address; the access MAY reach the window.
//   ADDR  not an access: an in-window address was formed (lea) or passed in an argument
//         register at a call. Suppressed by storesOnly.
//
//   analyzeHeadless <proj> <name> -process -noanalysis -postScript \
//       FindEffectiveAddr.java <lo> <hi> [storesOnly:true|false] [idxSlack:0x400]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class FindEffectiveAddr extends GhidraScript {

    // seeded base registers (ecus/med17/ecu.conf BASEREGS)
    static final long[] SEED = new long[16];
    static { for (int i=0;i<16;i++) SEED[i]=Long.MIN_VALUE;
             SEED[0]=0xd000c420L; SEED[8]=0xd000c420L; SEED[1]=0x8002f298L; SEED[9]=0x80103464L; }

    static final long UNK = Long.MIN_VALUE;

    static final Pattern LEA   = Pattern.compile("^lea a(\\d+),\\[a(\\d+)\\](#?([+-]?(?:0x)?[0-9a-fA-F]+))?$");
    static final Pattern LEAABS= Pattern.compile("^lea a(\\d+),(0x[0-9a-fA-F]+)$");
    static final Pattern MOVHA = Pattern.compile("^movh\\.a a(\\d+),#([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern ADDIHA= Pattern.compile("^addih\\.a a(\\d+),a(\\d+),#([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVAA = Pattern.compile("^mov\\.aa a(\\d+),a(\\d+)$");
    static final Pattern ADDAI = Pattern.compile("^(add|sub)\\.a a(\\d+),#([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MEM   = Pattern.compile("\\[a(\\d+)([+-]?)\\](#?([+-]?(?:0x)?[0-9a-fA-F]+))?");
    static final Pattern DEFA  = Pattern.compile("^[a-z0-9._]+ a(\\d+),");
    // indexed address arithmetic: the only way to reach a byte whose address is never
    // formed as a constant is base + runtime index. addsc.a aD,aB,dI,#n / add.a aD,aA,aB.
    static final Pattern IDXSC = Pattern.compile("^(addsc\\.a|addsc\\.at) a(\\d+),a(\\d+),");
    static final Pattern IDXRR = Pattern.compile("^(add|sub)\\.a a(\\d+),a(\\d+),a(\\d+)$");

    // ABS-format memory mnemonics actually present in this image (see header note (a)).
    static final Set<String> ABS_LD = new HashSet<>(Arrays.asList(
            "ld.a","ld.b","ld.bu","ld.d","ld.da","ld.h","ld.hu","ld.q","ld.w"));
    static final Set<String> ABS_ST = new HashSet<>(Arrays.asList(
            "st.a","st.b","st.d","st.da","st.h","st.q","st.w","st.t"));
    static final Pattern BAREHEX = Pattern.compile("^0x[0-9a-fA-F]+$");

    static long parse(String s) {
        if (s.startsWith("#")) s = s.substring(1);
        boolean neg = s.startsWith("-");
        if (neg || s.startsWith("+")) s = s.substring(1);
        long v = s.startsWith("0x")||s.startsWith("0X") ? Long.parseLong(s.substring(2),16)
                                                        : Long.parseLong(s,10);
        return neg ? -v : v;
    }

    /** bytes touched by an access, from its mnemonic. Used for window INTERSECTION. */
    static int width(String mn) {
        if (mn.endsWith(".b") || mn.endsWith(".bu") || mn.equals("st.t") || mn.equals("ld.t")) return 1;
        if (mn.endsWith(".h") || mn.endsWith(".hu") || mn.endsWith(".q")) return 2;
        if (mn.endsWith(".d") || mn.endsWith(".da")) return 8;
        return 4;   // .w .a ldmst swap.w cmpswap.w
    }

    static boolean isStore(String mn) {
        return mn.startsWith("st") || mn.startsWith("swap")
            || mn.startsWith("ldmst") || mn.startsWith("cmpswap");
    }

    private long lo, hi, slack;
    private boolean storesOnly;
    private int nhit = 0;

    private boolean hits(long ea, int w) {
        return ea <= hi && ea + w - 1 >= lo;
    }

    private void emit(Instruction in, long ea, String acc, String kind, String t,
                      String base, long disp, Function fn) {
        println(String.format("  %s  EA=%08x  %-5s kind=%-4s %-38s  base=%-14s disp=%d  fn=%s@%s",
                in.getAddress(), ea, acc, kind, t, base, disp, fn.getName(), fn.getEntryPoint()));
        nhit++;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        lo = Long.decode(args[0]); hi = Long.decode(args[1]);
        storesOnly = args.length < 3 || Boolean.parseBoolean(args[2]);
        slack = args.length > 3 ? Long.decode(args[3]) : 0x400L;

        int nf = 0;
        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        while (fit.hasNext()) {
            Function fn = fit.next();
            nf++;
            long[] reg = SEED.clone();
            boolean[] idx = new boolean[16];
            InstructionIterator it = currentProgram.getListing()
                    .getInstructions(fn.getBody(), true);
            while (it.hasNext()) {
                Instruction in = it.next();
                String t = in.toString().trim();
                String mn = in.getMnemonicString();
                boolean store = isStore(mn);
                int w = width(mn);

                // ---------- (1) ABSOLUTE-mode access: address is IN the instruction ----------
                if (!t.contains("[")) {
                    boolean absMem = ABS_LD.contains(mn) || ABS_ST.contains(mn);
                    boolean absLea = mn.equals("lea");
                    if (absMem || absLea) {
                        int sp = t.indexOf(' ');
                        long ea = UNK;
                        if (sp > 0) for (String o : t.substring(sp + 1).split(",")) {
                            o = o.trim();
                            if (BAREHEX.matcher(o).matches()) { ea = parse(o); break; }
                        }
                        if (ea != UNK && hits(ea, absLea ? 1 : w)) {
                            // st.t is a read-modify-write of one bit -> a WRITE.
                            if (absLea) { if (!storesOnly) emit(in, ea, "lea", "ADDR", t, "abs", 0, fn); }
                            else if (!storesOnly || store) emit(in, ea, store?"WRITE":"read", "ABS", t, "abs", 0, fn);
                        }
                    }
                }

                // ---------- (2) base register + displacement (resolved or indexed) ----------
                Matcher m = MEM.matcher(t);
                if (m.find()) {
                    int b = Integer.parseInt(m.group(1));
                    if (reg[b] != UNK) {
                        long disp = m.group(4) == null ? 0 : parse(m.group(4));
                        long ea = (reg[b] + disp) & 0xffffffffL;
                        boolean lea = mn.equals("lea");
                        String kind = lea ? "ADDR" : (idx[b] ? "IDX" : "BASE");
                        // An indexed access reaches base+disp+k*scale for unknown k, so accept a
                        // window that starts a little above the element-0 address.
                        boolean inWin = idx[b] && !lea
                                ? (ea <= hi && ea + w - 1 >= lo - slack)
                                : hits(ea, lea ? 1 : w);
                        if (inWin) {
                            String acc = lea ? "lea" : (store ? "WRITE" : "read");
                            if (!storesOnly || store)
                                emit(in, ea, acc, kind, t, String.format("a%d(%08x)", b, reg[b]), disp, fn);
                        }
                    }
                }

                // ---------- (3) in-window pointer handed to a callee in an argument register ----
                if (!storesOnly && (mn.startsWith("call") || mn.equals("fcall") || mn.equals("fcalla"))) {
                    for (int a = 4; a <= 7; a++)
                        if (reg[a] != UNK && reg[a] >= lo && reg[a] <= hi)
                            emit(in, reg[a], "arg", "ADDR", t, String.format("a%d(%08x)", a, reg[a]), 0, fn);
                }

                // ---------- (4) update address-register state ----------
                Matcher l = LEA.matcher(t);
                if (l.matches()) {
                    int da = Integer.parseInt(l.group(1)), sa = Integer.parseInt(l.group(2));
                    long d = l.group(4) == null ? 0 : parse(l.group(4));
                    boolean si = idx[sa];
                    reg[da] = reg[sa]==UNK ? UNK : (reg[sa] + d) & 0xffffffffL;
                    idx[da] = reg[da]==UNK ? false : si;
                    continue;
                }
                Matcher la = LEAABS.matcher(t);
                if (la.matches()) {   // TriCore ABS-format LEA: aD = the encoded address itself
                    int da = Integer.parseInt(la.group(1));
                    reg[da] = parse(la.group(2)); idx[da] = false; continue;
                }
                Matcher h = MOVHA.matcher(t);
                if (h.matches()) {
                    int da = Integer.parseInt(h.group(1));
                    reg[da] = (parse(h.group(2))<<16)&0xffffffffL; idx[da] = false; continue;
                }
                Matcher ah = ADDIHA.matcher(t);
                if (ah.matches()) {
                    int da = Integer.parseInt(ah.group(1)), sa = Integer.parseInt(ah.group(2));
                    reg[da] = reg[sa]==UNK ? UNK : (reg[sa] + ((parse(ah.group(3))<<16)&0xffffffffL)) & 0xffffffffL;
                    idx[da] = reg[da]==UNK ? false : idx[sa];
                    continue;
                }
                Matcher c = MOVAA.matcher(t);
                if (c.matches()) {
                    int da = Integer.parseInt(c.group(1)), sa = Integer.parseInt(c.group(2));
                    reg[da] = reg[sa]; idx[da] = idx[sa]; continue;
                }
                Matcher ai = ADDAI.matcher(t);      // add.a aN,#imm / sub.a aN,#imm  (SRC form)
                if (ai.matches()) {
                    int da = Integer.parseInt(ai.group(2));
                    long d = parse(ai.group(3));
                    if (ai.group(1).equals("sub")) d = -d;
                    if (reg[da] != UNK) reg[da] = (reg[da] + d) & 0xffffffffL;
                    continue;
                }
                Matcher isc = IDXSC.matcher(t);     // addsc.a aD,aB,dI,#n -- unknown index
                if (isc.find()) {
                    int da = Integer.parseInt(isc.group(2)), sb = Integer.parseInt(isc.group(3));
                    reg[da] = reg[sb]; idx[da] = reg[sb] != UNK;
                    continue;
                }
                Matcher irr = IDXRR.matcher(t);     // add.a aD,aA,aB / sub.a aD,aA,aB
                if (irr.matches()) {
                    int da = Integer.parseInt(irr.group(2));
                    int sa = Integer.parseInt(irr.group(3)), sb = Integer.parseInt(irr.group(4));
                    if (reg[sa] != UNK && reg[sb] != UNK && irr.group(1).equals("add")) {
                        reg[da] = (reg[sa] + reg[sb]) & 0xffffffffL; idx[da] = idx[sa] || idx[sb];
                    } else if (reg[sa] != UNK) { reg[da] = reg[sa]; idx[da] = true; }
                    else if (reg[sb] != UNK && irr.group(1).equals("add")) { reg[da] = reg[sb]; idx[da] = true; }
                    else { reg[da] = UNK; idx[da] = false; }
                    continue;
                }
                // post-increment base kills the base register
                Matcher pm = MEM.matcher(t);
                while (pm.find()) if ("+".equals(pm.group(2))) {
                    int b = Integer.parseInt(pm.group(1)); reg[b] = UNK; idx[b] = false;
                }
                // TriCore CALL saves only the UPPER context (A10-A15, D8-D15); A0/A1/A8/A9 are
                // global. The lower-context address registers A2-A7 do NOT survive the call.
                if (mn.startsWith("call") || mn.equals("fcall") || mn.equals("fcalla")) {
                    for (int a = 2; a <= 7; a++) { reg[a] = UNK; idx[a] = false; }
                }
                // any other instruction whose first operand is an address register clobbers it
                Matcher dfa = DEFA.matcher(t);
                if (dfa.find() && !mn.startsWith("st") && !mn.startsWith("jn") && !mn.startsWith("jz")
                        && !mn.startsWith("jeq") && !mn.startsWith("jne") && !mn.startsWith("call")) {
                    int b = Integer.parseInt(dfa.group(1)); reg[b] = UNK; idx[b] = false;
                }
            }
        }
        println("scanned " + nf + " functions; hits=" + nhit);
    }
}
