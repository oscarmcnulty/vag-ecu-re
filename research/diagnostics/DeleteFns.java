// Remove functions at addresses listed in a manifest file (one hex vaddr per line;
// '#' comments and blank lines ignored). Used to undo experimental function creation
// (e.g. an over-broad CodePtrSweep over code regions) so the project stays reproducible
// from analysis/function_entries.txt. Does NOT delete a function if its address is in
// the keep-manifest (arg[1], optional) — a safety net against removing wanted entries.
//   analyzeHeadless <proj> <name> -process -postScript DeleteFns.java <deleteList> [<keepManifest>]
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.BufferedReader;
import java.io.FileReader;
import java.util.HashSet;
import java.util.Set;

public class DeleteFns extends GhidraScript {
  Set<Long> readHex(String path) throws Exception {
    Set<Long> s = new HashSet<>();
    try (BufferedReader br = new BufferedReader(new FileReader(path))) {
      String line;
      while ((line = br.readLine()) != null) {
        line = line.trim();
        if (line.isEmpty() || line.startsWith("#")) continue;
        try { s.add(Long.decode(line.startsWith("0x") ? line : "0x" + line)); } catch (Exception e) {}
      }
    }
    return s;
  }
  @Override public void run() throws Exception {
    String[] args = getScriptArgs();
    if (args.length < 1) { println("usage: DeleteFns <deleteList> [keepManifest]"); return; }
    Set<Long> del = readHex(args[0]);
    Set<Long> keep = args.length > 1 ? readHex(args[1]) : new HashSet<>();
    int removed = 0, kept = 0, absent = 0;
    for (long v : del) {
      if (keep.contains(v)) { kept++; continue; }
      Address ep = toAddr(v);
      Function fn = getFunctionAt(ep);
      if (fn == null) { absent++; continue; }
      removeFunction(fn);
      if (getFunctionAt(ep) == null) removed++;
    }
    println("DeleteFns: removed=" + removed + " kept(in-manifest)=" + kept + " absent=" + absent);
  }
}
