// Boot full-init, bridge to run-mode, then WRITE-watch the TSK/ACC output shadow regions and
// log the writer PC + function for each newly-changed byte (deduped). Rationale: TSK_02/TSK_04
// (decel out + status) are transmitted CYCLICALLY even when ACC is idle, so the coordinator writes
// its output shadow every cycle regardless of ACC-active state -> a write-watch catches its PC even
// though the cal read-watch (only fires on a clamp) came up empty.
// Args: <entryHex> [budget] [bridgeStep]   (defaults 80021140, 12000000, 1500000)
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulComWatch2 extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a){ try{ byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}catch(Exception e){return -1;} }
  long rreg(String r){ try{ return emu.readRegister(r).longValue(); }catch(Throwable t){ return -1; } }
  boolean inCode(long a){ return (a>=0x80020000L&&a<0x80200000L)||(a>=0xd4000000L&&a<0xd4010000L); }
  long regOperand(Instruction in){
    if(in==null) return Long.MIN_VALUE;
    for(int o=0;o<in.getNumOperands();o++) for(Object x:in.getOpObjects(o)) if(x instanceof Register){ try{ return emu.readRegister((Register)x).longValue(); }catch(Exception e){} }
    return Long.MIN_VALUE;
  }

  long memEA(Instruction in){
    if(in==null) return -1;
    for(int o=0;o<in.getNumOperands();o++){
      Object[] objs=in.getOpObjects(o); Register base=null; long disp=0; boolean hasScalar=false;
      for(Object x:objs){ if(x instanceof Register) base=(Register)x; else if(x instanceof Scalar){ disp=((Scalar)x).getSignedValue(); hasScalar=true; } }
      if(base!=null){ try{ return emu.readRegister(base).longValue()+disp; }catch(Exception e){} }
      if(hasScalar && disp!=0) return disp;
    }
    return -1;
  }
  boolean shadowRegion(long a){ return (a>=0xd000d000L&&a<0xd000f000L)||(a>=0xc0002000L&&a<0xc0003000L); }
  // watched write windows: TSK queue/mode + ACC mirror (d000d3c0-d000d700) and Com IPDU bufs (c0002700-c0002b00)
  static final long[][] WIN = {{0xd000d3c0L,0xd000d700L},{0xc0002700L,0xc0002b00L},{0xd000e2b0L,0xd000e300L}};
  boolean watched(long a){ for(long[] w:WIN) if(a>=w[0]&&a<w[1]) return true; return false; }

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    long budget=args.length>1?Long.parseLong(args[1]):12000000L;
    long bridgeStep=args.length>2?Long.parseLong(args[2]):1500000L;
    emu=new EmulatorHelper(currentProgram);
    try{ org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emulate.Emulate", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.app.emulator.DefaultEmulator", org.apache.logging.log4j.Level.OFF); }catch(Throwable t){}
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x10000},{0xf0000000L,0x40000},{0xf0100000L,0x10000},{0xf02ff000L,0x1000},{0xe8000000L,0x2000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    for(String csr: new String[]{"ICR","ISP","BIV","BTV","PSW","PCON0","PCON1","PCON2","DCON0","DCX","SYSCON","CPU_ID","CORE_ID"})
      try{ emu.writeRegister(csr,0L); }catch(Throwable t){}
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);
    for(long a=0xf0000000L;a<0xf0000100L;a+=4) w32(a,0xffffffffL);
    for(long a=0xf0000c00L;a<0xf0001000L;a+=4) w32(a,0xffffffffL);
    for(long a=0xf02fff00L;a<0xf0300000L;a+=4) w32(a,0xffffffffL);
    w32(0xc03fcb04L, 0xf0000240L);

    long lo=0x80020000L, hi=0x80200000L; long steps=0; String stop="budget"; long prevPc=0;
    Map<Long,Long> fnStub=new HashMap<>(); fnStub.put(0x800b4f80L,0x190L); fnStub.put(0x80021de0L,0x190L);
    Set<Long> retStub=new HashSet<>(Arrays.asList(0x801d7838L,0x8002ed62L,0x801d7902L));
    fnStub.put(0x80028e76L,1L); retStub.add(0x801d5d7eL);
    ArrayDeque<Long> ring=new ArrayDeque<>(); int nullRecover=0, stubSkips=0; int wlog=0;
    // snapshot buffers per window
    byte[][] snap=new byte[WIN.length][]; boolean watching=false;
    Set<Long> seenWriter=new HashSet<>(), seenRead=new HashSet<>();
    // invoke the TSK_02 pack once the runtime Com context _DAT_c03fc37c has materialized (post-bridge)
    long invokeAt=bridgeStep+400000L; boolean invoked=false; int rlog=0;
    long invokeFn=0x800af8bcL, invokeArg=3;   // com_process_ipdu(3) = TSK_02
    try{ if(args.length>3) invokeFn=Long.parseLong(args[3],16); }catch(Exception e){}
    try{ if(args.length>4) invokeArg=Long.parseLong(args[4]); }catch(Exception e){}
    println(String.format("SHADOW-WATCH from %x budget=%d bridge@%d invoke %x(%d)@step%d",entry,budget,bridgeStep,invokeFn,invokeArg,invokeAt));
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){
          if(invoked){ stop="INVOKE-RETURNED"; break; }
          if(watching){ steps=invokeAt-1; }   // run-mode returned early -> jump to invoke
          else { stop="RETURNED-preboot"; break; }
          prevPc=pc; continue;
        }
        // once context is up, invoke the TSK_02 pack with read/write watch
        if(watching && !invoked && steps>=invokeAt){
          long ctx=rU32(0xc03fc37cL);
          println(String.format("### INVOKE %x(%d) @step%d  _DAT_c03fc37c=%x",invokeFn,invokeArg,steps,ctx));
          emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
          emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",SENT);
          emu.writeRegister("d4",invokeArg); emu.writeRegister("pc",invokeFn);
          invoked=true; ring.clear(); prevPc=pc; continue;
        }
        if(steps==bridgeStep){
          println(String.format("### BRIDGE to run-mode @step%d",steps));
          emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
          emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",SENT);
          emu.writeRegister("d4",0x1200L); emu.writeRegister("pc",0x80021214L);
          for(int wi=0;wi<WIN.length;wi++) snap[wi]=emu.readMemory(A(WIN[wi][0]),(int)(WIN[wi][1]-WIN[wi][0]));
          watching=true; prevPc=pc; continue;
        }
        if(!inCode(pc)){
          long ra=rreg("a11")&0xfffffffeL;
          if(inCode(ra) && ra!=prevPc && nullRecover<20000){ nullRecover++;
            emu.writeRegister("pc",ra); try{emu.writeRegister("d2",0L);}catch(Exception e){} prevPc=pc; continue; }
          stop="left @"+Long.toHexString(pc); break; }
        if((steps&0xf)==0){ long vt=0x40*(steps/16); for(long a=0xf0000210L;a<=0xf0000228L;a+=4) w32(a,vt); }
        if(steps%15000==0){ w32(0xf0000240L, 0x2000L); }
        if(fnStub.containsKey(pc)){ long ra=rreg("a11")&0xfffffffeL;
          if(ra>=lo&&ra<hi){ emu.writeRegister("d2",fnStub.get(pc)); emu.writeRegister("pc",ra); prevPc=pc; continue; } }
        if(retStub.contains(pc)){ long ra=rreg("a11")&0xfffffffeL;
          if(ra>=lo&&ra<hi){ emu.writeRegister("pc",ra); prevPc=pc; continue; } }
        Instruction in=getInstructionAt(A(pc));
        String mn=in!=null?in.getMnemonicString().toLowerCase():"?";
        // read-watch during the invoked pack: log loads of signal-shadow RAM (candidate decel source)
        if(invoked && mn.startsWith("ld")){ long ea=memEA(in);
          if(ea>=0 && shadowRegion(ea) && seenRead.add((pc<<20)^(ea&0xfffffL)) && rlog++<200){
            Function fn=getFunctionContaining(A(pc));
            println(String.format("  RD [%x] pc=%x %s (fn %s)",ea,pc,in.toString(),fn!=null?fn.getName():"?")); } }
        if(mn.equals("calli")||mn.equals("jli")){ long tgt=regOperand(in)&0xfffffffeL;
          if(!inCode(tgt)){ emu.writeRegister("pc",pc+in.getLength()); try{emu.writeRegister("d2",0L);}catch(Exception e){} prevPc=pc; continue; } }
        if(mn.equals("ji")){ long tgt=regOperand(in)&0xfffffffeL;
          if(!inCode(tgt)){ long ra=rreg("a11")&0xfffffffeL; if(inCode(ra)){ emu.writeRegister("pc",ra); prevPc=pc; continue; } } }
        // simple spin breaker
        ring.addLast(pc); if(ring.size()>6000){ ring.pollFirst();
          if((steps&0xfff)==0){ HashSet<Long> s=new HashSet<>(ring);
            if(s.size()<=40){ long ra=rreg("a11")&0xfffffffeL;
              if(ra>=lo&&ra<hi){ emu.writeRegister("pc",ra); try{emu.writeRegister("d2",0L);}catch(Exception e){} ring.clear(); prevPc=pc; continue; } } } }
        long stepPc=pc;
        prevPc=pc;
        try{ emu.step(monitor); }catch(Exception se){}
        long np=emu.readRegister("pc").longValue();
        if(np==stepPc){ int len=in!=null?in.getLength():2; try{ emu.writeMemory(A(stepPc),new byte[len]); }catch(Exception e){} emu.writeRegister("pc",stepPc+len); }
        // after each step, diff the watched windows; attribute change to stepPc (the instruction just run)
        if(watching){
          for(int wi=0;wi<WIN.length;wi++){
            byte[] cur=emu.readMemory(A(WIN[wi][0]),(int)(WIN[wi][1]-WIN[wi][0]));
            for(int k=0;k<cur.length;k++) if(cur[k]!=snap[wi][k]){
              long addr=WIN[wi][0]+k;
              if(seenWriter.add((stepPc<<20)^(addr&0xfffffL)) && wlog++<400){
                Function fn=getFunctionContaining(A(stepPc));
                println(String.format("  WR [%x] %02x->%02x  writer pc=%x fn=%s @step%d",
                  addr,snap[wi][k]&0xff,cur[k]&0xff,stepPc,fn!=null?fn.getName():"?",steps));
              }
              snap[wi][k]=cur[k];
            }
          }
        }
      }
    }catch(Exception e){ stop="FAULT: "+e.getMessage(); }
    println("STOP "+steps+" steps: "+stop);
    // summary: distinct writer functions
    emu.dispose();
  }
}
