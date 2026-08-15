// Ghidra headless postScript: decompile every function to <outDir>/<addr>.c and emit a
// per-function MANIFEST so gaps are never silent. Each intended function is classified
// ok | degraded | fail (and, vs the canonical entry list, absent), so the disasm-recovery
// step (reproduce.sh 6b) can cover EVERY function that lacks usable C -- not just the ones
// that happened to leave a banner-carrying .c behind.
//   analyzeHeadless <proj> <name> -process -postScript DecompileAll.java <outDir> [entriesFile]
// Outputs:
//   <outDir>/<addr>.c              decompiled C (ok + degraded; fail/absent produce none)
//   <outDir>.manifest.csv          addr,name,bytes,status,elapsed_ms,reason   (one row per intended fn)
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import java.io.File;
import java.io.FileWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public class DecompileAll extends GhidraScript {
    // Status taxonomy (per intended function):
    //   ok        -- full, usable C. INCLUDES two informational warnings that do NOT compromise the
    //                body: the "delay deadcode elimination for space" restart, and "Could not
    //                recover jumptable" (a benign fall-back to a correct indirect call). Keying
    //                'degraded' on either mislabelled ~850 healthy functions. Logged with
    //                reason=space-restart-benign / jumptable-fallback-benign so the manifest is honest.
    //   degraded  -- a genuine call target whose body was TRUNCATED on undecodable bytes. In this
    //                firmware that is only the handful of 1-byte halt/trap stubs in RAM (whose
    //                disasm view is the better artifact anyway). Fed to the disasm fallback (6b).
    //   bogus     -- a truncated body on an entry that NOTHING calls: a spurious function created on
    //                data (strings/tables/padding), e.g. an entry sitting on the ASCII part string
    //                "S85L...". NOT a real function -> pruned from function_entries.txt, NOT disasm'd.
    //   fail/absent -- no .c at all / not a live function (unchanged).
    //
    // GENUINE damage = the body was TRUNCATED because SLEIGH hit bytes it could not decode. That
    // is the only signal that actually costs usable C. Note what is deliberately NOT here:
    //   - "Restarted to delay deadcode elimination for space" -- informational restart, completes.
    //   - "Could not recover jumptable ... Too many branches" -- the decompiler could not prove a
    //     computed target was a static switch, so it falls back to a plain indirect call
    //     `(*(code *)(ptr & ~1))(...)`, which is CORRECT for the callback/vtable/installed-handler
    //     dispatch these sites actually are (153/156 carry no truncation). Benign; noted, not degraded.
    private static final String[] DAMAGE_SIGNALS = {
        "Bad instruction",               // SLEIGH could not decode -> body truncated
        "Truncating control flow",       // decompiler gave up mid-body
        "Unimplemented",                 // unmodeled opcode
    };
    // BENIGN warnings the decompiler emits that do NOT compromise the body -- recorded in the
    // reason column for traceability, but classified 'ok'. (Explicitly NOT damage.)
    private static final String BENIGN_RESTART = "Restarted to delay deadcode elimination for space";
    private static final String BENIGN_JUMPTABLE = "Could not recover jumptable";
    private static final int[] TIMEOUTS = {60, 240};   // escalate before giving up

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args.length > 0 ? args[0] : "decompiles";
        String entriesFile = args.length > 1 ? args[1] : null;
        new File(outDir).mkdirs();

        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        StringBuilder manifest = new StringBuilder("addr,name,bytes,status,elapsed_ms,reason\n");
        Set<String> seen = new LinkedHashSet<>();
        int ok = 0, degraded = 0, bogus = 0, fail = 0;

        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Function fn = it.next();
            String addr = fn.getEntryPoint().toString();
            long bytes = fn.getBody().getNumAddresses();
            seen.add(addr.replaceAll("^0x", ""));

            String status = "fail", reason = "";
            String c = null;
            long dt = 0;
            for (int t : TIMEOUTS) {
                long t0 = System.currentTimeMillis();
                DecompileResults r = dec.decompileFunction(fn, t, monitor);
                dt = System.currentTimeMillis() - t0;
                if (r == null) { reason = "null-results"; continue; }
                if (!r.decompileCompleted()) {
                    String e = r.getErrorMessage();
                    reason = (e == null || e.isBlank()) ? "not-completed" : e.replaceAll("\\s+", " ").trim();
                    continue;   // retry at the next-higher timeout
                }
                if (r.getDecompiledFunction() == null) { reason = "no-c"; continue; }
                c = r.getDecompiledFunction().getC();
                String damage = firstDamage(c);
                if (damage != null) {
                    // Truncated body. If nothing CALLs the entry it is a spurious function on data
                    // (string/table/padding) -> 'bogus' (pruned, not disasm-recovered). If it is a
                    // genuine call target that still truncates, it is real damage -> 'degraded'
                    // (disasm fallback). In this firmware the only 'degraded' cases are the 1-byte
                    // halt/trap stubs in RAM, which the disasm view renders best anyway.
                    if (hasCallRef(fn.getEntryPoint())) {
                        status = "degraded";
                        reason = "truncated:" + damage.toLowerCase().replace(' ', '-');
                    } else {
                        status = "bogus";
                        reason = "truncated-uncalled";
                    }
                } else {
                    status = "ok";
                    // Note (don't penalise) benign warnings so the manifest stays honest.
                    if (c.contains(BENIGN_JUMPTABLE)) reason = "jumptable-fallback-benign";
                    else if (c.contains(BENIGN_RESTART)) reason = "space-restart-benign";
                }
                break;
            }

            if (c != null) {
                try (FileWriter w = new FileWriter(new File(outDir, addr + ".c"))) { w.write(c); }
            }
            if (status.equals("ok")) ok++;
            else if (status.equals("degraded")) degraded++;
            else if (status.equals("bogus")) bogus++;
            else fail++;
            manifest.append(addr).append(',').append(csv(fn.getName())).append(',').append(bytes)
                    .append(',').append(status).append(',').append(dt).append(',').append(csv(reason)).append('\n');
        }

        // Reconcile against the canonical entry list: any intended entry that is not a live
        // function here (creation drift) is reported as 'absent' so it is never silently lost.
        int absent = 0;
        if (entriesFile != null && new File(entriesFile).exists()) {
            List<String> lines = Files.readAllLines(Paths.get(entriesFile));
            for (String raw : lines) {
                String s = raw.trim();
                if (s.isEmpty() || s.startsWith("#")) continue;   // tolerate comments/blank lines
                s = s.replaceAll("^0x", "");
                if (!s.matches("[0-9a-fA-F]+")) continue;
                if (!seen.contains(s)) {
                    manifest.append("0x").append(s).append(",,0,absent,0,not-a-live-function\n");
                    absent++;
                }
            }
        }

        File mf = new File(outDir + ".manifest.csv");
        try (FileWriter w = new FileWriter(mf)) { w.write(manifest.toString()); }

        int total = ok + degraded + bogus + fail;
        double pct = total > 0 ? (100.0 * ok / total) : 0.0;
        println(String.format("DecompileAll: ok=%d degraded=%d bogus=%d fail=%d absent=%d (%.1f%% clean) manifest=%s",
                ok, degraded, bogus, fail, absent, pct, mf.getPath()));
        if (fail + absent > 0)
            println("DecompileAll: WARNING " + (fail + absent) + " function(s) have NO usable C "
                    + "-- see status=fail/absent in " + mf.getName() + " (feed to DumpDisasmFns).");
        if (bogus > 0)
            println("DecompileAll: NOTE " + bogus + " 'bogus' entr(y/ies) truncate on a bad instruction with "
                    + "no caller -- likely spurious functions on data; prune from function_entries.txt.");
    }

    // A CALL reference to the entry point marks a genuine function; entries with none that also
    // fail to decode are spurious functions created on data.
    private boolean hasCallRef(Address entry) {
        for (Reference ref : getReferencesTo(entry)) {
            if (ref.getReferenceType().isCall()) return true;
        }
        return false;
    }

    private static String firstMatch(String hay, String[] needles) {
        for (String n : needles) if (hay.contains(n)) return n;
        return null;
    }

    /**
     * Damage signals, but ONLY where the decompiler itself raised them.
     *
     * Scanning the whole C text is wrong once ApplySymbols is in the pipeline: the function's plate
     * comment is emitted above the signature and becomes part of getC(), so a symbols_merged.csv
     * comment that merely DISCUSSES a bad instruction marks its own function degraded. That is not
     * hypothetical -- it happened to segC_routine_called_from_TSK02 (0xc000079c), a complete 40-byte
     * function ending in `ret`, whose note explains the bad-instruction story and thereby tripped the
     * detector. Ghidra prefixes every warning it emits with "WARNING:", so require that on the same
     * line; prose in a plate comment can then say anything it likes.
     */
    private static String firstDamage(String c) {
        for (String line : c.split("\n")) {
            if (!line.contains("WARNING:")) continue;
            String hit = firstMatch(line, DAMAGE_SIGNALS);
            if (hit != null) return hit;
        }
        return null;
    }

    private static String csv(String s) {
        if (s == null) return "";
        return (s.contains(",") || s.contains("\"")) ? '"' + s.replace("\"", "\"\"") + '"' : s;
    }
}
