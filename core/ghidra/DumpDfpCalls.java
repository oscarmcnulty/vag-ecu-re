// Resolve the DFP-handle argument (d4) at every call to the DSM report/query entry points.
//
// WHY. The DSM report API is FUN_8009d0ca(handle,...) / FUN_8009ca3c(handle,...) with
// handle = (algorithm<<12) | dfp_index. Handles are almost always materialised as
// `lea a15,[a1]-off ; ld.h(u) d4,[a15]` from the a1 literal pool, or as `mov d4,#imm`.
// Grepping decompiles gives the symbol name of the literal, not its value, so a question
// like "who reports DFP 397?" cannot be answered from the C. This walks back from each
// call site inside the same function and constant-propagates d4.
//
//   analyzeHeadless <proj> <name> -process -noanalysis -postScript \
//       DumpDfpCalls.java 0x8009d0ca [0x8009ca3c ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryAccessException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class DumpDfpCalls extends GhidraScript {

    static final long A0 = 0xd000c420L, A1 = 0x8002f298L, A8 = 0xd000c420L, A9 = 0x80103464L;

    static final Pattern LEA   = Pattern.compile("^lea a(\\d+),\\[a(\\d+)\\]([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVHA = Pattern.compile("^movh\\.a a(\\d+),#?([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern MOVD  = Pattern.compile("^mov(?:\\.u)? d(\\d+),#([+-]?(?:0x)?[0-9a-fA-F]+)$");
    static final Pattern LDH   = Pattern.compile("^ld\\.hu? d(\\d+),\\[a(\\d+)\\](?:#)?([+-]?(?:0x)?[0-9a-fA-F]+)?$");
    static final Pattern MOVDD = Pattern.compile("^mov d(\\d+),d(\\d+)$");
    static final Pattern LDA   = Pattern.compile("^ld\\.a a(\\d+),\\[a(\\d+)\\](?:#)?([+-]?(?:0x)?[0-9a-fA-F]+)?$");
    static final Pattern MOVAA2= Pattern.compile("^mov\\.aa a(\\d+),a(\\d+)$");

    static long parse(String s) {
        if (s == null) return 0;
        boolean neg = s.startsWith("-");
        String t = s.startsWith("+") || neg ? s.substring(1) : s;
        long v = t.startsWith("0x") || t.startsWith("0X") ? Long.parseLong(t.substring(2), 16)
                                                          : Long.parseLong(t);
        return neg ? -v : v;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Set<Long> targets = new HashSet<>();
        for (String a : args) targets.add(Long.decode(a));

        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        while (fit.hasNext()) {
            Function fn = fit.next();
            // linear pass over the function body, tracking a-regs and d4
            long[] areg = new long[16];
            long[] dreg = new long[16];
            for (int i = 0; i < 16; i++) { areg[i] = Long.MIN_VALUE; dreg[i] = Long.MIN_VALUE; }
            areg[0] = A0; areg[1] = A1; areg[8] = A8; areg[9] = A9;

            InstructionIterator iit = currentProgram.getListing()
                    .getInstructions(fn.getBody(), true);
            while (iit.hasNext()) {
                Instruction in = iit.next();
                String s = in.toString().trim();

                if (s.startsWith("call ") || s.startsWith("calla ") || s.startsWith("j ")
                        || s.startsWith("ja ")) {
                    Address[] flows = in.getFlows();
                    for (Address f : flows) {
                        if (targets.contains(f.getOffset())) {
                            long h = dreg[4];
                            println(String.format("  %s  fn=%-30s -> %s  d4=%s",
                                    in.getMinAddress(), fn.getName() + "@" + fn.getEntryPoint(),
                                    f, h == Long.MIN_VALUE ? "?" :
                                       String.format("0x%04x (dfp %d)", h & 0xffff, h & 0xfff)));
                        }
                    }
                    // calls clobber d0-d7 by convention except we keep going; reset d4
                    dreg[4] = Long.MIN_VALUE;
                    continue;
                }

                Matcher m;
                if ((m = LEA.matcher(s)).matches()) {
                    int d = Integer.parseInt(m.group(1)), b = Integer.parseInt(m.group(2));
                    areg[d] = areg[b] == Long.MIN_VALUE ? Long.MIN_VALUE
                                                        : areg[b] + parse(m.group(3));
                } else if ((m = MOVHA.matcher(s)).matches()) {
                    areg[Integer.parseInt(m.group(1))] = parse(m.group(2)) << 16;
                } else if ((m = MOVDD.matcher(s)).matches()) {
                    dreg[Integer.parseInt(m.group(1))] = dreg[Integer.parseInt(m.group(2))];
                } else if ((m = MOVD.matcher(s)).matches()) {
                    dreg[Integer.parseInt(m.group(1))] = parse(m.group(2)) & 0xffffffffL;
                } else if ((m = MOVAA2.matcher(s)).matches()) {
                    areg[Integer.parseInt(m.group(1))] = areg[Integer.parseInt(m.group(2))];
                } else if ((m = LDA.matcher(s)).matches()) {
                    int d = Integer.parseInt(m.group(1)), b = Integer.parseInt(m.group(2));
                    long off = m.group(3) == null ? 0 : parse(m.group(3));
                    long ea = areg[b] == Long.MIN_VALUE ? Long.MIN_VALUE : areg[b] + off;
                    long v = Long.MIN_VALUE;
                    if (ea != Long.MIN_VALUE && ea >= 0x80000000L && ea < 0x80400000L) {
                        try { v = getInt(toAddr(ea)) & 0xffffffffL; }
                        catch (MemoryAccessException e) { v = Long.MIN_VALUE; }
                    }
                    areg[d] = v;
                } else if ((m = LDH.matcher(s)).matches()) {
                    int d = Integer.parseInt(m.group(1)), b = Integer.parseInt(m.group(2));
                    long off = m.group(3) == null ? 0 : parse(m.group(3));
                    long ea = areg[b] == Long.MIN_VALUE ? Long.MIN_VALUE : areg[b] + off;
                    long v = Long.MIN_VALUE;
                    if (ea != Long.MIN_VALUE && ea >= 0x80000000L && ea < 0x80400000L) {
                        try { v = getShort(toAddr(ea)) & 0xffffL; }
                        catch (MemoryAccessException e) { v = Long.MIN_VALUE; }
                    }
                    dreg[d] = v;
                } else {
                    // any other definition of a d-reg or a-reg invalidates it
                    Matcher dm = Pattern.compile("^[a-z0-9._]+ d(\\d+),").matcher(s);
                    if (dm.find()) dreg[Integer.parseInt(dm.group(1))] = Long.MIN_VALUE;
                    Matcher am = Pattern.compile("^[a-z0-9._]+ a(\\d+),").matcher(s);
                    if (am.find()) {
                        int r = Integer.parseInt(am.group(1));
                        if (r != 0 && r != 1 && r != 8 && r != 9) areg[r] = Long.MIN_VALUE;
                        else areg[r] = Long.MIN_VALUE;
                    }
                }
            }
        }
        println("done.");
    }
}
