// Ghidra headless postScript: dump every code reference whose destination lies in
// the calibration region, using Ghidra's RESOLVED references (catches base-register
// and descriptor-resolved accesses that a text scan of the decompiles misses).
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript FindCalXrefs.java <outCsv> [loHex] [hiHex] \
//           [--alias=<aliasBase>:<cachedBase>:<len>]
// Output rows: dest_vaddr, from_vaddr, from_func
//
// --alias folds references that ORIGINATE in a non-cached flash alias back onto their
// cached address and de-duplicates them. This is required whenever MapMemory.java has
// mapped the alias: the alias is byte-mapped and executable, so the same instruction
// is disassembled at both 0x80... and 0xa0... and emits the SAME cal reference twice.
// On MED17.1.1 that was 2344 of 2548 rows -- and because CanonicalizeAlias.java has
// (correctly) removed the duplicate alias FUNCTIONS, those rows also carry an empty
// from_func, so they read as "cal accessed from nowhere". Folding fixes both.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import java.io.FileWriter;
import java.util.LinkedHashSet;
import java.util.Set;

public class FindCalXrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String out = "cal_ghidra_xref.csv";
        long lo = 0x80040000L, hi = 0x80070000L;
        long aliasBase = -1, aliasCached = 0, aliasLen = 0;
        int positional = 0;
        for (String a : args) {
            if (a.startsWith("--alias=")) {
                String[] p = a.substring(8).split(":");
                if (p.length != 3) { println("bad --alias (want base:cached:len): " + a); return; }
                aliasBase = Long.decode(p[0]); aliasCached = Long.decode(p[1]); aliasLen = Long.decode(p[2]);
            } else if (positional == 0) { out = a; positional++; }
            else if (positional == 1) { lo = Long.decode(a); positional++; }
            else if (positional == 2) { hi = Long.decode(a); positional++; }
        }

        AddressSet region = new AddressSet(toAddr(lo), toAddr(hi - 1));
        ReferenceManager rm = currentProgram.getReferenceManager();
        int rows = 0, folded = 0, dupes = 0;
        Set<String> emitted = new LinkedHashSet<>();

        try (FileWriter w = new FileWriter(out)) {
            w.write("dest_vaddr,from_vaddr,from_func\n");
            // iterate every address in the cal region that is a reference destination
            var destIt = rm.getReferenceDestinationIterator(region, true);
            while (destIt.hasNext() && !monitor.isCancelled()) {
                Address dest = destIt.next();
                for (Reference ref : rm.getReferencesTo(dest)) {
                    Address from = ref.getFromAddress();
                    if (aliasBase >= 0) {
                        long f = from.getOffset();
                        if (f >= aliasBase && f < aliasBase + aliasLen) {
                            from = toAddr(f - aliasBase + aliasCached);
                            folded++;
                        }
                    }
                    String key = dest + "," + from;
                    if (!emitted.add(key)) { dupes++; continue; }
                    Function fn = getFunctionContaining(from);
                    String fname = fn != null ? fn.getName() : "";
                    w.write(String.format("%s,%s,%s\n", dest, from, fname));
                    rows++;
                }
            }
        }
        println("FindCalXrefs: " + rows + " references into [" +
                Long.toHexString(lo) + "," + Long.toHexString(hi) + ") -> " + out
                + (aliasBase >= 0 ? "  (alias-folded=" + folded + ", deduped=" + dupes + ")" : ""));
    }
}
