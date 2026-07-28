// Brute-force cold-invoke EVERY function with conventional base regs (a1=0x80048000 SDA etc.)
// and watch for ANY load whose effective address lands in the decel-limit cal table
// 0x8004dd90-0x8004ddbe (+ non-cached alias 0xa004dd9x). Directly finds the curve reader /
// L2 symmetry monitor regardless of how it is dispatched, because the cal read is address-based.
// Args: [budgetPerFn] [loFnHex] [hiFnHex]   (defaults: 30000, 0x80020000, 0x80200000)
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulFnScanAcc extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rreg(String r){ try{ return emu.readRegister(r).longValue(); }catch(Throwable t){ return -1; } }
  boolean inCode(long a){ return (a>=0x80020000L&&a<0x80200000L)||(a>=0xd4000000L&&a<0xd4010000L); }
  boolean isDecel(long ea){ return (ea>=0x8004dd90L&&ea<0x8004ddc0L)||(ea>=0xa004dd90L&&ea<0xa004ddc0L)
      ||(VALIDATE && ((ea>=0xa004cf00L&&ea<0xa004d200L)||(ea>=0x80040dc0L&&ea<0x80040e80L))); }
  static final boolean VALIDATE = System.getenv("FNSCAN_VALIDATE")!=null;

  long regOperand(Instruction in){
    if(in==null) return Long.MIN_VALUE;
    for(int o=0;o<in.getNumOperands();o++)
      for(Object x:in.getOpObjects(o)) if(x instanceof Register){ try{ return emu.readRegister((Register)x).longValue(); }catch(Exception e){} }
    return Long.MIN_VALUE;
  }
  long loadEA(Instruction in){
    if(in==null || !in.getMnemonicString().toLowerCase().startsWith("ld")) return -1;
    for(int o=0;o<in.getNumOperands();o++){
      Object[] objs=in.getOpObjects(o); Register base=null; long disp=0; boolean hasScalar=false;
      for(Object x:objs){ if(x instanceof Register) base=(Register)x; else if(x instanceof Scalar){ disp=((Scalar)x).getSignedValue(); hasScalar=true; } }
      if(base!=null){ try{ return emu.readRegister(base).longValue()+disp; }catch(Exception e){} }
      if(hasScalar && disp!=0) return disp;
    }
    return -1;
  }

  // Seed a plausible ACC-ACTIVE state so a coordinator whose cal-read is gated on
  // engaged/commanded-decel-exceeds-limit takes that branch. Values from 801e9b86's use
  // of the ACC mirror block (d000d5c0-d6ff): accel d606, speed d644, status d656-658,
  // engaged-ish flags d5c5/d60d. Commanded decel = raw -700 (-3.5 m/s2 @0.005), which
  // EXCEEDS the -3.0 cal floor -> should force the clamp path that reads 0x8004dd90.
  void seedAccActive() throws Exception {
    // fill the ACC mirror region with nonzero "active" bytes
    byte[] act=new byte[0x140]; for(int i=0;i<act.length;i++) act[i]=(byte)0x01;
    emu.writeMemory(A(0xd000d5c0L),act);
    // specific known fields
    w16(0xd000d606L,0xFD44L);   // commanded accel/decel = -700 (-3.5) -> exceeds -3.0 floor
    w16(0xd000d644L,0x1388L);   // speed mirror = 5000 (nonzero, mid-range)
    emu.writeMemory(A(0xd000d5c5L),new byte[]{1});   // engaged-ish flag
    emu.writeMemory(A(0xd000d60dL),new byte[]{1});   // engaged-ish flag
    emu.writeMemory(A(0xd000d656L),new byte[]{0});   // status: no prior fault
    emu.writeMemory(A(0xd000d657L),new byte[]{0});
    emu.writeMemory(A(0xd000d658L),new byte[]{0});
    // Com/TSK mode selector (canmo uses DAT_d000d3dc); TX-queue head nonzero-ish
    emu.writeMemory(A(0xd000d3dcL),new byte[]{0});
  }
  void w16(long a,long v) throws Exception { byte[] b={(byte)v,(byte)(v>>8)}; emu.writeMemory(A(a),b); }
  void initState(long entry, long csa, int n) throws Exception {
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    // give plausible nonzero args (many readers take an input value + maybe a struct ptr)
    for(String r:new String[]{"d4","d5","d6","d7"}) emu.writeRegister(r,0x1200L);
    emu.writeRegister("a4",0xd0009000L); emu.writeRegister("a5",0xd0009000L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);
  }

  public void run() throws Exception {
    String[] args=getScriptArgs();
    int budget=args.length>0?Integer.parseInt(args[0]):30000;
    long loFn=args.length>1?Long.parseLong(args[1],16):0x80020000L;
    long hiFn=args.length>2?Long.parseLong(args[2],16):0x80200000L;
    emu=new EmulatorHelper(currentProgram);
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}
    // enumerate function entry points in range
    List<Long> fns=new ArrayList<>();
    FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
    while(it.hasNext()){ Function f=it.next(); long e=f.getEntryPoint().getOffset(); if(e>=loFn&&e<hiFn) fns.add(e); }
    println(String.format("EMUL-FN-SCAN %d functions, budget=%d/fn, watching decel 0x8004dd90-ddbe (+a0 alias)",fns.size(),budget));
    long SENT=0xd0003ff0L; long csa=0xd0004000L; int n=82;
    int hitFns=0, done=0;
    for(long entry:fns){
      done++;
      // fresh scratch RAM each fn (flash cal is read-only, stays valid)
      for(long[] r: new long[][]{{0xc03f0000L,0x10000},{0xd0000000L,0x10000},{0xd4000000L,0x2000},{0xf0000000L,0x2000}}) zero(r[0],(int)r[1]);
      try{ seedAccActive(); }catch(Exception e){}
      try{ initState(entry,csa,n); }catch(Exception e){ continue; }
      long prevPc=0; boolean logged=false;
      ArrayDeque<Long> ring=new ArrayDeque<>();
      try{
        for(int steps=0;steps<budget;steps++){
          long pc=emu.readRegister("pc").longValue();
          if(pc==SENT) break;                       // returned
          if(!inCode(pc)){                          // bad indirect -> try return to caller once
            long ra=rreg("a11")&0xfffffffeL;
            if(inCode(ra)&&ra!=prevPc){ emu.writeRegister("pc",ra); try{emu.writeRegister("d2",0L);}catch(Exception e){} prevPc=pc; continue; }
            break;
          }
          Instruction in=getInstructionAt(A(pc));
          String mn=in!=null?in.getMnemonicString().toLowerCase():"?";
          if(mn.startsWith("ld")){ long ea=loadEA(in);
            if(isDecel(ea)){
              Function fn=getFunctionContaining(A(pc));
              println(String.format("  *** DECEL-READ fn=%s(%x) pc=%x reads [%x] %s @step%d",
                fn!=null?fn.getName():"?",entry,pc,ea,in.toString(),steps));
              logged=true; break;
            }
          }
          // stub-skip indirect calls/jumps to non-code (null fn-ptrs in cold state)
          if(mn.equals("calli")||mn.equals("jli")){ long tgt=regOperand(in)&0xfffffffeL;
            if(!inCode(tgt)){ emu.writeRegister("pc",pc+in.getLength()); try{emu.writeRegister("d2",0L);}catch(Exception e){} prevPc=pc; continue; } }
          if(mn.equals("ji")){ long tgt=regOperand(in)&0xfffffffeL;
            if(!inCode(tgt)){ long ra=rreg("a11")&0xfffffffeL; if(inCode(ra)){ emu.writeRegister("pc",ra); prevPc=pc; continue; } } }
          // tiny spin breaker: stuck in <=6 PCs -> abandon fn
          ring.addLast(pc); if(ring.size()>2000){ ring.pollFirst();
            if((steps&0x3ff)==0){ HashSet<Long> s=new HashSet<>(ring); if(s.size()<=6) break; } }
          prevPc=pc;
          emu.step(monitor);
          long np=emu.readRegister("pc").longValue();
          if(np==pc){ Instruction i2=getInstructionAt(A(pc)); int len=i2!=null?i2.getLength():2; emu.writeRegister("pc",pc+len); }
        }
      }catch(Exception e){ /* fault -> next fn */ }
      if(logged) hitFns++;
      if((done%500)==0) println(String.format("  ...scanned %d/%d fns, %d decel-readers so far",done,fns.size(),hitFns));
    }
    println("SCAN DONE: "+hitFns+" functions read the decel table out of "+fns.size());
    emu.dispose();
  }
}
