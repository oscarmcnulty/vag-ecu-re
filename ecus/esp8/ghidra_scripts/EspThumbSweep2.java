// Generalised Thumb / Thumb-2 function recovery.  args: <lo> <hi> (hex, no 0x)
// Prologues: Thumb  PUSH {..,lr} = 0xB5xx
//            Thumb-2 PUSH.W {..,lr} = 0xE92D 0x4xxx  (stored big-endian: e9 2d 4x xx)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspThumbSweep2 extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        long LO = Long.parseLong(a[0],16), HI = Long.parseLong(a[1],16);
        Memory mem = currentProgram.getMemory();
        AddressSpace sp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        Listing lst = currentProgram.getListing();
        int f1=0,f2=0,made=0;
        for (long ad0=LO; ad0<HI; ad0+=2) {
            Address ad = sp.getAddress(ad0);
            if (lst.getInstructionAt(ad)!=null || lst.getDefinedDataAt(ad)!=null) continue;
            int hw;
            try { hw = mem.getShort(ad) & 0xFFFF; } catch(Exception e){ continue; }
            boolean hit=false;
            if ((hw & 0xFF00)==0xB500) { hit=true; f1++; }
            else if (hw==0xE92D) {
                int hw2; try { hw2 = mem.getShort(ad.add(2)) & 0xFFFF; } catch(Exception e){ continue; }
                if ((hw2 & 0xF000)==0x4000) { hit=true; f2++; }
            }
            if (!hit) continue;
            ArmDisassembleCommand cmd = new ArmDisassembleCommand(ad, null, true);
            if (cmd.applyTo(currentProgram, monitor) && lst.getInstructionAt(ad)!=null) {
                if (lst.getFunctionAt(ad)==null) {
                    CreateFunctionCmd fc = new CreateFunctionCmd(ad);
                    if (fc.applyTo(currentProgram, monitor)) made++;
                }
            }
        }
        int tot=0; FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
        while(it.hasNext()){it.next();tot++;}
        println("EspThumbSweep2: PUSH="+f1+" PUSH.W="+f2+" fns_created="+made+" total_now="+tot);
    }
}
