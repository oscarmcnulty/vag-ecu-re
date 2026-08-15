// Find every instruction whose *effective address* falls in a target window, including
// accesses built as "lea aX,[a0]off" + "st.b [aX]#disp" (a base+displacement pair that
// Ghidra's reference model does not attribute to the final target).
//
// WHY. FindRefsTo only sees refs Ghidra created. A store through a struct/array base
// (lea to the base, then a displaced st.b) leaves no reference on the target byte, so a
// backwards trace of "who writes this RAM byte?" comes up empty even though the writer is
// fully disassembled. This does a linear, per-function constant-propagation of the address
// registers (seeded with the known base registers) and reports every computed EA in range.
//
//   analyzeHeadless <proj> <name> -process -noanalysis -postScript \
//       FindEffectiveAddr.java <lo> <hi> [storesOnly:true|false]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class FindEffectiveAddr extends GhidraScript {

    // seeded base registers (ecus/med17/ecu.conf BASEREGS)
    static final long[] SEED = new long[16];
    static { for (int i=0;i<16;i++) SEED[i]=Long.MIN_VALUE;
             SEED[0]=0xd000c420L; SEED[8]=0xd000c420L; SEED[1]=0x8002f298L; SEED[9]=0x80103464L; }

    static final Pattern LEA   = Pattern.compile("^lea a(\\d+),\\[a(\\d+)\\]([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVHA = Pattern.compile("^movh\\.a a(\\d+),#?([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVAA = Pattern.compile("^mov\\.aa a(\\d+),a(\\d+)$");
    static final Pattern MEM   = Pattern.compile("\\[a(\\d+)([+-]?)\\](#?([+-]?(?:0x)?[0-9a-fA-F]+))?");
    static final Pattern DEFA  = Pattern.compile("^[a-z0-9._]+ a(\\d+),");
    // indexed address arithmetic: the only way to reach a byte whose address is never
    // formed as a constant is base + runtime index.
    static final Pattern IDX   = Pattern.compile("^(addsc\\.a|addsc\\.at|add\\.a|sub\\.a) a(\\d+),a(\\d+),");

    static long parse(String s) {
        boolean neg = s.startsWith("-");
        if (neg || s.startsWith("+")) s = s.substring(1);
        long v = s.startsWith("0x")||s.startsWith("0X") ? Long.parseLong(s.substring(2),16)
                                                        : Long.parseLong(s,10);
        return neg ? -v : v;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        long lo = Long.decode(args[0]), hi = Long.decode(args[1]);
        boolean storesOnly = args.length < 3 || Boolean.parseBoolean(args[2]);

        int nf = 0, nhit = 0;
        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        while (fit.hasNext()) {
            Function fn = fit.next();
            nf++;
            long[] reg = SEED.clone();
            InstructionIterator it = currentProgram.getListing()
                    .getInstructions(fn.getBody(), true);
            while (it.hasNext()) {
                Instruction in = it.next();
                String t = in.toString().trim();
                String mn = in.getMnemonicString();

                // --- report memory operands whose EA we can resolve ---
                Matcher m = MEM.matcher(t);
                if (m.find()) {
                    int b = Integer.parseInt(m.group(1));
                    if (reg[b] != Long.MIN_VALUE) {
                        long disp = m.group(4) == null ? 0 : parse(m.group(4));
                        long ea = reg[b] + disp;
                        boolean isStore = mn.startsWith("st") || mn.startsWith("swap")
                                       || mn.startsWith("ldmst") || mn.startsWith("cmpswap");
                        if (ea >= lo && ea <= hi && (!storesOnly || isStore)) {
                            println(String.format("  %s  EA=%08x  %-6s %-38s  base=a%d(%08x) disp=%d  fn=%s@%s",
                                    in.getAddress(), ea, isStore?"WRITE":"read", t, b, reg[b], disp,
                                    fn.getName(), fn.getEntryPoint()));
                            nhit++;
                        }
                    }
                }

                // --- indexed arithmetic off a base that lies in the window ---
                Matcher ix = IDX.matcher(t);
                if (ix.find()) {
                    int sb = Integer.parseInt(ix.group(3));
                    if (reg[sb] != Long.MIN_VALUE && reg[sb] >= lo - 0x400 && reg[sb] <= hi) {
                        println(String.format("  %s  INDEXED base=a%d(%08x)  %-38s  fn=%s@%s",
                                in.getAddress(), sb, reg[sb], t, fn.getName(), fn.getEntryPoint()));
                        nhit++;
                    }
                }

                // --- update address-register state ---
                Matcher l = LEA.matcher(t);
                if (l.matches()) {
                    int da = Integer.parseInt(l.group(1)), sa = Integer.parseInt(l.group(2));
                    reg[da] = reg[sa]==Long.MIN_VALUE ? Long.MIN_VALUE
                            : (reg[sa] + parse(l.group(3))) & 0xffffffffL;
                    continue;
                }
                Matcher h = MOVHA.matcher(t);
                if (h.matches()) { reg[Integer.parseInt(h.group(1))] = (parse(h.group(2))<<16)&0xffffffffL; continue; }
                Matcher c = MOVAA.matcher(t);
                if (c.matches()) { reg[Integer.parseInt(c.group(1))] = reg[Integer.parseInt(c.group(2))]; continue; }
                // post-increment base kills the base register
                Matcher pm = MEM.matcher(t);
                while (pm.find()) if ("+".equals(pm.group(2))) reg[Integer.parseInt(pm.group(1))] = Long.MIN_VALUE;
                // any other instruction whose first operand is an address register clobbers it
                Matcher dfa = DEFA.matcher(t);
                if (dfa.find() && !mn.startsWith("st") && !mn.startsWith("jn") && !mn.startsWith("jz")
                        && !mn.startsWith("jeq") && !mn.startsWith("jne") && !mn.startsWith("call")) {
                    reg[Integer.parseInt(dfa.group(1))] = Long.MIN_VALUE;
                }
            }
        }
        println("scanned " + nf + " functions; hits=" + nhit);
    }
}
