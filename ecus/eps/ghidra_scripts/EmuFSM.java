import ghidra.app.emulator.EmulatorHelper;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import java.math.BigInteger;

// EmuFSM.java  -- p-code emulate the Audi 8R EPS engage-statechart pieces (V850E, LE, base 0).
// Purpose: prove, by ACTUAL EXECUTION, (a) each state-entry function's state-id write to
// hca_engage_fsm_state @0xfffede5c and its dwell-target write @0xfffede74, and (b) the RTOS
// indirect dispatch site FUN_0002de6e -> (**(code**)(TCB+0xc))().
//
// Calls out of the target function body are STUBBED (return 0) so setup subroutines that touch
// unmodelled peripherals don't derail the run; the state/dwell writes we care about are inline
// immediates that execute regardless. gp/tp/ctbp/sp seeded from crt0.
public class EmuFSM extends GhidraScript {
  static final long GP    = 0xFFFF0000L;
  static final long TP    = 0x0001A238L;
  static final long CTBP  = 0x0003F272L;
  static final long SP    = 0xFFFFEFF0L;
  static final long EP    = 0xFFFE0000L;
  static final long SENT  = 0x00FFFFFEL;   // sentinel return addr (breakpoint)
  static final long STATE = 0xFFFEDE5CL;   // hca_engage_fsm_state (u32)
  static final long DTGT  = 0xFFFEDE74L;   // hca_dwell_target (u16)
  static final long DCNT  = 0xFFFEDE72L;   // hca_dwell_counter (u16)
  static final long DWALK = 0xFFFEDE70L;   // down-walk counter (u8)

  long[] entries = {0x2b458L,0x2b45eL,0x2b49aL,0x2b5c4L,0x2b5f8L,0x2b626L,
                    0x2b66aL,0x2b706L,0x2b73aL,0x2b778L,0x2b7e4L,0x2b8b4L};

  EmulatorHelper emu;

  void seed(long entry) throws Exception {
    emu.writeRegister("gp", GP);
    emu.writeRegister("tp", TP);
    emu.writeRegister("sp", SP);
    emu.writeRegister("ep", EP);
    emu.writeRegister("lp", SENT);
    try { emu.writeRegister("ctbp", CTBP); } catch (Exception e) {}
    emu.writeRegister("pc", entry);
    // clear the observed RAM cells
    emu.writeMemoryValue(toAddr(STATE), 4, 0xEEEEEEEEL);
    emu.writeMemoryValue(toAddr(DTGT), 2, 0);
    emu.writeMemoryValue(toAddr(DCNT), 2, 0);
    emu.writeMemoryValue(toAddr(DWALK), 1, 0);
  }

  long runFn(long entry) throws Exception {
    seed(entry);
    long lo = entry, hi = entry + 0x320;
    for (int i = 0; i < 4000; i++) {
      long pc = emu.readRegister("pc").longValue() & 0xffffffffL;
      if (pc == SENT) return i;
      Instruction in = getInstructionAt(toAddr(pc));
      if (in == null) return -1;
      String m = in.getMnemonicString().toLowerCase();
      boolean isCall = in.getFlowType().isCall();
      if (isCall) {
        // stub any call whose target leaves the function body
        Address[] fl = in.getFlows();
        boolean out = true;
        if (fl != null) for (Address a : fl) { long t=a.getOffset(); if (t>=lo && t<hi) out=false; }
        if (m.equals("callt")) out = true;                 // callt thunks: always stub
        if (out) {
          emu.writeRegister("r10", 0);                     // fake return value
          long nxt = pc + in.getLength();
          emu.writeRegister("pc", nxt);
          continue;
        }
      }
      emu.step(monitor);
    }
    return -2;
  }

  long rd(long a, int sz) throws Exception {
    byte[] b = emu.readMemory(toAddr(a), sz);
    long v = 0; for (int i=sz-1;i>=0;i--) v = (v<<8) | (b[i]&0xff);
    return v;
  }

  public void run() throws Exception {
    emu = new EmulatorHelper(currentProgram);
    println("=== EmuFSM: engage-FSM entry functions (state id + dwell target) ===");
    int[] stnum = {0,1,2,3,4,5,6,7,8,9,0xa,0xb};
    for (int k=0;k<entries.length;k++) {
      long steps = runFn(entries[k]);
      long st = rd(STATE,4), tgt = rd(DTGT,2), cnt = rd(DCNT,2), dw = rd(DWALK,1);
      println(String.format("entry@%06x  exp_state=%2d  ->  hca_engage_fsm_state=%s  dwell_target=%d  dwell_cnt=%d  downwalk=%d  (steps=%d)",
        entries[k], stnum[k],
        (st==0xEEEEEEEEL? "<unwritten>" : Long.toString(st)),
        tgt, cnt, dw, steps));
    }
    emu.dispose();
    println("=== EmuFSM done ===");
  }
}
