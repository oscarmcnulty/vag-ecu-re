// Ghidra headless postScript: recreate functions from a version-controlled entry-point
// manifest (one hex vaddr per line; '#' comments ignored). Disassembles and forces a
// function at each address that auto-analysis didn't already find (e.g. CAN-stack
// handlers reached only via function-pointer tables). Part of the reproduce pipeline.
//   analyzeHeadless <proj> <name> -process -postScript CreateFunctions.java <manifest>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.BufferedReader;
import java.io.FileReader;

public class CreateFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) { println("usage: CreateFunctions <manifest>"); return; }
        int have = 0, created = 0, failed = 0;
        try (BufferedReader br = new BufferedReader(new FileReader(args[0]))) {
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                Address ep = currentProgram.getAddressFactory().getAddress(line);
                if (ep == null) { failed++; continue; }
                if (getFunctionAt(ep) != null) { have++; continue; }
                disassemble(ep);
                new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
                if (getFunctionAt(ep) != null) created++; else failed++;
            }
        }
        println("CreateFunctions: existing=" + have + " created=" + created + " failed=" + failed);
    }
}
