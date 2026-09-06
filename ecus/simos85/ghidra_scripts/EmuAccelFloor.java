// Validate the sub-15 km/h ACCELERATION path in Simos8.5.
// Runs a target function to completion at a swept ego speed, mirrors the flash cal
// window into the 0xa0 uncached alias (so cal pointer derefs resolve), watches which
// speed-floor cal addresses get read, and dumps the near-standstill gate + torque outputs.
// Args: <entryHex> [budget]   (ego-speed sweep is internal)
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmuAccelFloor extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  void w16(long a,int v) throws Exception { byte[] b=new byte[2]; b[0]=(byte)v; b[1]=(byte)(v>>8); emu.writeMemory(A(a),b);}
  void w8(long a,int v) throws Exception { emu.writeMemory(A(a),new byte[]{(byte)v}); }
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a){ try{ byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}catch(Exception e){return -1;} }
  int rU16(long a){ try{ byte[] b=emu.readMemory(A(a),2); return (b[0]&0xff)|((b[1]&0xff)<<8);}catch(Exception e){return -1;} }
  int rU8(long a){ try{ return emu.readMemory(A(a),1)[0]&0xff;}catch(Exception e){return -1;} }
  long rreg(String r){ try{ return emu.readRegister(r).longValue(); }catch(Throwable t){ return -1; } }

  // mirror flash [lo,hi) into the 0xa0-uncached alias so *(0xa00xxxxx) derefs resolve
  void mirrorFlash(long lo,long hi) throws Exception {
    int chunk=0x1000;
    for(long a=lo;a<hi;a+=chunk){ int n=(int)Math.min(chunk,hi-a);
      byte[] b=new byte[n]; try{ b=rdBytes(A(a),n);}catch(Exception e){ continue; }
      emu.writeMemory(A(0xa0000000L|(a&0x1fffffffL)),b); }
  }
  byte[] rdBytes(Address a,int n) throws Exception { byte[] b=new byte[n]; currentProgram.getMemory().getBytes(a,b); return b; }

  long loadEA(long pc){
    Instruction in=getInstructionAt(A(pc)); if(in==null) return -1;
    if(!in.getMnemonicString().toLowerCase().startsWith("ld")) return -1;
    for(int o=0;o<in.getNumOperands();o++){
      Object[] objs=in.getOpObjects(o); Register base=null; long disp=0; boolean hasScalar=false;
      for(Object x:objs){ if(x instanceof Register) base=(Register)x; else if(x instanceof Scalar){ disp=((Scalar)x).getSignedValue(); hasScalar=true; } }
      if(base!=null){ try{ return emu.readRegister(base).longValue()+disp; }catch(Exception e){} }
      if(hasScalar && disp!=0) return disp;
    }
    return -1;
  }
  long canon(long a){ return (a>=0xa0000000L&&a<0xc0000000L)?(0x80000000L|(a&0x1fffffffL)):a; }

  void baseSetup(long entry) throws Exception {
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x10000},{0xf0000000L,0x40000},{0xf0100000L,0x10000},{0xe8000000L,0x2000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    for(String csr: new String[]{"ICR","ISP","BIV","BTV","PSW","SYSCON"}) try{ emu.writeRegister(csr,0L);}catch(Throwable t){}
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);
  }

  // watchlist of speed-floor cals (canonical 0x80 form)
  long[] WATCH = {0x8007a26aL /*C_VS_MIN_CRU 3.0*/, 0x80079536L /*creep 3.0*/,
                  0x800794efL,0x800794f2L /*L2 crawl 15*/, 0x8007a204L /*PI cal base*/, 0x800793a0L /*mon cal base*/,
                  0xd000d644L /*ego working*/, 0xd000da54L /*ego monitor*/};

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    long budget=args.length>1?Long.parseLong(args[1]):4000000L;
    long SENT=0xd0003ff0L;
    emu=new EmulatorHelper(currentProgram);
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}

    // ego speeds in 1/128 km/h: 0, 2, 3(=384), 5, 10, 14, 20 km/h
    int[] kmh = {0,2,3,4,5,10,14,20};
    println(String.format("=== EmuAccelFloor entry=%x budget=%d ===",entry,budget));
    println("ego_kmh | e2c5(stst) e2e8(torqOut) e2e2 e2ec e2f0 e2c1 e2c4 | read15? read3? | steps stop");
    for(int kv: kmh){
      int ego = kv*128;
      baseSetup(entry);
      mirrorFlash(0x80040000L,0x800a0000L);   // cal + pointer table region into 0xa0 alias
      // --- input state: cruise "regulating", positive accel request, chosen ego speed ---
      w16(0xd000d644L, ego); w16(0xd000da54L, ego);      // ego working + monitor copies
      w16(0xd0007bacL, 0x7a4);                            // ACC_Sollbeschleunigung (>0x5a4 default => accel)
      // guard inputs for the near-standstill compare (line 291-293): make the chain reachable.
      // gate = cVar14(=e2c1) && d5c5==0 && e2c4==0 && d656==0 && (ego < cal 0x8007a26a=384 [3.0km/h])
      w8(0xd000d5c5L,0); w8(0xd000d656L,0); w8(0xd000d657L,0);   // d5c5/d656 must be 0
      w8(0xd000d62aL,200);                                // > cal[base+0x41]=128 -> standstill flag true when ego<3
      w16(0xd000d5e4L, 50); w16(0xd000d5e8L, 60);         // e2c1 = (prior_torque <= max(d5e4,d5e8))
      w16(0xd000e2e8L, 0);                                // prior torque low -> e2c1=1 -> cVar14!=0
      w8(0xd000d60dL,1); w8(0xd000d606L,10);

      Set<Long> readW=new HashSet<>();
      long steps=0,pc=0; String stop="budget"; boolean read15=false, read3=false;
      try{
        for(;steps<budget;steps++){
          pc=emu.readRegister("pc").longValue();
          if(pc==SENT){ stop="RET"; break; }
          if(pc<0x80020000L||pc>=0x80200000L){ stop="left@"+Long.toHexString(pc); break; }
          long ea=loadEA(pc);
          if(ea>=0){ long c=canon(ea);
            if(c==0x800794efL||c==0x800794f2L) read15=true;
            if(c==0x8007a26aL||c==0x80079536L) read3=true;
            for(long w:WATCH) if(c==w) readW.add(w); }
          emu.step(monitor);
        }
      }catch(Exception e){ stop="FAULT@"+Long.toHexString(pc)+":"+e.getMessage(); }
      int e2c5=rU8(0xd000e2c5L), e2c1=rU8(0xd000e2c1L), e2c4=rU8(0xd000e2c4L);
      int e2e8=rU16(0xd000e2e8L), e2e2=rU16(0xd000e2e2L), e2ec=rU16(0xd000e2ecL), e2f0=rU16(0xd000e2f0L);
      println(String.format("%6d | e2c5=%d e2e8=%d e2e2=%d e2ec=%d e2f0=%d e2c1=%d e2c4=%d | 15:%b 3:%b | %d %s",
        kv, e2c5, e2e8, e2e2, e2ec, e2f0, e2c1, e2c4, read15, read3, steps, stop));
    }
    emu.dispose();
  }
}
