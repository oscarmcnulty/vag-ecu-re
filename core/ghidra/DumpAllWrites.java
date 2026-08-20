// Dump EVERY resolvable effective-address WRITE into the RAM window, for the whole image,
// in ONE headless pass, to a CSV file.
//
// WHY. Classifying the 133 COM signal-descriptor GROUPS as RX or TX by signal *geometry*
// (which bits look like a counter/CRC, etc.) has produced wrong answers. The objective test
// is WHO WRITES the group's RAM targets:
//   - written by the RX timeout/default substitution setter, or by a COM unpacker => RX
//   - written by application/control code                                          => TX
// Answering that per target with one FindEffectiveAddr run per address would be ~560 headless
// runs. This does the same constant-propagation ONCE over the full RAM range and dumps
// `ea,insaddr,function,funcentry,mnemonic` so the join can be done offline in Python.
//
// The address-register constant propagation is identical to FindEffectiveAddr.java (seeded
// a0/a1/a8/a9 from ecus/med17/ecu.conf BASEREGS); see that file for the rationale. Output is
// written to a FILE (arg 3) as well as a one-line summary on stdout, so a long run leaves a
// durable artifact even if the harness around it dies.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis -scriptPath core/ghidra \
//       -postScript DumpAllWrites.java <lo> <hi> <outfile> [storesOnly:true|false] [aN=0x.. ...]
//
// Pass the ECU's BASEREGS (from ecu.conf) as trailing aN=0x.. tokens, e.g.
//   ... DumpAllWrites.java 0xd0000000 0xd0010000 out.csv true a0=0xd0008000 a1=0x80048000 a8=0x80088800
// With NO tokens it falls back to MED17's base registers, which are WRONG for any other ECU (Simos85
// resolves ~0x4420 off), so always pass BASEREGS unless the target really is MED17.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import java.io.BufferedWriter;
import java.io.FileWriter;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class DumpAllWrites extends GhidraScript {

    // Base registers to seed constant-propagation. Pass the ECU's BASEREGS as trailing
    // aN=0x.. tokens (same form as SetBaseRegs.java), e.g. a0=0xd0008000 a1=0x80048000 a8=0x80088800.
    // With no tokens this falls back to MED17's values -- WRONG for any other ECU (Simos85 is off by
    // 0x4420), so always pass BASEREGS from ecu.conf. Populated per-run in run() from defaultSeed().
    static long[] defaultSeed() {
        long[] s = new long[16];
        for (int i=0;i<16;i++) s[i]=Long.MIN_VALUE;
        // ecus/med17/ecu.conf BASEREGS (fallback only)
        s[0]=0xd000c420L; s[8]=0xd000c420L; s[1]=0x8002f298L; s[9]=0x80103464L;
        return s;
    }

    static final Pattern LEA   = Pattern.compile("^lea a(\\d+),\\[a(\\d+)\\]([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVHA = Pattern.compile("^movh\\.a a(\\d+),#?([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVAA = Pattern.compile("^mov\\.aa a(\\d+),a(\\d+)$");
    static final Pattern MEM   = Pattern.compile("\\[a(\\d+)([+-]?)\\](#?([+-]?(?:0x)?[0-9a-fA-F]+))?");
    static final Pattern DEFA  = Pattern.compile("^[a-z0-9._]+ a(\\d+),");
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
        String out = args[2];
        boolean storesOnly = args.length < 4 || Boolean.parseBoolean(args[3]);

        // Trailing aN=0x.. tokens override the base-register seed (BASEREGS from ecu.conf).
        final long[] seed = defaultSeed();
        boolean seededFromArgs = false;
        for (int i = 3; i < args.length; i++) {
            String a = args[i];
            int eq = a.indexOf('=');
            if (eq < 1) continue;
            String name = a.substring(0, eq).trim();
            if (!name.matches("a\\d+")) continue;               // address registers only
            int rn = Integer.parseInt(name.substring(1));
            if (rn < 0 || rn > 15) continue;
            seed[rn] = Long.parseLong(a.substring(eq + 1).trim().replaceFirst("^0[xX]", ""), 16);
            seededFromArgs = true;
        }
        println("DumpAllWrites: base-reg seed = "
                + (seededFromArgs ? "from args" : "MED17 FALLBACK (pass BASEREGS if not MED17!)")
                + " a0=0x" + Long.toHexString(seed[0]) + " a1=0x" + Long.toHexString(seed[1])
                + " a8=0x" + Long.toHexString(seed[8]));

        int nf = 0, nhit = 0, nidx = 0;
        BufferedWriter w = new BufferedWriter(new FileWriter(out));
        w.write("kind,ea,insaddr,func,funcentry,mnemonic,text\n");

        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        while (fit.hasNext()) {
            Function fn = fit.next();
            nf++;
            String fname = fn.getName(), fentry = fn.getEntryPoint().toString();
            long[] reg = seed.clone();
            InstructionIterator it = currentProgram.getListing()
                    .getInstructions(fn.getBody(), true);
            while (it.hasNext()) {
                Instruction in = it.next();
                String t = in.toString().trim();
                String mn = in.getMnemonicString();

                Matcher m = MEM.matcher(t);
                if (m.find()) {
                    int b = Integer.parseInt(m.group(1));
                    if (reg[b] != Long.MIN_VALUE) {
                        long disp = m.group(4) == null ? 0 : parse(m.group(4));
                        long ea = (reg[b] + disp) & 0xffffffffL;
                        boolean isStore = mn.startsWith("st") || mn.startsWith("swap")
                                       || mn.startsWith("ldmst") || mn.startsWith("cmpswap");
                        if (ea >= lo && ea <= hi && (!storesOnly || isStore)) {
                            w.write(String.format("%s,%08x,%s,%s,%s,%s,\"%s\"%n",
                                    isStore ? "W" : "R", ea, in.getAddress(), fname, fentry, mn, t));
                            nhit++;
                        }
                    }
                }

                Matcher ix = IDX.matcher(t);
                if (ix.find()) {
                    int sb = Integer.parseInt(ix.group(3));
                    if (reg[sb] != Long.MIN_VALUE && reg[sb] >= lo - 0x400 && reg[sb] <= hi) {
                        w.write(String.format("I,%08x,%s,%s,%s,%s,\"%s\"%n",
                                reg[sb], in.getAddress(), fname, fentry, mn, t));
                        nidx++;
                    }
                }

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
                Matcher pm = MEM.matcher(t);
                while (pm.find()) if ("+".equals(pm.group(2))) reg[Integer.parseInt(pm.group(1))] = Long.MIN_VALUE;
                Matcher dfa = DEFA.matcher(t);
                if (dfa.find() && !mn.startsWith("st") && !mn.startsWith("jn") && !mn.startsWith("jz")
                        && !mn.startsWith("jeq") && !mn.startsWith("jne") && !mn.startsWith("call")) {
                    reg[Integer.parseInt(dfa.group(1))] = Long.MIN_VALUE;
                }
            }
        }
        w.close();
        println("DumpAllWrites: scanned " + nf + " functions; mem-hits=" + nhit + " indexed=" + nidx
                + " -> " + out);
    }
}
