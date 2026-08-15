// MED17.1.1: boot-emulate and snapshot RAM, specifically to catch function pointers that are
// written into RAM at RUNTIME rather than supplied by the flash .data image.
//
// WHY (and why it is deliberately narrow). core/ghidra/ApplyLoadImage.java already recovers the
// *initialiser* half of RAM statically and exactly -- it applies the firmware's own copy tables,
// so .data, the PSPR helper library and the PCP2 images are present with no emulation involved.
// That leaves exactly one question emulation can answer and static analysis cannot: which RAM
// function-pointer slots are still 0 in .data and get *registered* while the ECU boots. Those are
// the sites ResolveRamDispatch bins as PTR_NULL / EA_UNINIT.
//
// So this harness does not try to reproduce the boot (it cannot: the reset/crt0 sector is blank in
// an OBD read). It runs the same phase chain EmulA9 proved works on this image -- module init
// 0x8006fa8e, then the OS core-context inits 0x800960fe(0)/(1), then scheduler init 0x800966ea --
// on a project where the load image has ALREADY been applied, and watches every store:
//   * value is a plausible code pointer AND destination is DSPR  -> log it as a registration
//   * at the end, sweep RAM for runs of code pointers -> candidate dispatch tables
// A negative result is a real result here: if nothing registers, the "RAM vtable" hypothesis for
// this image is wrong and the unresolved calli are caller-supplied callbacks, not table lookups.
//
// Run AFTER ApplyLoadImage.java on the same (throwaway) project:
//   analyzeHeadless <proj> MED1711 -process <bin> -noanalysis \
//       -scriptPath research/emulation -postScript EmulRamSnap.java 8006fa8e [steps]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulRamSnap extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a){ try{ byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}catch(Exception e){return -1;} }
  long rreg(String r){ try{ return emu.readRegister(r).longValue(); }catch(Throwable t){ return -1; } }
  boolean isPeriph(long a){ return (a>=0xf0000000L&&a<0xf0300000L)||(a>=0xe8000000L&&a<0xe8010000L); }
  boolean isDspr(long a){ return a>=0xd0000000L && a<0xd0020000L; }
  boolean isCodePtr(long v){ return (v&1)==0 && ((v>=0x80004000L&&v<0x80380000L)||(v>=0xa0004000L&&v<0xa0380000L)
                                                ||(v>=0xc00003a0L&&v<0xc0001670L)||(v>=0xd0000ac8L&&v<0xd000aaa8L)); }
  int ilen(long pc){ try{ Instruction in=getInstructionAt(A(pc)); if(in!=null) return in.getLength(); }catch(Throwable t){} return 2; }

  long loadEA(long pc){
    Instruction in=getInstructionAt(A(pc)); if(in==null) return -1;
    if(!in.getMnemonicString().toLowerCase().startsWith("ld")) return -1;
    for(int o=0;o<in.getNumOperands();o++){
      Object[] objs=in.getOpObjects(o); Register base=null; long disp=0;
      for(Object x:objs){ if(x instanceof Register) base=(Register)x; else if(x instanceof Scalar) disp=((Scalar)x).getSignedValue(); }
      if(base!=null){ try{ return emu.readRegister(base).longValue()+disp; }catch(Exception e){} }
    }
    return -1;
  }

  /** for a store, return {effectiveAddress, storedValue} or null */
  long[] storeEAVal(Instruction in){
    if(in==null) return null;
    String mn=in.getMnemonicString().toLowerCase();
    if(!(mn.equals("st.w")||mn.equals("st.a"))) return null;
    Register base=null, src=null; long disp=0;
    for(Object x:in.getOpObjects(0)){
      if(x instanceof Register) base=(Register)x; else if(x instanceof Scalar) disp=((Scalar)x).getSignedValue();
    }
    for(int o=1;o<in.getNumOperands();o++)
      for(Object x:in.getOpObjects(o)) if(x instanceof Register) src=(Register)x;
    if(base==null){                       // absolute form: st.w 0xd000xxxx,dN
      for(Object x:in.getOpObjects(0)) if(x instanceof Scalar) disp=((Scalar)x).getUnsignedValue();
      if(disp==0||src==null) return null;
      try{ return new long[]{disp&0xffffffffL, emu.readRegister(src).longValue()&0xffffffffL}; }catch(Exception e){ return null; }
    }
    if(src==null) return null;
    try{ return new long[]{(emu.readRegister(base).longValue()+disp)&0xffffffffL,
                            emu.readRegister(src).longValue()&0xffffffffL}; }catch(Exception e){ return null; }
  }

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=args.length>0?Long.parseLong(args[0],16):0x8006fa8eL;
    long budget=args.length>1?Long.parseLong(args[1]):20000000L;
    emu=new EmulatorHelper(currentProgram);
    try{ for(String lg:new String[]{"ghidra.pcode.emulate.Emulate","ghidra.app.emulator.DefaultEmulator",
            "ghidra.pcode.emu","ghidra.app.emulator.EmulatorHelper"})
           org.apache.logging.log4j.core.config.Configurator.setLevel(lg, org.apache.logging.log4j.Level.OFF);
    }catch(Throwable t){}
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}

    // NOTE: unlike EmulA9 we do NOT blank 0xd0000000 -- the load image is already in the program and
    // blanking it would destroy exactly the state we came here to use. Only the stack/CSA area and
    // the peripheral space are pre-set.
    for(long[] r: new long[][]{{0xf0000000L,0x300000},{0xe8000000L,0x10000}}) zero(r[0],(int)r[1]);
    long csa=0xd0080000L; int n=512;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); try{ emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);}catch(Throwable t){}
    for(String csr: new String[]{"ICR","ISP","BIV","BTV","PSW","PCON0","PCON1","PCON2","DCON0","DCX","SYSCON","CPU_ID","CORE_ID"})
      try{ emu.writeRegister(csr,0L);}catch(Throwable t){}
    emu.writeRegister("a0",0xd000c420L); emu.writeRegister("a1",0x8002f298L); emu.writeRegister("a8",0xd000c420L);
    emu.writeRegister("a10",0xd007ff00L);
    long SENT=0xd000baf0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);
    for(String r:new String[]{"d4","d5","d6","d7"}) try{emu.writeRegister(r,0L);}catch(Exception e){}
    for(long a=0xf0000000L;a<0xf0000100L;a+=4) w32(a,0xffffffffL);

    long[] phases={entry, 0x800960feL, 0x800960feL, 0x800966eaL}; long[] phaseArg={0,0,1,0}; int phase=0;
    long steps=0, vtime=0, prevPc=entry; String stop="budget";
    Map<Long,Long> pokeVal=new HashMap<>();
    LinkedHashMap<String,Long> regs=new LinkedHashMap<>();     // "pc:ea" -> value (fn-ptr stores)
    ArrayDeque<Long> ring=new ArrayDeque<>(); int breaks=0, skipInsn=0, skipped=0, callsSkipped=0;
    Map<Long,Integer> skipLoop=new HashMap<>(); Map<Long,Integer> hot=new HashMap<>(); long maxPc=0;
    println(String.format("EmulRamSnap from %x budget=%d (load image assumed applied)",entry,budget));
    try{
      for(;steps<budget;steps++){
        long pc=rreg("pc");
        if(pc==SENT){
          phase++;
          if(phase<phases.length){
            println(String.format("--- phase %d done @step%d; entering 0x%08x(arg=%d)",phase-1,steps,phases[phase],phaseArg[phase]));
            try{ emu.writeRegister("pc",phases[phase]); emu.writeRegister("a11",SENT); emu.writeRegister("d4",phaseArg[phase]); }catch(Exception e){}
            continue;
          }
          stop="RETURNED-all-phases"; break;
        }
        boolean okpc=(pc>=0x80000000L&&pc<0x80400000L)||(pc>=0xa0000000L&&pc<0xa0400000L)
                   ||(pc>=0xc00003a0L&&pc<0xc0001670L)||(pc>=0xd0000ac8L&&pc<0xd000aaa8L);
        if(!okpc){ stop="left-code @"+Long.toHexString(pc)+" from "+Long.toHexString(prevPc); break; }
        prevPc=pc;
        if(hot.size()<400000||hot.containsKey(pc)) hot.merge(pc,1,Integer::sum);
        if(pc>=0x80000000L&&pc<0x80400000L&&pc>maxPc) maxPc=pc;
        if((steps&0xf)==0){ vtime+=0x40; for(long a=0xf0000210L;a<=0xf0000228L;a+=4) w32(a,vtime); }
        if(steps%15000==0){ w32(0xf0000240L,0x2000L); }

        // THE POINT OF THIS HARNESS: catch a code pointer being stored into DSPR.
        Instruction cur=getInstructionAt(A(pc));
        long[] sv=storeEAVal(cur);
        if(sv!=null && isDspr(sv[0]) && isCodePtr(sv[1])){
          String key=Long.toHexString(pc)+":"+Long.toHexString(sv[0]);
          if(regs.putIfAbsent(key,sv[1])==null && regs.size()<=400)
            println(String.format("  FNPTR-STORE pc=%08x  [%08x] <- %08x  @step%d",pc,sv[0],sv[1],steps));
        }

        // spin breaker (same policy as EmulA9: poke peripheral reads, else step past scan loops)
        ring.addLast(pc); if(ring.size()>6000){ ring.pollFirst();
          if((steps&0xfff)==0){ HashSet<Long> s=new HashSet<>(ring);
            if(s.size()<=24){ boolean poked=false; long smax=0; for(long q:s) if(q>smax) smax=q;
              for(long ppc:s){ long ea=loadEA(ppc);
                if(ea>=0 && isPeriph(ea)){ long v=pokeVal.getOrDefault(ea&~3L,0L)+0x11111111L; v|=0xE000E000L; pokeVal.put(ea&~3L,v); try{w32(ea&~3L,v);}catch(Exception e){} poked=true; } }
              if(poked) breaks++;
              else { int c=skipLoop.merge(smax,1,Integer::sum);
                if(c<=200){ try{ emu.writeRegister("pc",smax+ilen(smax));}catch(Exception e){} skipped++; } }
              ring.clear(); } } }
        try{ emu.step(monitor); }catch(Exception se){}
        long np=rreg("pc");
        if(np==pc){
          int len=cur!=null?cur.getLength():2;
          try{ emu.writeMemory(A(pc), new byte[len]); }catch(Exception e){}
          try{ emu.writeRegister("pc", pc+len); }catch(Exception e){} skipInsn++;
        }
      }
    }catch(Throwable t){ stop="FAULT @"+Long.toHexString(rreg("pc"))+" : "+t.getMessage(); }

    println("STOP "+steps+" steps hw-breaks="+breaks+" loop-skips="+skipped+" nop-patches="+skipInsn+" : "+stop);
    println("distinct code-pointer stores into DSPR: "+regs.size()+"   maxFlashPc=0x"+Long.toHexString(maxPc));
    println("=== the two ji tables named in the handoff ===");
    for(int i=0;i<6;i++) println(String.format("   0xd0004980[%d] = %08x",i,rU32(0xd0004980L+i*4)));
    for(int i=0;i<5;i++) println(String.format("   0xd0004cb8[%d] = %08x",i,rU32(0xd0004cb8L+i*4)));
    println(String.format("   mode byte 0xd00072e5 = %02x", (rU32(0xd00072e4L)>>8)&0xff));
    // sweep RAM for runs of >=3 consecutive code pointers -> candidate dispatch tables
    println("=== RAM sweep: runs of >=3 consecutive code pointers ===");
    int runs=0;
    for(long a=0xd0000000L;a<0xd0020000L;a+=4){
      long v=rU32(a); if(!isCodePtr(v)) continue;
      long b=a; int cnt=0; while(b<0xd0020000L && isCodePtr(rU32(b))){ cnt++; b+=4; }
      if(cnt>=3){ StringBuilder sb=new StringBuilder(String.format("   %08x x%d :",a,cnt));
        for(long p=a;p<Math.min(b,a+40);p+=4) sb.append(String.format(" %08x",rU32(p)));
        println(sb.toString()); runs++; }
      a=b-4;
      if(runs>60){ println("   (truncated)"); break; }
    }
    println("EMULRAMSNAPDONE");
    emu.dispose();
  }
}
