// Ghidra headless postScript: collapse functions living in a non-cached flash alias
// onto their canonical cached address.
//
// Background: MapMemory.java maps the TriCore non-cached flash alias (0xa0000000 ->
// 0x80000000) so that control flow through alias pointers resolves instead of dying
// with "Could not follow disassembly flow into non-existing memory". That fixes the
// flow, but auto-analysis then materialises FUNCTIONS at alias addresses too, and
// because the alias is byte-mapped they are bit-identical twins of the cached ones.
// On MED17.1.1 that was 1360 alias functions against 3396 real ones -- ~29% of the
// corpus duplicated, which doubles decompile time and (worse) doubles the function
// list that later gets hand- or AI-annotated.
//
// Two distinct cases, and conflating them loses code:
//   twin   -- a function already exists at the cached address. The alias one is pure
//             duplication -> delete it.
//   orphan -- NO function exists at the cached address; this code was only ever
//             reached through an alias pointer. Deleting it would silently lose a
//             real function, so CREATE the cached twin first, then delete the alias.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript CanonicalizeAlias.java 0xa0000000 0x80000000 0x400000
// Args: <aliasBase> <cachedBase> <length>. Pass -n / --dry-run to only report.
//@category VAG-RE
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.util.ArrayList;
import java.util.List;

public class CanonicalizeAlias extends GhidraScript {

    private static long hex(String s) {  // accepts values with or without the 0x prefix
        return Long.parseLong(s.trim().replaceFirst("^0[xX]", ""), 16);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        boolean dry = false;
        List<String> pos = new ArrayList<>();
        for (String a : args) {
            if (a.equals("-n") || a.equals("--dry-run")) dry = true; else pos.add(a);
        }
        if (pos.size() < 3) {
            println("usage: CanonicalizeAlias <aliasBase> <cachedBase> <length> [-n]");
            return;
        }
        long aliasBase = hex(pos.get(0)), cachedBase = hex(pos.get(1)), len = hex(pos.get(2));
        long delta = cachedBase - aliasBase;

        // Snapshot first: deleting while iterating the FunctionManager is unsafe.
        List<Function> inAlias = new ArrayList<>();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext() && !monitor.isCancelled()) {
            Function f = it.next();
            long ep = f.getEntryPoint().getOffset();
            if (ep >= aliasBase && ep < aliasBase + len) inAlias.add(f);
        }

        int twins = 0, orphansCreated = 0, orphansFailed = 0, deleted = 0;
        for (Function f : inAlias) {
            if (monitor.isCancelled()) break;
            long ep = f.getEntryPoint().getOffset();
            Address cached = toAddr(ep + delta);

            if (getFunctionAt(cached) == null) {
                // orphan: preserve it at the canonical address before dropping the alias copy
                if (dry) { orphansCreated++; continue; }
                disassemble(cached);
                new CreateFunctionCmd(cached).applyTo(currentProgram, monitor);
                if (getFunctionAt(cached) != null) orphansCreated++;
                else { orphansFailed++; continue; }   // keep the alias fn rather than lose the code
            } else {
                twins++;
            }
            if (dry) continue;
            removeFunction(f);
            if (getFunctionAt(f.getEntryPoint()) == null) deleted++;
        }

        println(String.format("CanonicalizeAlias: alias fns=%d twins=%d orphans-recovered=%d "
                + "orphans-failed=%d deleted=%d%s",
                inAlias.size(), twins, orphansCreated, orphansFailed, deleted, dry ? " (DRY RUN)" : ""));
        if (orphansFailed > 0) {
            println("  NOTE: " + orphansFailed + " alias fns kept -- could not create the cached twin."
                    + " They stay in the corpus rather than being silently dropped.");
        }
    }
}
