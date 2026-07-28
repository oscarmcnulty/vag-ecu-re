// Ghidra headless postScript: apply a symbols CSV (address,name,type,comment).
// type = FUNCTION | LABEL. Reproduces the labeled project from version control,
// so recovered symbols never live only in ephemeral /tmp again.
//   analyzeHeadless <proj> <name> -process -postScript ApplySymbols.java <csvPath>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class ApplySymbols extends GhidraScript {
    private final Set<String> used = new HashSet<>();

    // Disambiguate duplicate names (e.g. near-identical map wrappers an LLM names
    // identically) by appending the address, so the whole CSV applies cleanly.
    private String unique(String name, Address a) {
        if (used.add(name)) return name;
        String alt = name + "_" + a.toString();
        used.add(alt);
        return alt;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) { println("usage: ApplySymbols <csvPath>"); return; }
        int applied = 0, funcs = 0, labels = 0, skipped = 0;
        try (BufferedReader br = new BufferedReader(new FileReader(args[0]))) {
            String line; boolean header = true;
            while ((line = br.readLine()) != null) {
                if (header) { header = false; continue; }
                if (line.trim().isEmpty()) continue;
                String[] f = splitCsv(line);
                if (f.length < 3) { skipped++; continue; }
                Address a = toAddr(Long.decode(f[0].trim()));
                String name = unique(f[1].trim(), a);
                String type = f[2].trim().toUpperCase();
                String comment = f.length > 3 ? f[3].trim() : "";
                try {
                    if (type.equals("FUNCTION")) {
                        Function fn = getFunctionAt(a);
                        if (fn == null) fn = createFunction(a, name);
                        if (fn != null) { fn.setName(name, SourceType.USER_DEFINED); funcs++; }
                        else { createLabel(a, name, true, SourceType.USER_DEFINED); labels++; }
                    } else {
                        createLabel(a, name, true, SourceType.USER_DEFINED); labels++;
                    }
                    if (!comment.isEmpty()) setPlateComment(a, comment);
                    applied++;
                } catch (Exception e) {
                    println("  skip " + name + " @ " + a + ": " + e.getMessage());
                    skipped++;
                }
            }
        }
        println("ApplySymbols: applied=" + applied + " funcs=" + funcs
                + " labels=" + labels + " skipped=" + skipped);
    }

    private String[] splitCsv(String line) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        boolean q = false;
        for (char c : line.toCharArray()) {
            if (c == '"') q = !q;
            else if (c == ',' && !q) { out.add(cur.toString()); cur.setLength(0); }
            else cur.append(c);
        }
        out.add(cur.toString());
        return out.toArray(new String[0]);
    }
}
