// Ghidra headless: set TriCore base-register values as context, then re-analyze so
// [a1+off] etc. resolve to absolute cal addresses (creating the references that map
// extraction needs). Values are per-ECU -- recover them first with FindBaseRegs.java
// and pass them in as `a<N>=<value>` arguments:
//   analyzeHeadless <proj> <name> -process <bin> \
//       -scriptPath core/ghidra -postScript SetBaseRegs.java a0=0xd0008000 a1=0x80048000 a8=0x80088800
// Use the CACHED (0x8...) form of a flash base so the refs land in the 0x80000000 image
// rather than the 0xa0000000 non-cached alias, which the loader does not map.
// Known values:
//   simos85 (TC1796): a0=0xd0008000 (RAM sdata) a1=0x80048000 (CAL base) a8=0x80088800
//                     (descriptor/system base; a8-0x26a8 = master pointer table)
// Pass `-nore` (or `noreanalyze`) to set the context WITHOUT triggering a re-analysis.
//@category VAG-RE
import ghidra.app.plugin.core.analysis.AutoAnalysisManager;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.lang.RegisterValue;
import ghidra.program.model.listing.ProgramContext;
import java.math.BigInteger;
import java.util.LinkedHashMap;
import java.util.Map;

public class SetBaseRegs extends GhidraScript {
    @Override
    public void run() throws Exception {
        Map<String, Long> regs = new LinkedHashMap<>();
        boolean reanalyze = true;

        for (String a : getScriptArgs()) {
            if (a.equals("-nore") || a.equals("noreanalyze")) { reanalyze = false; continue; }
            int eq = a.indexOf('=');
            if (eq < 1) { println("SetBaseRegs: ignoring unparsable arg '" + a + "'"); continue; }
            String name = a.substring(0, eq).trim();
            if (!name.matches("[ad]\\d+")) { println("SetBaseRegs: not a register: " + name); continue; }
            regs.put(name, Long.parseLong(a.substring(eq + 1).trim().replaceFirst("^0[xX]", ""), 16));
        }
        if (regs.isEmpty()) {
            println("SetBaseRegs: no registers given. usage: SetBaseRegs.java a0=0x... a1=0x... [a8=0x...] [-nore]");
            println("             recover the values first with FindBaseRegs.java");
            return;
        }

        ProgramContext ctx = currentProgram.getProgramContext();
        Address start = currentProgram.getMinAddress();
        Address end = currentProgram.getMaxAddress();

        for (Map.Entry<String, Long> e : regs.entrySet()) {
            Register r = ctx.getRegister(e.getKey());
            if (r == null) { println("no register " + e.getKey()); continue; }
            ctx.setRegisterValue(start, end, new RegisterValue(r, BigInteger.valueOf(e.getValue())));
            println(String.format("set %s = 0x%08x over %s..%s", e.getKey(), e.getValue(), start, end));
        }

        if (!reanalyze) { println("context set; re-analysis skipped (-nore)."); return; }
        println("re-analyzing with base-register context ...");
        AutoAnalysisManager mgr = AutoAnalysisManager.getAnalysisManager(currentProgram);
        mgr.reAnalyzeAll(null);
        mgr.startAnalysis(monitor);
        println("re-analysis complete.");
    }
}
