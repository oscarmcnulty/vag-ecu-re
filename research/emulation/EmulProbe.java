// Emulation harness probe: validate the PCode emulator on a known leaf unpacker,
// then (optionally) emulate an init function. Args: <entryHex> [stepBudget]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.math.BigInteger;

public class EmulProbe extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long base,int len){ try{ emu.writeMemory(A(base), new byte[len]); }catch(Exception e){ println("zero fail "+Long.toHexString(base)+": "+e); } }

  public void run() throws Exception {
    String[] args = getScriptArgs();
    long entry = Long.parseLong(args.length>0?args[0]:"801d4a5e",16);
    int budget = args.length>1?Integer.parseInt(args[1]):20000;
    emu = new EmulatorHelper(currentProgram);

    // Map/zero RAM + peripherals so loads don't fault
    zero(0xc0000000L,0x10000); zero(0xc0400000L,0x1000);
    zero(0xd0000000L,0x10000); zero(0xd0400000L,0x1000);
    zero(0xf0000000L,0x20000); zero(0xf0100000L,0x2000); zero(0xf0050000L,0x2000);

    // Fake input frame at 0xd000f800 = bytes 00..07
    byte[] fr=new byte[16]; for(int i=0;i<16;i++) fr[i]=(byte)i;
    emu.writeMemory(A(0xd000f800L), fr);

    // Base registers (from decompiles) + stack + arg + return sentinel
    emu.writeRegister("a0",0xd0008000L);
    emu.writeRegister("a1",0x80048000L);
    emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xd000ff00L);   // SP
    emu.writeRegister("a4",0xd000f800L);     // param_1 (pointer arg)
    emu.writeRegister("d4",0L);
    emu.writeRegister("pc",entry);

    Address next = getFunctionAfter(A(entry))!=null ? getFunctionAfter(A(entry)).getEntryPoint() : A(entry+0x200);
    long lo=entry, hi=next.getOffset();
    println(String.format("entry=%x  fn-range=[%x,%x)  budget=%d", entry, lo, hi, budget));

    int steps=0; String stopReason="budget";
    try {
      for(; steps<budget; steps++){
        long pc = emu.readRegister("pc").longValue();
        if(steps<40) println(String.format("  [%3d] pc=%x", steps, pc));
        if(pc<lo || pc>=hi){ stopReason="left-fn @"+Long.toHexString(pc); break; }
        emu.step(monitor);
      }
    } catch(Exception e){
      long pc = 0; try{ pc=emu.readRegister("pc").longValue(); }catch(Exception e2){}
      stopReason="FAULT @pc="+Long.toHexString(pc)+" : "+e.getMessage();
    }
    println("STOP after "+steps+" steps: "+stopReason);

    // Read the expected output for the leaf validation
    try{
      byte[] o=emu.readMemory(A(0xd000d536L),4);
      println(String.format("d000d536 = %02x %02x %02x %02x  (expect frame[6],frame[7]=06 07 ..)",o[0]&0xff,o[1]&0xff,o[2]&0xff,o[3]&0xff));
    }catch(Exception e){ println("read d536 fail: "+e); }
    emu.dispose();
  }
}
