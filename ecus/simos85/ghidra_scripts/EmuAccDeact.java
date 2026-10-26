// Validate the sub-15 km/h ACC accel-loss mechanism + the proposed cal fix, by emulating the CRUC
// state machine 8013ef46 (which internally calls the transition dispatcher 8013e8aa) over several cycles.
// Hypothesis: a5a2 (d000a5a2) = debounced ESP ECD_nicht_verfuegbar is the SOLE CRUC inhibit input that
// fires below ~15 km/h. It sets d0001169 bit 0x04 -> d0001160 = d1169 & cal 0x80043422 (0xEF) ->
// condition-word inhibit bit -> CRUC leaves {1,5} -> a5ac clears -> ACC engine torque withdrawn.
// Fix: cal 0x80043422 0xEF->0xEB drops bit 0x04 so a5a2 no longer deactivates ACC.
// Method: hold the machine in state 1, re-assert the external inputs each cycle, and run N cycles.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
public class EmuAccDeact extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  void w16(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v,(byte)(v>>8)}); }
  void w8(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v}); }
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  int rU8(long a){ try{ return emu.readMemory(A(a),1)[0]&0xff;}catch(Exception e){return -1;} }
  byte[] rd(Address a,int n) throws Exception { byte[] b=new byte[n]; currentProgram.getMemory().getBytes(a,b); return b; }
  void mirror(long lo,long hi) throws Exception { for(long a=lo;a<hi;a+=0x1000){int n=(int)Math.min(0x1000,hi-a);
    byte[] b; try{b=rd(A(a),n);}catch(Exception e){continue;} emu.writeMemory(A(0xa0000000L|(a&0x1fffffffL)),b);} }
  void zeroRam() {
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x10000},{0xf0000000L,0x40000},{0xf0100000L,0x10000},{0xe8000000L,0x2000}}) zero(r[0],(int)r[1]);
  }
  void resetRegs(long entry) throws Exception {
    long csa=0xd0004000L; int n=82; for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",0xd0003ff0L); emu.writeRegister("pc",entry);
  }
  // external inputs produced by OTHER modules each cycle (re-asserted every cycle); internal state is NOT touched
  void inputs(int a5a2,int calByte) throws Exception {
    w8(0xd000ad0fL,1); w8(0xd000a757L,1); w8(0xd000a5a8L,0); w8(0xd000a756L,0);
    w8(0xd000b297L,1); w8(0xd000a594L,1); w8(0xd000a55dL,0); w8(0xd000a5a5L,0); w8(0xd000a587L,1);
    w8(0xd000b296L,0); w8(0xd000b298L,1); w8(0xd000a335L,0); w8(0xd000b1c7L,0); w8(0xd000b29cL,1);
    w8(0xd000a59cL,0); w16(0xd0007e84L,0); w8(0xd000118aL,1);
    for(long a=0xd00086acL;a<=0xd00086b4L;a++) w8(a,0xff);   // DCC-enable port (clears inhibit bit 0x40)
    w8(0xd000a5a2L,a5a2);
    if(calByte>=0){ w8(0x80043422L,calByte); w8(0xa0043422L,calByte); }
  }
  int oneCycle(long budget) throws Exception {
    resetRegs(0x8013ef46L);
    long SENT=0xd0003ff0L; long steps=0,pc=0;
    try{ for(;steps<budget;steps++){ pc=emu.readRegister("pc").longValue();
      if(pc==SENT) break; if(pc<0x80020000L||pc>=0x80200000L) break; emu.step(monitor);} }
    catch(Exception e){}
    return rU8(0xd000b28eL);  // STATE_CRU_CTL
  }
  String run3(int a5a2,int calByte,int cycles,long budget) throws Exception {
    zeroRam(); mirror(0x80040000L,0x800a0000L);
    inputs(a5a2,calByte);
    // seed: already regulating in state 1 (stable shadow)
    w8(0xd0001165L,1); w8(0xd0001166L,1); w8(0xd000b28eL,1); w8(0xd000b28fL,1); w8(0xd000b28dL,1);
    StringBuilder seq=new StringBuilder();
    int st=1;
    for(int c=0;c<cycles;c++){ inputs(a5a2,calByte); st=oneCycle(budget); seq.append(st); }
    String verdict = (st==1||st==2||st==5)?"REGULATING(accel alive)":(st==0?"OFF(no accel)":(st==6?"blend-out":"state"+st));
    return String.format("STATE seq=%s  final=%d [%s]  d1160=0x%02x d1169=0x%02x (calByte=0x%02x)",
      seq, st, verdict, rU8(0xd0001160L), rU8(0xd0001169L), rU8(0x80043422L));
  }
  public void run() throws Exception {
    long budget=14000000L; int N=8;
    emu=new EmulatorHelper(currentProgram);
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){public void write(int b){}})); }catch(Throwable t){}
    println("=== EmuAccDeact 8013ef46 ("+N+" cycles): does a5a2(ECD) deactivate the CRUC, and does cal 0x80043422 fix it? ===");
    println("  baseline  a5a2=0, stock cal   -> "+run3(0,-1,N,budget));
    println("  ECD set   a5a2=1, stock 0xEF  -> "+run3(1,0xEF,N,budget));
    println("  ECD + FIX a5a2=1, cal 0xEB    -> "+run3(1,0xEB,N,budget));
    emu.dispose();
  }
}
