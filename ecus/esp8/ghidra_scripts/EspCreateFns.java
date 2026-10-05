// Recreate the exact ESP8 mixed-ISA function set from a Thumb-annotated manifest
// (lines: 0xADDR,<T|A>). Sets the TMode context for Thumb entries so disassembly starts
// in the correct ISA, then forces a function. Part of ecus/esp8/8R0907379BG/reproduce.sh.
//   analyzeHeadless <proj> <name> -process -postScript EspCreateFns.java <manifest>
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
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
                // Clear conflicts so disassembly starts clean: manifest entries recovered from the
                // data-driven dispatch tables (KWP service handlers) can land in the DATA region or
                // over an ARM mis-decode. If ep is interior to a WRONG-ISA function, drop that function;
                // then clear any code/data unit straddling ep.
                Function cont = getFunctionContaining(ep);
                if (cont != null && cont.getEntryPoint().getOffset() != ep.getOffset() && tmode != null) {
                    BigInteger cv = currentProgram.getProgramContext().getValue(tmode, cont.getEntryPoint(), false);
                    boolean contThumb = cv != null && cv.intValue() == 1;
                    if (contThumb != thumb) {
                        AddressSetView body = cont.getBody();
                        removeFunctionAt(cont.getEntryPoint());
                        clearListing(body.getMinAddress(), body.getMaxAddress());
                    }
                }
                CodeUnit cu = currentProgram.getListing().getCodeUnitContaining(ep);
                if (cu != null) clearListing(cu.getMinAddress(), cu.getMaxAddress());
                disassemble(ep);
                new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
                if (getFunctionAt(ep) != null) created++; else failed++;
            }
        }
        println("EspCreateFns: existing="+have+" created="+created+" failed="+failed+" thumbSet="+thumbSet);
    }
}
