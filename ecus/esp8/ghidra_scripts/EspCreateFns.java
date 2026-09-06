// Recreate the exact ESP8 mixed-ISA function set from a Thumb-annotated manifest
// (lines: 0xADDR,<T|A>). Sets the TMode context for Thumb entries so disassembly starts
// in the correct ISA, then forces a function. Part of ecus/esp8/8R0907379BG/reproduce.sh.
//   analyzeHeadless <proj> <name> -process -postScript EspCreateFns.java <manifest>
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import java.io.*;
import java.math.BigInteger;

public class EspCreateFns extends GhidraScript {
    public void run() throws Exception {
        if (getScriptArgs().length < 1) { println("usage: EspCreateFns <manifest>"); return; }
        Register tmode = currentProgram.getLanguage().getRegister("TMode");
        int have=0, created=0, failed=0, thumbSet=0;
        try (BufferedReader br = new BufferedReader(new FileReader(getScriptArgs()[0]))) {
            String line;
            while ((line = br.readLine()) != null) {
                line = line.trim();
                if (line.isEmpty() || line.startsWith("#")) continue;
                String[] p = line.split(",");
                Address ep = currentProgram.getAddressFactory().getAddress(p[0].trim());
                if (ep == null) { failed++; continue; }
                boolean thumb = p.length > 1 && p[1].trim().equalsIgnoreCase("T");
                if (thumb && tmode != null) {
                    try { currentProgram.getProgramContext().setValue(tmode, ep, ep, BigInteger.ONE); thumbSet++; }
                    catch (Exception e) { /* context set may fail on already-defined; disasm still keyed */ }
                }
                if (getFunctionAt(ep) != null) { have++; continue; }
                disassemble(ep);
                new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
                if (getFunctionAt(ep) != null) created++; else failed++;
            }
        }
        println("EspCreateFns: existing="+have+" created="+created+" failed="+failed+" thumbSet="+thumbSet);
    }
}
