// Recover ARM functions: find STMFD sp!,{...,lr} prologues in undefined code, disasm + create.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspSweep extends GhidraScript {
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing lst = currentProgram.getListing();
        long LO=0x0, HI=0xa2000;
        int found=0, disasm=0, madeFn=0;
        for (long a=LO; a<HI; a+=4) {
            Address ad = sp.getAddress(a);
            // only in an initialized, currently-undefined spot
            if (lst.getInstructionAt(ad)!=null) continue;
            if (lst.getDefinedDataAt(ad)!=null) continue;
            int wrd;
            try { wrd = mem.getInt(ad); } catch(Exception e){ continue; }
            // STMFD sp!,{...,lr}: 0xE92D_xxxx with LR bit (0x4000) set
            if ((wrd & 0xFFFF0000)==0xE92D0000 && (wrd & 0x4000)!=0) {
                found++;
                ArmDisassembleCommand cmd = new ArmDisassembleCommand(ad, null, false);
                if (cmd.applyTo(currentProgram, monitor)) {
                    disasm++;
                    if (lst.getFunctionAt(ad)==null) {
                        CreateFunctionCmd fc = new CreateFunctionCmd(ad);
                        if (fc.applyTo(currentProgram, monitor)) madeFn++;
                    }
                }
            }
        }
        println("prologues found="+found+" disasm_ok="+disasm+" functions_created="+madeFn);
        // report new total
        int tot=0; FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
        while(it.hasNext()){it.next();tot++;}
        println("total functions now: "+tot);
    }
}
