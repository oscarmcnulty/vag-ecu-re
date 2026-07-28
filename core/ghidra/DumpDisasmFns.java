// Dump annotated TriCore disassembly for a list of functions (one addr per line;
// a ".c" suffix and "0x" prefix are tolerated so a `ls decompiles_r` list works).
//
// Purpose: Ghidra's decompiler guts ~174 functions with the "delay deadcode
// elimination for space" restart (division / CSFR idioms like dvstep.u, mfcr,
// disable/enable -- e.g. 0x800ad02a). Their decompiled C is unusable, but the
// disassembly is fine. This keeps those functions readable from disasm.
//   analyzeHeadless <proj> <name> -process -noanalysis -postScript DumpDisasmFns.java <listFile> <outDir>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;
import java.io.File;
import java.io.FileWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;

public class DumpDisasmFns extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String listFile = args[0];
        String outDir = args.length > 1 ? args[1] : "disasm_r";
        new File(outDir).mkdirs();

        List<String> lines = Files.readAllLines(Paths.get(listFile));
        int done = 0, miss = 0;
        for (String raw : lines) {
            String s = raw.trim();
            if (s.isEmpty() || s.startsWith("#")) continue;
            s = s.replaceAll("\\.c$", "").replaceAll("^0x", "");
            Address ep;
            try { ep = currentProgram.getAddressFactory().getAddress(s); }
            catch (Exception e) { miss++; continue; }
            Function fn = getFunctionAt(ep);
            if (fn == null) fn = getFunctionContaining(ep);
            if (fn == null) { miss++; continue; }

            StringBuilder sb = new StringBuilder();
            sb.append("; ").append(fn.getName()).append(" @ ").append(fn.getEntryPoint())
              .append("  (").append(fn.getBody().getNumAddresses()).append(" bytes)\n");
            sb.append("; stored return=").append(fn.getReturnType())
              .append("  params=").append(fn.getParameterCount()).append("\n;\n");
            InstructionIterator it = currentProgram.getListing().getInstructions(fn.getBody(), true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                StringBuilder refs = new StringBuilder();
                for (Reference r : ins.getReferencesFrom()) {
                    Address to = r.getToAddress();
                    Symbol sym = getSymbolAt(to);
                    refs.append("  -> ").append(sym != null ? sym.getName() : to.toString());
                }
                sb.append(ins.getAddress()).append(":  ").append(ins.toString()).append(refs).append("\n");
            }
            try (FileWriter w = new FileWriter(new File(outDir, fn.getEntryPoint().toString() + ".asm"))) {
                w.write(sb.toString());
            }
            done++;
        }
        println("DumpDisasmFns: dumped=" + done + " missed=" + miss + " out=" + outDir);
    }
}
