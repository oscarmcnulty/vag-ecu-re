// Ghidra headless postScript: audit every COMPUTED (indirect) branch/call and report which
// ones Ghidra never resolved, so dispatch-hidden code cannot stay invisible.
//
// WHY. Per-function decompile stats only describe functions Ghidra already found. Code reached
// ONLY through a function-pointer table is not a "degraded" function -- it is not a function at
// all, so it is absent from the manifest and silently scores as clean. This walks the other way:
// from every `ji`/`calli`/`calla` site, ask what the reference model resolved, and classify.
//
// Three buckets matter, and they need different fixes:
//   RESOLVED-OK    targets exist and are inside functions          -> nothing to do
//   RESOLVED-BARE  targets exist but are NOT in any function       -> create functions there
//   UNRESOLVED     no computed-flow references at all              -> table must be recovered
//                  (a table living in RAM can never be resolved statically -- it is filled at
//                   boot, so the flash INITIALISER is what has to be found)
//   OFF-IMAGE      target outside every initialised block (e.g. TriCore PSPR at 0xc0000000)
//
//   analyzeHeadless <proj> <name> -process -postScript AuditIndirectBranches.java [csvOut]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.FlowType;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;

import java.io.PrintWriter;
import java.util.LinkedHashMap;
import java.util.Map;

public class AuditIndirectBranches extends GhidraScript {

    private String classify(Instruction in, StringBuilder tgts) {
        int nOk = 0, nBare = 0, nOff = 0, n = 0;
        for (Reference r : in.getReferencesFrom()) {
            RefType rt = r.getReferenceType();
            if (!(rt.isCall() || rt.isJump()) || !rt.isComputed()) continue;
            Address to = r.getToAddress();
            n++;
            if (tgts.length() < 220) tgts.append(tgts.length() == 0 ? "" : " ").append(to);
            MemoryBlock b = getMemoryBlock(to);
            if (b == null || !b.isInitialized()) nOff++;
            else if (getFunctionContaining(to) == null) nBare++;
            else nOk++;
        }
        if (n == 0) return "UNRESOLVED";
        if (nOff > 0) return "OFF-IMAGE";
        if (nBare > 0) return "RESOLVED-BARE";
        return "RESOLVED-OK";
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter csv = args.length > 0 ? new PrintWriter(args[0]) : null;
        if (csv != null) csv.println("site,function,mnemonic,verdict,targets");

        Map<String, Integer> tally = new LinkedHashMap<>();
        Map<String, Integer> byMnem = new LinkedHashMap<>();
        int total = 0;

        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction in = it.next();
            FlowType ft = in.getFlowType();
            // Computed = target is not a literal in the instruction. Covers ji/jli/calli and
            // any indirect call the processor module models as computed.
            if (!ft.isComputed() || !(ft.isCall() || ft.isJump())) continue;
            total++;
            StringBuilder tgts = new StringBuilder();
            String verdict = classify(in, tgts);
            tally.merge(verdict, 1, Integer::sum);
            byMnem.merge(in.getMnemonicString() + "/" + verdict, 1, Integer::sum);
            Function fn = getFunctionContaining(in.getAddress());
            if (csv != null)
                csv.printf("0x%s,%s,%s,%s,%s%n", in.getAddress(),
                        fn == null ? "(none)" : fn.getName(), in.getMnemonicString(),
                        verdict, tgts);
            if (!verdict.equals("RESOLVED-OK"))
                println(String.format("  %s  %-8s %-14s fn=%-34s %s", in.getAddress(),
                        in.getMnemonicString(), verdict,
                        fn == null ? "(none)" : fn.getName(), tgts));
        }
        if (csv != null) csv.close();

        println("=== indirect branch audit ===");
        println("  computed call/jump sites: " + total);
        for (Map.Entry<String, Integer> e : tally.entrySet())
            println(String.format("  %-14s %d", e.getKey(), e.getValue()));
        println("  --- by mnemonic ---");
        for (Map.Entry<String, Integer> e : byMnem.entrySet())
            println(String.format("  %-28s %d", e.getKey(), e.getValue()));
        println("AUDITDONE");
    }
}
