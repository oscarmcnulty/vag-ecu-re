// Force-disassemble + create a function at each given address.  args: <addr>[t] ...
//   trailing 't' (or an odd address) => disassemble as THUMB
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspFnAt extends GhidraScript {
    public void run() throws Exception {
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing lst = currentProgram.getListing();
        for (String s : getScriptArgs()) {
            boolean thumb = s.endsWith("t");
            if (thumb) s = s.substring(0, s.length()-1);
            long v = Long.parseLong(s,16);
            if ((v & 1)!=0) { thumb = true; v &= ~1L; }
            Address ad = sp.getAddress(v);
            Function ex = getFunctionContaining(ad);
            if (ex!=null && ex.getEntryPoint().equals(ad)) { println("EspFnAt: "+ad+" already a function"); continue; }
            ArmDisassembleCommand cmd = new ArmDisassembleCommand(ad, null, thumb);
            boolean d = cmd.applyTo(currentProgram, monitor);
            boolean f = false;
            if (lst.getInstructionAt(ad)!=null) {
                CreateFunctionCmd fc = new CreateFunctionCmd(ad);
                f = fc.applyTo(currentProgram, monitor);
            }
            println("EspFnAt: "+ad+" thumb="+thumb+" disasm="+d+" fn="+f);
        }
    }
}
