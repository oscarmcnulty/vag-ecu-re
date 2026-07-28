// Peripheral-model emulation layer: live STM timer + generic busy-wait breaker (poke polled HW regs).
// Runs boot from main() to build the Com context c03fc37c. Args: <entryHex> [budget]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulPeriph extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a){ try{ byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}catch(Exception e){return -1;} }
  boolean isPeriph(long a){ return (a>=0xf0000000L&&a<0xf0110000L); }

  // resolve effective address of a load instruction using live registers
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
    long entry=Long.parseLong(args[0],16);
    long budget=args.length>1?Long.parseLong(args[1]):60000000L;
    emu=new EmulatorHelper(currentProgram);
    // suppress Ghidra's per-failed-instruction error logging (else unimplemented insns flood the log -> OOM)
    try{ org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emulate.Emulate", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.app.emulator.DefaultEmulator", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emu", org.apache.logging.log4j.Level.OFF); }catch(Throwable t){}
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x10000},{0xf0000000L,0x40000},{0xf0100000L,0x10000},{0xe8000000L,0x2000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    // initialize core CSRs so "uninitialized register read" doesn't throw
    for(String csr: new String[]{"ICR","ISP","BIV","BTV","PSW","PCON0","PCON1","PCON2","DCON0","DCX","SYSCON","CPU_ID","CORE_ID","PC"})
      try{ if(!csr.equals("PC")) emu.writeRegister(csr,0L); }catch(Throwable t){}
    // suppress the emulator's per-failed-instruction stderr trace flood (else OOM)
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);
    // seed SCU/PLL "ready" high bits
    for(long a=0xf0000000L;a<0xf0000100L;a+=4) w32(a,0xffffffffL);
    // pre-seed the scheduler's STM status pointer (never set on the reachable init path) so tasks tick
    w32(0xc03fcb04L, 0xf0000240L);

    long lo=0x80020000L, hi=0x80200000L, ctx=0, cb04=0, vtime=0; long steps=0; String stop="budget";
    Map<Long,Long> pokeVal=new HashMap<>();
    Set<Long> tasksSeen=new HashSet<>(); Set<Long> tasks=new HashSet<>(Arrays.asList(0x80028348L,0x8002837eL,0x8002842cL,0x80028ccaL));
    ArrayDeque<Long> ring=new ArrayDeque<>(); int breaks=0, skipInsn=0;
    println(String.format("PERIPH-EMU from %x budget=%d",entry,budget));
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){ stop="RETURNED"; break; }
        if(pc<lo||pc>=hi){ stop="left @"+Long.toHexString(pc); break; }
        // live STM timer: advance TIM0..TIM6 every 16 steps
        if((steps&0xf)==0){ vtime+=0x40; for(long a=0xf0000210L;a<=0xf0000228L;a+=4) w32(a,vtime); }
        // periodic scheduler tick: set STM_ISRR bit13 every 15000 steps (c03fcb04 points here)
        if(steps%15000==0){ w32(0xf0000240L, 0x2000L); }
        // watches
        if((steps&0x3ff)==0){ long c=rU32(0xc03fc37cL); if(c!=ctx){ println(String.format(">>> c03fc37c %x->%x @%d pc=%x",ctx,c,steps,pc)); ctx=c; }
          long p=rU32(0xc03fcb04L); if(p!=cb04){ println(String.format("    c03fcb04 -> %x @%d",p,steps)); cb04=p; } }
        if(tasks.contains(pc)&&tasksSeen.add(pc)) println(String.format("*** TASK %x runs @step%d ctx=%x",pc,steps,rU32(0xc03fc37cL)));
        // spin detection over ring of 6000
        ring.addLast(pc); if(ring.size()>6000){ ring.pollFirst();
          if((steps&0xfff)==0){ HashSet<Long> s=new HashSet<>(ring);
            if(s.size()<=8){ // busy-wait: poke any peripheral loads in the loop
              boolean poked=false;
              for(long ppc:s){ long ea=loadEA(ppc);
                if(ea>=0 && isPeriph(ea)){ long v=pokeVal.getOrDefault(ea&~3L,0L)+0x11111111L; v|=0xE000E000L; pokeVal.put(ea&~3L,v); w32(ea&~3L,v); poked=true; } }
              if(poked){ breaks++; if(breaks<=25) println(String.format("  [poke HW spin @%x, %d addrs] step%d",pc,s.size(),steps)); }
              // else: no peripheral load -> legit bounded loop (fill/copy/compute); let it run
              ring.clear(); } } }
        // step, with PC-stuck recovery: skip unimplemented insns (isync/dsync/mtcr/mfcr/traps) as nop
        try{ emu.step(monitor); }catch(Exception se){ /* handled by stuck-detect below */ }
        long np=emu.readRegister("pc").longValue();
        if(np==pc){
          Instruction in=getInstructionAt(A(pc)); int len=in!=null?in.getLength():2;
          try{ emu.writeMemory(A(pc), new byte[len]); }catch(Exception e){}  // patch to nop(s) so it never re-throws
          emu.writeRegister("pc", pc+len); skipInsn++;
          if(skipInsn<=80) println(String.format("  [nop-patch @%x %s]",pc,in!=null?in.getMnemonicString():"?"));
        }
      }
    }catch(Exception e){
      long pc=0; try{pc=emu.readRegister("pc").longValue();}catch(Exception e2){}
      Instruction in=null; try{in=getInstructionAt(A(pc));}catch(Exception e2){}
      stop="FAULT @pc="+Long.toHexString(pc)+" ["+(in!=null?in.toString():"?")+"] : "+e.getMessage();
    }
    println("STOP "+steps+" steps, hw-breaks="+breaks+" skip-insn="+skipInsn+": "+stop);
    println(String.format("FINAL c03fc37c=%x c03fcb04=%x  tasks_ran=%s",rU32(0xc03fc37cL),rU32(0xc03fcb04L),tasksSeen));
    // dump ACC mirror region to catch any signal writes
    StringBuilder mb=new StringBuilder("ACC mirrors d000d5c0-d000d6ff:");
    for(long a=0xd000d5c0L;a<0xd000d700L;a+=4){ long v=rU32(a); if(v!=0) mb.append(String.format(" [%x]=%x",a,v)); }
    println(mb.toString());
    emu.dispose();
  }
}
