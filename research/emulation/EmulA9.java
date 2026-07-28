// MED17.1.1: resolve the per-task base register `a9` by boot emulation with a peripheral-model layer.
// a9 is set by FUN_8009624e @0x8009624e as a9 = *(0xd0014c7c + param_1*4) (uncached-aliased if flash).
// Peripheral layer (adapted from Simos8.5 EmulPeriph.java): log suppression, CSR init, live STM timer,
// nop-patch for unimplemented TriCore insns, and a smart busy-wait breaker that pokes only peripheral loads.
// Hooks the a9 setter + dumps the task table 0xd0014c7c[]. See ecus/med17/maps/a9_resolution.md.
// Args: <entryHex> [stepBudget]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulA9 extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a){ try{ byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}catch(Exception e){return -1;} }
  long rreg(String r){ try{ return emu.readRegister(r).longValue(); }catch(Throwable t){ return -1; } }
  void copyFlash(long src,long dst,int len){ try{ byte[] b=emu.readMemory(A(src),len); emu.writeMemory(A(dst),b); println(String.format("pre-copied 0x%x bytes flash 0x%08x -> 0x%08x",len,src,dst)); }catch(Throwable t){ println("copyFlash failed: "+t.getMessage()); } }
  int ilen(long pc){ try{ Instruction in=getInstructionAt(A(pc)); if(in!=null) return in.getLength(); }catch(Throwable t){} return 2; }
  boolean isPeriph(long a){ return (a>=0xf0000000L&&a<0xf0300000L)||(a>=0xe8000000L&&a<0xe8010000L); }
  boolean inACC(long pc){ return (pc>=0x80140000L&&pc<0x80146000L)||pc==0x801455aeL||pc==0x80140922L||pc==0x801418eaL; }

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

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=args.length>0?Long.parseLong(args[0],16):0x8006fa8eL;
    long budget=args.length>1?Long.parseLong(args[1]):30000000L;
    final long A9SET=0x8009624eL;
    emu=new EmulatorHelper(currentProgram);
    // suppress the per-failed-instruction error/trace flood (else -> log OOM / JIT abort)
    try{ org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emulate.Emulate", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.app.emulator.DefaultEmulator", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emu", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.app.emulator.EmulatorHelper", org.apache.logging.log4j.Level.OFF); }catch(Throwable t){}
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}
    // memory map (MED17: RAM d0.., PRAM d4.., DSPR/LMU c0.., periph f0.., e8..)
    for(long[] r: new long[][]{{0x0L,0x200000},{0xc0000000L,0x40000},{0xc03f0000L,0x10000},{0xd0000000L,0x100000},
        {0xd4000000L,0x20000},{0xf0000000L,0x300000},{0xe8000000L,0x10000}}) zero(r[0],(int)r[1]);
    // CSA free-list
    long csa=0xd0080000L; int n=512;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); try{ emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);}catch(Throwable t){}
    for(String csr: new String[]{"ICR","ISP","BIV","BTV","PSW","PCON0","PCON1","PCON2","DCON0","DCX","SYSCON","CPU_ID","CORE_ID"})
      try{ emu.writeRegister(csr,0L);}catch(Throwable t){}
    // MED17 base regs + stack + sentinel
    emu.writeRegister("a0",0xd000c420L); emu.writeRegister("a1",0x8002f298L); emu.writeRegister("a8",0xd000c420L);
    emu.writeRegister("a10",0xd007ff00L);
    long SENT=0xd000baf0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);
    // phase chain: run module-init (8006fa8e) to completion, THEN the OS core-context/scheduler inits that
    // call the a9 setter with correct state. 800960fe(0)/(1) set up core contexts 0/1; 800966ea = sched init.
    long[] phases={entry, 0x800960feL, 0x800960feL, 0x800966eaL}; long[] phaseArg={0,0,1,0}; int phase=0;
    for(String r:new String[]{"d4","d5","d6","d7"}) try{emu.writeRegister(r,0L);}catch(Exception e){}
    // seed SCU/PLL "ready" high bits
    for(long a=0xf0000000L;a<0xf0000100L;a+=4) w32(a,0xffffffffL);
    // crt0 PSPR code relocation (flash LMA -> PSPR VMA 0xc0000000) that we skip by entering after crt0.
    // Descriptor @0x8001c6f8: src=0x8001d7a0, dst=0xc0000000, len=0x9dc. Covers the calla 0xc000079c targets.
    copyFlash(0x8001d7a0L, 0xc0000000L, 0x26b0);

    long lo=0x80000000L, hi=0x80400000L; long steps=0, vtime=0, prevPc=entry; String stop="budget";
    long wBlk=0, wT0=0, wT1=0;
    boolean reachedSetter=false;
    Map<Long,Long> pokeVal=new HashMap<>();
    Map<Long,Long> paramToA9=new LinkedHashMap<>();
    Set<Long> accA9=new LinkedHashSet<>();
    ArrayDeque<Long> ring=new ArrayDeque<>(); int breaks=0, skipInsn=0, skipped=0, callsSkipped=0;
    Map<Long,Integer> skipLoop=new HashMap<>();
    // Flash call sites into PSPR checksum/init routines to BYPASS (set return d2=0 = success, skip the calla).
    // 0x8019169c: FUN_80191684 calls func_0xc000079c() -> the big crt0 checksum loop @0xc0000690.
    Set<Long> skipCalls=new HashSet<>(Arrays.asList(0x8019169cL));
    Map<Long,Integer> hot=new HashMap<>(); long maxPc=0;
    List<String> log=new ArrayList<>();
    println(String.format("EmulA9 PERIPH from %x budget=%d hook a9-setter@%x",entry,budget,A9SET));
    try{
      for(;steps<budget;steps++){
        long pc=rreg("pc");
        if(pc==SENT){
          phase++;
          if(phase<phases.length){
            println(String.format("--- phase %d done @step%d; entering 0x%08x(arg=%d)  DAT_d0014cb4=%x",phase-1,steps,phases[phase],phaseArg[phase],rU32(0xd0014cb4L)));
            try{ emu.writeRegister("pc",phases[phase]); emu.writeRegister("a11",SENT); emu.writeRegister("d4",phaseArg[phase]); }catch(Exception e){}
            continue;
          }
          stop="RETURNED-all-phases"; break;
        }
        // valid code: flash, uncached-flash alias, or PSPR scratchpad (0xc0000000, copied at boot)
        boolean okpc=(pc>=0x80000000L&&pc<0x80400000L)||(pc>=0xa0000000L&&pc<0xa0400000L)||(pc>=0xc0000000L&&pc<0xc00026b0L)||(pc>=0xd4000000L&&pc<0xd4010000L);
        if(!okpc){
          Instruction pin=getInstructionAt(A(prevPc));
          stop="left-code @"+Long.toHexString(pc)+" from "+Long.toHexString(prevPc)+" ["+(pin!=null?pin.toString():"?")+"]";
          break;
        }
        prevPc=pc;
        // BYPASS every flash->PSPR call (checksum/perf-critical routines): fake success (d2=0), skip the call.
        // The OS code we want (FUN_8009624e, 800966ea) is all in FLASH, so no-op'ing PSPR still reaches it.
        if(pc>=0x80000000L && pc<0x80400000L){
          Instruction in=getInstructionAt(A(pc));
          if(in!=null && in.getMnemonicString().toLowerCase().startsWith("call")){
            boolean toPspr=false;
            for(Address ft:in.getFlows()){ long t=ft.getOffset(); if(t>=0xc0000000L&&t<0xc0010000L){ toPspr=true; break; } }
            if(toPspr){
              try{ emu.writeRegister("d2",0L); emu.writeRegister("pc", pc+in.getLength()); }catch(Exception e){}
              callsSkipped++; if(callsSkipped<=15 && log.size()<40) log.add(String.format("BYPASS PSPR call @%x @step%d",pc,steps));
              continue;
            }
          }
        }
        if(hot.size()<400000||hot.containsKey(pc)) hot.merge(pc,1,Integer::sum); if(pc>=0x80000000L&&pc<0x80400000L&&pc>maxPc) maxPc=pc;
        // live STM timer + periodic scheduler tick
        if((steps&0xf)==0){ vtime+=0x40; for(long a=0xf0000210L;a<=0xf0000228L;a+=4) w32(a,vtime); }
        if(steps%15000==0){ w32(0xf0000240L,0x2000L); }
        // a9-write hook: compute the value the setter assigns
        if(pc==A9SET){
          reachedSetter=true;
          long p1=rreg("d4")&0xff, tbl=rU32(0xd0014cb4L);
          long src=(tbl>0)?rU32(tbl+0x1c+p1*4):0;
          long a9=(src>>>28)==8?(src+0x20000000L)&0xffffffffL:src;
          Long key=(p1<<32)|(a9&0xffffffffL);
          if(!paramToA9.containsKey(key)){ paramToA9.put(key,a9);
            println(String.format("   A9-WRITE @step %d: param_1=0x%x DAT_d0014cb4=0x%08x src=0x%08x -> a9=0x%08x",steps,p1,tbl,src,a9)); }
          if(paramToA9.size()>=60){ stop="captured-60"; break; }
        }
        if(inACC(pc)){ long a9=rreg("a9"); if(a9>0) accA9.add(a9); }
        // write-watch: capture the moment the OS init sets the block ptr + core-base table (the real a9 source)
        if((steps&0x3f)==0){
          long b=rU32(0xd0014cb4L); if(b!=wBlk){ println(String.format(">>> DAT_d0014cb4 %x->%x @step%d pc=%x",wBlk,b,steps,pc)); wBlk=b; }
          long t0=rU32(0xd0014c7cL); if(t0!=wT0){ println(String.format(">>> core-base[0] 0xd0014c7c %x->%x @step%d pc=%x",wT0,t0,steps,pc)); wT0=t0; }
          long t1=rU32(0xd0014c80L); if(t1!=wT1){ println(String.format(">>> core-base[1] 0xd0014c80 %x->%x @step%d pc=%x",wT1,t1,steps,pc)); wT1=t1; }
        }
        // spin detection (ring of 6000, <=24 distinct). Poke peripheral loads; else skip crt0 scan/delay loops.
        ring.addLast(pc); if(ring.size()>6000){ ring.pollFirst();
          if((steps&0xfff)==0){ HashSet<Long> s=new HashSet<>(ring);
            if(s.size()<=24){ boolean poked=false; long smax=0; for(long q:s) if(q>smax) smax=q;
              for(long ppc:s){ long ea=loadEA(ppc);
                if(ea>=0 && isPeriph(ea)){ long v=pokeVal.getOrDefault(ea&~3L,0L)+0x11111111L; v|=0xE000E000L; pokeVal.put(ea&~3L,v); try{w32(ea&~3L,v);}catch(Exception e){} poked=true; } }
              if(poked){ breaks++; if(breaks<=20 && log.size()<40) log.add(String.format("poke HW spin @%x (%d addrs) step%d",pc,s.size(),steps)); }
              else { // no peripheral read: a crt0 scan/delay loop (checksum/copy over a big region). Skip past it.
                int c=skipLoop.merge(smax,1,Integer::sum);
                long tgt=(smax>=0xc0000000L&&smax<0xc0010000L)?smax+2:smax+ilen(smax);
                if(c<=200){ try{ emu.writeRegister("pc",tgt);}catch(Exception e){} skipped++;
                  if(skipped<=25 && log.size()<40) log.add(String.format("skip crt0 loop @%x -> %x (%d PCs, x%d) step%d",smax,tgt,s.size(),c,steps)); }
              }
              ring.clear(); } } }
        // step + nop-patch for unimplemented insns (isync/dsync/mtcr/mfcr/traps that don't advance PC)
        try{ emu.step(monitor); }catch(Exception se){}
        long np=rreg("pc");
        if(np==pc){
          Instruction in=getInstructionAt(A(pc)); int len=in!=null?in.getLength():2;
          try{ emu.writeMemory(A(pc), new byte[len]); }catch(Exception e){}
          try{ emu.writeRegister("pc", pc+len); }catch(Exception e){} skipInsn++;
          if(skipInsn<=40 && log.size()<40) log.add(String.format("nop-patch @%x %s",pc,in!=null?in.getMnemonicString():"?"));
        }
      }
    }catch(Throwable t){
      long pc=rreg("pc"); stop="FAULT @"+Long.toHexString(pc)+" : "+t.getMessage();
    }
    println("STOP "+steps+" steps hw-breaks="+breaks+" nop-patches="+skipInsn+" : "+stop+"  reachedA9setter="+reachedSetter);
    for(int i=0;i<Math.min(log.size(),24);i++) println("   "+log.get(i));
    println("a9-setter observations (param_1 -> a9):");
    for(Map.Entry<Long,Long> e:paramToA9.entrySet()) println(String.format("   param_1=0x%x -> a9=0x%08x",(e.getKey()>>>32),e.getValue()));
    println("a9 live inside ACC functions:");
    for(long a:accA9) println(String.format("   a9=0x%08x",a));
    println("task table 0xd0014c7c[0..15]:");
    for(int i=0;i<16;i++){ long v=rU32(0xd0014c7cL+i*4); if(v!=0) println(String.format("   [%2d] 0x%08x = 0x%08x",i,0xd0014c7cL+i*4,v)); }
    println("DAT_d0014cb4="+Long.toHexString(rU32(0xd0014cb4L))+"  maxFlashPc=0x"+Long.toHexString(maxPc)+"  distinctFlashPcs="+hot.size());
    println("top hot flash PCs:");
    hot.entrySet().stream().sorted((x,y)->y.getValue()-x.getValue()).limit(10)
       .forEach(e->println(String.format("   %08x : %d",e.getKey(),e.getValue())));
    emu.dispose();
  }
}
