// Ghidra headless: recover TriCore base-register init values (a0/a1/a8/a9...).
// Cal data is addressed base-register-relative; until these registers have known
// values, Ghidra resolves almost no cal references. This scans for the address
// building idioms (movh.a + lea/addih.a) that load constant addresses into the
// address registers, and reports the resulting values + how often each occurs.
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript FindBaseRegs.java
// Feed the winners to SetBaseRegs.java as `a0=0x... a1=0x...` arguments.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

public class FindBaseRegs extends GhidraScript {

    /**
     * Destination address register of an address-forming instruction, or null.
     * Uses getOpObjects rather than getRegister(0): for TriCore, operand 0 of
     * `lea a1,[a1]-0xd68` is not always exposed as a bare register, which made the
     * previous getRegister(0)/getScalar(i) version silently tally NOTHING on
     * MED17.1.1 even though the idiom is present (init @0x800829d2). getOpObjects
     * is the same extraction ResolveCalReads.java already relies on.
     */
    private static Register dstAreg(Instruction ins) {
        for (Object o : ins.getOpObjects(0)) {
            if (o instanceof Register r && r.getName().matches("a\\d+")) return r;
        }
        return null;
    }

    /** First scalar appearing in operands >= 1 (the immediate / displacement). */
    private static Scalar firstScalar(Instruction ins) {
        for (int i = 1; i < ins.getNumOperands(); i++) {
            for (Object o : ins.getOpObjects(i)) {
                if (o instanceof Scalar s) return s;
            }
        }
        return null;
    }

    @Override
    public void run() throws Exception {
        // per-register: last movh.a high value (reg name -> hi<<16)
        Map<String, Long> hi = new HashMap<>();
        // tally of resolved full values: "reg=0xVALUE" -> count
        Map<String, Integer> tally = new LinkedHashMap<>();
        // where each value was formed, for the report
        Map<String, String> firstSite = new HashMap<>();
        int movh = 0, formed = 0;

        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Instruction ins = it.next();
            String mn = ins.getMnemonicString().toLowerCase();
            Register dst = dstAreg(ins);
            if (dst == null) continue;
            String dn = dst.getName();

            if (mn.equals("movh.a")) {
                Scalar s = firstScalar(ins);
                if (s != null) { hi.put(dn, (s.getUnsignedValue() & 0xffffL) << 16); movh++; }
            } else if (mn.equals("lea") || mn.equals("addih.a") || mn.equals("add.a")) {
                Long base = hi.get(dn);
                if (base == null) continue;
                // The displacement must be relative to the SAME register the movh.a
                // wrote (lea a1,[a1]disp); `lea a15,[a0]disp` is an ordinary sdata
                // access, not the formation of a15's own base value.
                boolean selfRel = false;
                for (int i = 1; i < ins.getNumOperands() && !selfRel; i++) {
                    for (Object o : ins.getOpObjects(i)) {
                        if (o instanceof Register r && r.getName().equals(dn)) { selfRel = true; break; }
                    }
                }
                if (!selfRel && !mn.equals("add.a")) continue;
                Scalar s = firstScalar(ins);
                if (s == null) continue;
                long off = s.getSignedValue();
                long val = (mn.equals("addih.a") ? base + (off << 16) : base + off) & 0xffffffffL;
                String key = String.format("%s=0x%08x", dn, val);
                tally.merge(key, 1, Integer::sum);
                firstSite.putIfAbsent(key, ins.getAddress().toString());
                hi.remove(dn);      // consumed; don't re-pair with a later lea
                formed++;
            }
        }

        println(String.format("scanned: %d movh.a into an address reg, %d full values formed", movh, formed));
        println("=== candidate base-register values (reg=value : occurrences @ first site) ===");
        if (tally.isEmpty()) {
            println("  NONE -- this ECU may not use base-register-relative cal addressing,");
            println("  or the idiom differs. Run research/diagnostics/DumpAddrRegInsns.java to see the real idioms.");
        }
        tally.entrySet().stream()
             .sorted((a, b) -> b.getValue() - a.getValue())
             .forEach(e -> println(String.format("  %-16s : %5d  @%s",
                     e.getKey(), e.getValue(), firstSite.get(e.getKey()))));

        // The frequency ranking above is dominated by a15/a2/a3 -- ordinary scratch
        // address formation. The ACTUAL base registers rank near the BOTTOM, because
        // being set once in the startup code and never reloaded is precisely what
        // makes them base registers. Call them out so they are not missed in the noise.
        println("");
        println("=== ABI base registers (a0 sdata / a1 cal-or-rodata / a8,a9 system) ===");
        println("A low count here is EXPECTED and is the good sign: it means the value is");
        println("established once at startup and held. Feed these to SetBaseRegs.java.");
        boolean any = false;
        for (String reg : new String[]{"a0", "a1", "a8", "a9"}) {
            for (Map.Entry<String, Integer> e : tally.entrySet()) {
                if (e.getKey().startsWith(reg + "=")) {
                    println(String.format("  %-16s : %5d  @%s   -> %s",
                            e.getKey(), e.getValue(), firstSite.get(e.getKey()), e.getKey()));
                    any = true;
                }
            }
        }
        if (!any) println("  none found -- this ECU may address calibration absolutely instead.");
    }
}
