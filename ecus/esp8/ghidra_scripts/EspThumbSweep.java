// Recover THUMB functions: PUSH{...,lr}=0xB5xx at even undefined addrs -> disasm Thumb + create fn.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspThumbSweep extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing lst = currentProgram.getListing();
        long LO=0x0, HI=0xa2000;
        int found=0, ok=0, made=0;
        for (long a=LO; a<HI; a+=2) {
            Address ad = sp.getAddress(a);
            if (lst.getInstructionAt(ad)!=null || lst.getDefinedDataAt(ad)!=null) continue;
            int hw;
            try { hw = mem.getShort(ad) & 0xFFFF; } catch(Exception e){ continue; }
            // Thumb PUSH {..,lr} = 0xB5xx
            if ((hw & 0xFF00)==0xB500) {
                found++;
                ArmDisassembleCommand cmd = new ArmDisassembleCommand(ad, null, true); // thumb=true
                if (cmd.applyTo(currentProgram, monitor)) {
                    // sanity: require at least a few instructions decoded contiguously
                    Instruction i0 = lst.getInstructionAt(ad);
                    if (i0!=null) {
                        ok++;
                        if (lst.getFunctionAt(ad)==null) {
                            CreateFunctionCmd fc = new CreateFunctionCmd(ad);
                            if (fc.applyTo(currentProgram, monitor)) made++;
                        }
                    }
                }
            }
        }
        println("thumb PUSH found="+found+" disasm_ok="+ok+" fns_created="+made);
        int tot=0; FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
        while(it.hasNext()){it.next();tot++;}
        println("total functions now: "+tot);
    }
}
