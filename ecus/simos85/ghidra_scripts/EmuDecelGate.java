// Validate that the ACC DECEL enable (d000a582) is gated by the ESP ECD mode byte (d000b296==2),
// and is INDEPENDENT of ego speed inside the engine. Two internal sweeps over 8013c5d4.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.util.*;
public class EmuDecelGate extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  void w16(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v,(byte)(v>>8)}); }
  void w8(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v}); }
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  int rU16(long a){ try{ byte[] b=emu.readMemory(A(a),2); return (b[0]&0xff)|((b[1]&0xff)<<8);}catch(Exception e){return -1;} }
  int rU8(long a){ try{ return emu.readMemory(A(a),1)[0]&0xff;}catch(Exception e){return -1;} }
  byte[] rd(Address a,int n) throws Exception { byte[] b=new byte[n]; currentProgram.getMemory().getBytes(a,b); return b; }
  void mirror(long lo,long hi) throws Exception { for(long a=lo;a<hi;a+=0x1000){int n=(int)Math.min(0x1000,hi-a);
    byte[] b; try{b=rd(A(a),n);}catch(Exception e){continue;} emu.writeMemory(A(0xa0000000L|(a&0x1fffffffL)),b);} }
  void setup(long entry) throws Exception {
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x10000},{0xf0000000L,0x40000},{0xf0100000L,0x10000},{0xe8000000L,0x2000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82; for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",0xd0003ff0L); emu.writeRegister("pc",entry);
  }
  String runOnce(long entry,int ego,int mode,long budget) throws Exception {
    setup(entry); mirror(0x80040000L,0x800a0000L);
    w16(0xd000d644L,ego); w16(0xd000da54L,ego);
    w16(0xd0007bacL,0x7a4);            // positive accel request present
    w8(0xd000b296L,mode);              // ECD master-request mode (2 = ECD available & decel active)
    w8(0xd000b29cL,1);                 // -> bVar1=true branch (driver-brake path off)
    w16(0xc00010b8L,0);                // < cal 0x8004302a so the a582 magnitude term passes
    w8(0xd000a757L,1);                 // LV_DCC_ENA (ACC coded)
    w8(0xd000ad0fL,1);                 // ACC/cruise active master flag (else fn early-returns)
    long SENT=0xd0003ff0L; long steps=0,pc=0; String stop="budget";
    try{ for(;steps<budget;steps++){ pc=emu.readRegister("pc").longValue();
      if(pc==SENT){stop="RET";break;} if(pc<0x80020000L||pc>=0x80200000L){stop="left@"+Long.toHexString(pc);break;} emu.step(monitor);} }
    catch(Exception e){ stop="FAULT@"+Long.toHexString(pc); }
    return String.format("a582=%d c9a=0x%04x c00010b8=%d(<%d?) b28c=%d [%d %s]", rU8(0xd000a582L), rU16(0xd0007c9aL), rU16(0xc00010b8L), rU16(0x8004302aL), rU8(0xd000b28cL), steps, stop);
  }
  public void run() throws Exception {
    long entry=0x8013c5d4L, budget=6000000L;
    emu=new EmulatorHelper(currentProgram);
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){public void write(int b){}})); }catch(Throwable t){}
    println("=== EmuDecelGate 8013c5d4: a582 = ACC decel enable ===");
    println("-- Sweep A: ego fixed 10 km/h, vary ECD mode b296 --");
    for(int m: new int[]{0,1,2}) println(String.format("  b296=%d (ego=10) -> %s", m, runOnce(entry,10*128,m,budget)));
    println("-- Sweep B: ECD mode fixed =2 (available), vary ego speed --");
    for(int kv: new int[]{2,5,10,14,20}) println(String.format("  ego=%2d km/h (b296=2) -> %s", kv, runOnce(entry,kv*128,2,budget)));
    emu.dispose();
  }
}
