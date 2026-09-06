// Multi-cycle emulation of egas_l2_cruise_torque_monitor (0x8009c0b4) to test whether it latches
// a040/a03c/a03b (-> status 3) when ARMED (ACC_Status_ACC=3) with an engine-torque request present.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.util.*;
public class EmuL2Torque extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  void w16(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v,(byte)(v>>8)}); }
  void w8(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v}); }
  int rU8(long a){ try{ return emu.readMemory(A(a),1)[0]&0xff;}catch(Exception e){return -1;} }
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  byte[] rd(Address a,int n) throws Exception { byte[] b=new byte[n]; currentProgram.getMemory().getBytes(a,b); return b; }
  void mirror(long lo,long hi) throws Exception { for(long a=lo;a<hi;a+=0x1000){int n=(int)Math.min(0x1000,hi-a);
    byte[] b; try{b=rd(A(a),n);}catch(Exception e){continue;} emu.writeMemory(A(0xa0000000L|(a&0x1fffffffL)),b);} }
  long SENT=0xd0003ff0L;
  void csaBase() throws Exception {
    long csa=0xd0004000L; int n=82; for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",SENT);
  }
  boolean runTo(long entry,long budget) throws Exception {
    emu.writeRegister("pc",entry); long steps=0,pc=0;
    try{ for(;steps<budget;steps++){ pc=emu.readRegister("pc").longValue();
      if(pc==SENT) return true; if(pc<0x80020000L||pc>=0x80200000L) return false; emu.step(monitor);} }
    catch(Throwable e){ return false; }
    return false;
  }
  public void run() throws Exception {
    String[] args=getScriptArgs();
    int torqueHi = args.length>0?(int)(long)Long.decode(args[0]):0x20;   // acc_engine_torque_request>>8
    emu=new EmulatorHelper(currentProgram);
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){public void write(int b){}})); }catch(Throwable t){}
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x400000},{0xd0000000L,0x20000},{0xd4000000L,0x10000},
        {0xf0000000L,0x40000},{0xf0100000L,0x10000},{0xe8000000L,0x2000}}) zero(r[0],(int)r[1]);
    csaBase(); mirror(0x80040000L,0x800a0000L);
    // --- ARMED state ---
    w8(0xd000b057L,3);              // acc_ACC_Status_ACC = 3 (armed)
    w8(0xd000a03fL,0);              // torque-plausibility flag = 0 (not disarmed)
    w8(0xd000ae80L,0xff);           // arming counter >= cal(=0)
    w8(0xd000b28fL,0);              // STATE_CRU_CTL_long_substate != cal(=3)
    w8(0xd000a08bL,1);              // monitor-enable gate (else goto LAB_8009cf76)
    w8(0xd000a03eL,1); w8(0xd000191aL,0xfe);  // cVar7 arming-enable + its ^0xff ASIL shadow
    w16(0xd0007ce0L, (torqueHi&0xff)<<8);  // acc_engine_torque_request (hi byte = requested)
    // permission timers low so they expire -> permitted forced to 0
    for(long t: new long[]{0xd0001845L,0xd0001846L,0xd0001847L,0xd0001840L,0xd0001842L}) w8(t,2);
    println(String.format("=== EmuL2Torque: armed (Status=3), torque_req_hi=0x%02x, 50 cycles ===",torqueHi&0xff));
    println("cyc | a040 a03c d1856 a03b a04e a03e | ae35(dbnc) t1845 t1846 t1847");
    long entry=0x8009c0b4L;
    for(int cyc=0;cyc<50;cyc++){
      csaBase();
      // FORCE permission-denied: hold the permit timers at 0 so permitted<requested each cycle
      for(long t: new long[]{0xd0001845L,0xd0001846L,0xd0001847L}) w8(t,0);
      boolean ret=runTo(entry, 3000000L);
      int a040=rU8(0xd000a040L),a03c=rU8(0xd000a03cL),d1856=rU8(0xd0001856L),a03b=rU8(0xd000a03bL),a04e=rU8(0xd000a04eL),a03e=rU8(0xd000a03eL);
      int ae35=rU8(0xd000ae35L),t45=rU8(0xd0001845L),t46=rU8(0xd0001846L),t47=rU8(0xd0001847L);
      if(cyc<12 || a040==1||a03c==1||a03b==1||d1856==1 || cyc%5==0)
        println(String.format("%3d | %4d %4d %5d %4d %4d %4d | %5d %5d %5d %5d %s",
          cyc,a040,a03c,d1856,a03b,a04e,a03e, ae35,t45,t46,t47, ret?"":"(no-ret)"));
      if(a03b==1){ println("  >>> a03b LATCHED at cycle "+cyc+" -> Route A status 3"); break; }
    }
    emu.dispose();
  }
}
