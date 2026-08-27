// Fix code/data boundary: 0xa2000-0xa2800 is code, not data. Make it exec + disassemble.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.app.cmd.function.CreateFunctionCmd;
public class EspFixBoundary extends GhidraScript {
    public void run() throws Exception {
        Memory mem=currentProgram.getMemory();
        AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        Address split=sp.getAddress(0xa2800L);
        MemoryBlock data=mem.getBlock(sp.getAddress(0xa2000L));
        if (data!=null && data.getName().equals("DATA") && data.contains(split)) {
            mem.split(data, split);
            MemoryBlock code2=mem.getBlock(sp.getAddress(0xa2000L));
            code2.setName("CODE2"); code2.setExecute(true);
            println("split: CODE2 0xa2000-0xa2800 exec, DATA 0xa2800+");
        } else println("already fixed or unexpected: "+(data!=null?data.getName():"null"));
        // disassemble ARM + Thumb prologues in 0xa2000-0xa2800
        Listing lst=currentProgram.getListing();
        int made=0;
        for (long a=0xa2000L; a<0xa2800L; a+=2) {
            Address ad=sp.getAddress(a);
            if (lst.getInstructionAt(ad)!=null||lst.getDefinedDataAt(ad)!=null) continue;
            int hw; try{hw=mem.getShort(ad)&0xFFFF;}catch(Exception e){continue;}
            boolean thumb=(hw&0xFF00)==0xB500;
            boolean arm=false;
            if (a%4==0){ try{ int w=mem.getInt(ad); if((w&0xFFFF0000)==0xE92D0000&&(w&0x4000)!=0) arm=true;}catch(Exception e){} }
            if (thumb||arm){
                ArmDisassembleCommand c=new ArmDisassembleCommand(ad,null,thumb);
                if(c.applyTo(currentProgram,monitor) && lst.getInstructionAt(ad)!=null){
                    if(lst.getFunctionAt(ad)==null){ CreateFunctionCmd f=new CreateFunctionCmd(ad); if(f.applyTo(currentProgram,monitor)) made++; }
                }
            }
        }
        // ensure the known trampoline at 0xa2428 (Thumb) is a function
        Address tr=sp.getAddress(0xa2428L);
        if(lst.getInstructionAt(tr)==null){ new ArmDisassembleCommand(tr,null,true).applyTo(currentProgram,monitor); }
        if(lst.getFunctionAt(tr)==null){ new CreateFunctionCmd(tr).applyTo(currentProgram,monitor); made++; }
        println("functions created in 0xa2000-0xa2800: "+made);
    }
}
