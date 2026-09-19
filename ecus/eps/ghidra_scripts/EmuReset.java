import ghidra.app.emulator.EmulatorHelper;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

// EmuReset.java -- p-code emulate the engage-FSM DOWN-WALK debounce components to pin the
// 6-min-counter reset timing BY EXECUTION (V850E LE base 0). Complements EmuFSM (entry-actions).
//   test A: op_mode-wait during-action FUN_0002be3a -- hold op_mode!=3, count ticks until it
//           posts the 0x105 timeout event; proves hca_engage_opmode_wait (fffede78) saturates at 0x28=40.
//   test B: state-1 during FUN_0002ba40 -- proves state-1 pre-debounce fffede70 counts down from 10.
//   test C: active during FUN_0002be80 -- confirms it only ++ the 6-min counter (no exit gate).
public class EmuReset extends GhidraScript {
  static final long GP=0xFFFF0000L, TP=0x0001A238L, CTBP=0x0003F272L, SP=0xFFFFEFF0L, EP=0xFFFE0000L;
  static final long SENT=0x00FFFFFEL;
  static final long OPMODE=0xFFFEC0ECL;      // _op_mode (resolved below from symbol if present)
  static final long OPWAIT=0xFFFEDE78L;      // hca_engage_opmode_wait
  static final long DWALK =0xFFFEDE70L;      // state-1 pre-debounce
  static final long TCNT  =0xFFFEDE84L;      // hca_engage_time_counter (6-min)
  EmulatorHelper emu;

  void seed(long entry){
    emu.writeRegister("gp",GP); emu.writeRegister("tp",TP); emu.writeRegister("sp",SP);
    emu.writeRegister("ep",EP); emu.writeRegister("lp",SENT);
    try{emu.writeRegister("ctbp",CTBP);}catch(Exception e){}
    emu.writeRegister("pc",entry);
  }
  // run one call of `entry` to completion (stub out-of-body calls), return #steps
  int runOnce(long entry) throws Exception {
    seed(entry);
    long lo=entry, hi=entry+0x400;
    for(int i=0;i<6000;i++){
      long pc=emu.readRegister("pc").longValue()&0xffffffffL;
      if(pc==SENT) return i;
      Instruction in=getInstructionAt(toAddr(pc));
      if(in==null) return -1;
      if(in.getFlowType().isCall()){
        Address[] fl=in.getFlows(); boolean out=true;
        if(fl!=null) for(Address a:fl){long t=a.getOffset(); if(t>=lo&&t<hi) out=false;}
        if(in.getMnemonicString().equalsIgnoreCase("callt")) out=true;
        if(out){ emu.writeRegister("r10",0); emu.writeRegister("pc",pc+in.getLength()); continue; }
      }
      emu.step(monitor);
    }
    return -2;
  }
  long rd(long a,int sz) throws Exception { byte[] b=emu.readMemory(toAddr(a),sz); long v=0; for(int i=sz-1;i>=0;i--) v=(v<<8)|(b[i]&0xff); return v; }
  void wr(long a,int sz,long v){ emu.writeMemoryValue(toAddr(a),sz,v); }

  public void run() throws Exception {
    emu=new EmulatorHelper(currentProgram);
    // resolve _op_mode symbol if labeled
    long opmode=OPMODE;
    try{ ghidra.program.model.symbol.Symbol s=getSymbols("op_mode",null).get(0); opmode=s.getAddress().getOffset(); }catch(Exception e){}
    println("=== EmuReset: engage-FSM down-walk debounce (by execution) ===");
    println("op_mode @ 0x"+Long.toHexString(opmode));

    // TEST A: op_mode-wait FUN_0002be3a with op_mode held !=3 -> count ticks to 0x28 saturate.
    wr(opmode,1,0); wr(OPWAIT,1,0);
    int satTick=-1;
    for(int t=1;t<=60;t++){
      runOnce(0x2be3aL);
      long w=rd(OPWAIT,1);
      if(w>=0x28 && satTick<0) satTick=t;
    }
    println("TEST A op_mode-wait: hca_engage_opmode_wait saturated at count 0x"+Long.toHexString(rd(OPWAIT,1))
      +" ; ticks-to-0x28 = "+satTick+"  (x2.016ms = "+String.format("%.1f",satTick*2.016)+" ms)");

    // control: op_mode==3 -> should advance immediately, wait stays 0
    wr(opmode,1,3); wr(OPWAIT,1,0); runOnce(0x2be3aL);
    println("TEST A ctrl (op_mode==3): opmode-wait after 1 tick = "+rd(OPWAIT,1)+" (expect 0 = immediate advance)");

    // TEST B: state-1 during FUN_0002ba40 -> fffede70 counts down from 10
    wr(DWALK,1,10);
    int b=-1;
    for(int t=1;t<=20;t++){ runOnce(0x2ba40L); if(rd(DWALK,1)==0 && b<0) b=t; }
    println("TEST B state-1 pre-debounce fffede70: reached 0 after "+b+" ticks (seeded 10)");

    // TEST C: active during FUN_0002be80 -> only increments the 6-min counter
    wr(TCNT,4,1000); runOnce(0x2be80L);
    println("TEST C active-during: 6-min counter 1000 -> "+rd(TCNT,4)+" (expect 1001; confirms no exit gate here)");
    println("=== EmuReset done ===");
    emu.dispose();
  }
}
