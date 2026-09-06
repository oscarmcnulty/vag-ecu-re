// Emulate the REAL ACC_01 (0x109) RX decoder (canrx_ACC_01_DCC1_109 @0x801383e8) on a crafted,
// E2E-valid frame carrying a positive acceleration command, then chain the decoded signal into the
// torque controller across an ego-speed sweep -- the ingress->consume longitudinal pipeline on real code.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.util.*;
public class EmuAccIngress extends GhidraScript {
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
  String runTo(long budget) throws Exception {
    long SENT=0xd0003ff0L; long steps=0,pc=0; String stop="budget";
    try{ for(;steps<budget;steps++){ pc=emu.readRegister("pc").longValue();
      if(pc==SENT){stop="RET";break;} if(pc<0x80020000L||pc>=0x80200000L){stop="left@"+Long.toHexString(pc);break;} emu.step(monitor);} }
    catch(Exception e){ stop="FAULT@"+Long.toHexString(pc); }
    return steps+" "+stop;
  }
  public void run() throws Exception {
    emu=new EmulatorHelper(currentProgram);
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){public void write(int b){}})); }catch(Throwable t){}
    // crafted ACC_01 frame: XOR-all==8, byte1 low-nibble nonzero (first-frame sync), +1.0 m/s2 accel
    // d0007bac = (b4&7)<<8|b3 = 0x66c = 1644 ; phys = 1644*0.005 - 7.22 = +1.0 m/s2
    byte[] frame = {(byte)0x73,(byte)0x01,(byte)0x00,(byte)0x6c,(byte)0x06,(byte)0x00,(byte)0x00,(byte)0x10};
    long FB=0xd0003f00L;
    println("=== EmuAccIngress: RX-decode 0x109 then chain to torque PI ===");
    int xor=0; for(byte b:frame) xor^=(b&0xff);
    println(String.format("frame = 73 01 00 6c 06 00 00 10 ; XOR-all=0x%02x (E2E needs 0x08)", xor));

    // --- link 1: run the real RX decoder 801383e8 on the frame ---
    setup(0x801383e8L); mirror(0x80040000L,0x800a0000L);
    emu.writeMemory(A(FB),frame); emu.writeRegister("a4",FB); emu.writeRegister("d4",FB);
    String r1=runTo(2000000L);
    int bac=rU16(0xd0007bacL), a7ae=rU8(0xd000a7aeL), b06a=rU8(0xd000b06aL), b057=rU8(0xd000b057L), a3c0=rU8(0xd000a3c0L);
    double phys = bac*0.005 - 7.22;
    println(String.format("LINK1 RX-decode [%s]: d0007bac=0x%03x (=%+.2f m/s2)  ACC_Anhalten=%d  Dynamik=%d  Status_ACC=%d  E2E_err(a3c0)=%d",
        r1, bac, phys, a7ae, b06a, b057, a3c0));
    if(bac!=0x66c) { println("  (decode did not land expected 0x66c -- check E2E/counter gate)"); }

    // --- link 2: chain decoded accel into the torque PI 801e9b86 across an ego-speed sweep ---
    println("LINK2 torque PI 801e9b86 fed the decoded accel, ego sweep:");
    int savedBac = bac;
    for(int kv: new int[]{2,5,10,14,20}){
      setup(0x801e9b86L); mirror(0x80040000L,0x800a0000L);
      w16(0xd0007bacL, savedBac==0?0x66c:savedBac);   // decoded positive accel carried forward
      w16(0xd000d644L, kv*128); w16(0xd000da54L, kv*128);
      w8(0xd000d5c5L,0); w8(0xd000d656L,0); w8(0xd000d657L,0); w8(0xd000d62aL,200);
      w16(0xd000d5e4L,50); w16(0xd000d5e8L,60); w16(0xd000e2e8L,0); w8(0xd000d60dL,1); w8(0xd000d606L,10);
      String r=runTo(4000000L);
      println(String.format("  ego=%2d km/h -> e2c5(standstill)=%d  e2e8(torqOut)=%d  [%s]",
          kv, rU8(0xd000e2c5L), rU16(0xd000e2e8L), r));
    }
    emu.dispose();
  }
}
