import ghidra.app.emulator.EmulatorHelper;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

// EmuDispatch.java -- prove the RTOS statechart/task DISPATCH site by execution.
// FUN_0002de6e ends with:  (**(code**)((&DAT_fffee0dc)[idx] + 0xc))();
// i.e. it calls the task body through the function-pointer field at offset +0xc of the
// selected task-control-block (TCB), the TCB pointer taken from the array @0xfffee0dc[idx].
// We plant a synthetic TCB whose +0xc field = 0x0002b626 (the state-5/active entry, used purely
// as a distinctive marker), arm the scheduler's "ready" bookkeeping, run, and confirm the
// emulator's PC actually reaches 0x0002b626 -> the indirect target resolved to the planted value.
public class EmuDispatch extends GhidraScript {
  static final long GP=0xFFFF0000L, TP=0x0001A238L, CTBP=0x0003F272L, SP=0xFFFFEFF0L, EP=0xFFFE0000L;
  static final long DISP  = 0x0002de6eL;
  static final long ARR   = 0xFFFEE0DCL;   // DAT_fffee0dc: array of TCB pointers
  static final long TCB   = 0xFFFE1000L;   // our synthetic TCB
  static final long FE=0xFFFEE0FEL, FC=0xFFFEE0FCL, FD=0xFFFEE0FDL, FF=0xFFFEE0FFL;
  static final long CNTB  = 0xFFFEE109L;   // DAT_fffee108._1_1_
  static final long MARK  = 0x0002b626L;   // planted function pointer (distinctive)
  static final long SENT  = 0x00FFFFFEL;

  public void run() throws Exception {
    EmulatorHelper emu = new EmulatorHelper(currentProgram);
    emu.writeRegister("gp",GP); emu.writeRegister("tp",TP); emu.writeRegister("sp",SP);
    emu.writeRegister("ep",EP); emu.writeRegister("lp",SENT);
    try { emu.writeRegister("ctbp",CTBP); } catch(Exception e){}
    try { emu.writeRegister("psw",0xC0); } catch(Exception e){ println("psw set warn: "+e); }
    emu.writeRegister("pc", DISP);

    // scheduler bookkeeping so the dispatch path is taken:
    emu.writeMemoryValue(toAddr(ARR), 4, TCB);   // TCB[0] = &synthTCB
    emu.writeMemoryValue(toAddr(FE), 1, 0);       // ready index = 0
    emu.writeMemoryValue(toAddr(FC), 1, 0);       // current index = 0
    emu.writeMemoryValue(toAddr(FD), 1, 5);       // fd > ff  => no early return
    emu.writeMemoryValue(toAddr(FF), 1, 1);
    emu.writeMemoryValue(toAddr(CNTB), 1, 0);     // history counter < 8

    // synthetic TCB fields
    emu.writeMemoryValue(toAddr(TCB+0), 1, 5);    // priority
    emu.writeMemoryValue(toAddr(TCB+1), 1, 2);    // state
    emu.writeMemoryValue(toAddr(TCB+2), 1, 0x00); // flag != 0x10
    emu.writeMemoryValue(toAddr(TCB+0xc), 4, MARK); // <-- the function pointer we expect called

    emu.setBreakpoint(toAddr(MARK));
    emu.setBreakpoint(toAddr(SENT));
    boolean ok = false;
    for (int i=0;i<20000;i++){
      long pc = emu.readRegister("pc").longValue() & 0xffffffffL;
      if (pc==MARK){ ok=true; break; }
      if (pc==SENT) break;
      Instruction in = getInstructionAt(toAddr(pc));
      if (in==null){ println("no instr @"+Long.toHexString(pc)); break; }
      String m = in.getMnemonicString().toLowerCase();
      if (m.equals("di")||m.equals("ei")){ emu.writeRegister("pc", pc+in.getLength()); continue; }
      emu.step(monitor);
    }
    long endpc = emu.readRegister("pc").longValue() & 0xffffffffL;
    println("=== EmuDispatch ===");
    println("planted TCB+0xc = 0x"+Long.toHexString(MARK));
    println("dispatcher resolved indirect call -> PC reached 0x"+Long.toHexString(endpc)
            +"   "+(ok? "MATCH (mechanism proven: (**(code**)(TCB+0xc))())" : "NO-MATCH"));
    emu.dispose();
  }
}
