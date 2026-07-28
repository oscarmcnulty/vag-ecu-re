// Resolve the AUTOSAR-Com RX/TX signal-buffer chain and find the decel source shadow.
// Stage 0: invoke Com init FUN_801ceff4(0) to materialize DAT_d0000cd0/cd4/cd8 + the 6
//   per-connection runtime-state records (0xc0002798 + conn*0x14) and their signal-buffer
//   descriptors (state+0x10 = 0xc0002810 + conn*8).
// Stage 1: invoke com_process_ipdu(conn) [=0x800af8bc] (default conn=3 = TSK_02, the decel-out
//   message) with a READ/WRITE watch over the Com + mirror RAM, logging PC+fn for every access.
//   The decel value source (TSK_Verzoeg_Anf shadow) will appear among the reads -> FindRefsTo it
//   to name the coordinator. Also dumps the resolved buffer chain.
// Args: [connHex] [budget]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulComWatch extends GhidraScript {
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
  // effective address of the memory operand ([base]disp) of a ld/st
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
  boolean watchRegion(long a){ return (a>=0xd0000000L&&a<0xd0010000L)||(a>=0xc0002000L&&a<0xc0003000L)||(a>=0xd0009000L&&a<0xd000f000L); }

  void setup(long csa,int n) throws Exception {
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
  }

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long conn=args.length>0?Long.parseLong(args[0],16):3;   // 3 = TSK_02 (decel out)
    long budget=args.length>1?Long.parseLong(args[1]):8000000L;
    emu=new EmulatorHelper(currentProgram);
    try{ org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emulate.Emulate", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.app.emulator.DefaultEmulator", org.apache.logging.log4j.Level.OFF); }catch(Throwable t){}
    try{ System.setErr(new java.io.PrintStream(new java.io.OutputStream(){ public void write(int b){} })); }catch(Throwable t){}
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x10000},{0xf0000000L,0x40000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82; setup(csa,n);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT);
    // STAGE 0: Com init FUN_801ceff4(0)
    emu.writeRegister("pc",0x801ceff4L); emu.writeRegister("d4",0L);
    println("EMUL-COM-WATCH: stage0 Com init 801ceff4(0)");
    long lo=0x80020000L, hi=0x80200000L; int stage=0; long prevPc=0;
    Set<Long> seen=new HashSet<>(); int wlog=0;
    LinkedHashSet<Long> readFns=new LinkedHashSet<>();
    try{
      for(long steps=0;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){
          if(stage==0){
            stage=1;
            // dump the resolved Com chain
            long cd0=rU32(0xd0000cd0L), cd4=rU32(0xd0000cd4L), cd8=rU32(0xd0000cd8L);
            println(String.format("### stage0 done: DAT_d0000cd0=%x d0000cd4=%x d0000cd8=%x",cd0,cd4,cd8));
            for(int c=0;c<6;c++){ long st=0xc0002798L+c*0x14; long bufdesc=rU32(st+0x10); long dataptr=rU32(bufdesc);
              println(String.format("   conn%d state@%x  desc(state+0x10)=%x  *(desc)=dataptr=%x  bytes@desc: %08x %08x",
                c,st,bufdesc,dataptr,rU32(bufdesc),rU32(bufdesc+4))); }
            // STAGE 1: invoke com_process_ipdu(conn)
            setup(csa,n); emu.writeRegister("a11",SENT);
            emu.writeRegister("pc",0x800af8bcL); emu.writeRegister("d4",conn);
            println(String.format("### stage1: com_process_ipdu(%d) with read/write watch",conn));
            prevPc=pc; continue;
          } else { println("### stage1 RETURNED"); break; }
        }
        if(!inCode(pc)){ long ra=rreg("a11")&0xfffffffeL;
          if(inCode(ra)&&ra!=prevPc){ emu.writeRegister("pc",ra); try{emu.writeRegister("d2",0L);}catch(Exception e){} prevPc=pc; continue; }
          println(String.format("  [stage%d left code @%x]",stage,pc)); break; }
        Instruction in=getInstructionAt(A(pc));
        String mn=in!=null?in.getMnemonicString().toLowerCase():"?";
        if(stage==1 && (mn.startsWith("ld")||mn.startsWith("st"))){
          long ea=memEA(in);
          if(ea>=0 && watchRegion(ea) && seen.add((pc<<20)^(ea&0xfffffL)) && wlog++<300){
            Function fn=getFunctionContaining(A(pc));
            boolean wr=mn.startsWith("st");
            println(String.format("  %s [%x] pc=%x %s (fn %s)",wr?"WR":"RD",ea,pc,in.toString(),fn!=null?fn.getName():"?"));
            if(!wr) readFns.add(ea);
          }
        }
        // stub-skip bad indirect calls
        if(mn.equals("calli")||mn.equals("jli")){ long tgt=regOperand(in)&0xfffffffeL;
          if(!inCode(tgt)){ emu.writeRegister("pc",pc+in.getLength()); try{emu.writeRegister("d2",0L);}catch(Exception e){} prevPc=pc; continue; } }
        if(mn.equals("ji")){ long tgt=regOperand(in)&0xfffffffeL;
          if(!inCode(tgt)){ long ra=rreg("a11")&0xfffffffeL; if(inCode(ra)){ emu.writeRegister("pc",ra); prevPc=pc; continue; } } }
        prevPc=pc;
        try{ emu.step(monitor); }catch(Exception se){ println(String.format("  [fault stage%d @%x: %s]",stage,pc,se.getMessage()));
          long ra=rreg("a11")&0xfffffffeL; if(inCode(ra)){ emu.writeRegister("pc",ra);} else break; }
        long np=emu.readRegister("pc").longValue();
        if(np==pc){ int len=in!=null?in.getLength():2; try{emu.writeMemory(A(pc),new byte[len]);}catch(Exception e){} emu.writeRegister("pc",pc+len); }
      }
    }catch(Exception e){ println("FAULT: "+e.getMessage()); }
    println("=== distinct RAM read addresses during com_process_ipdu (candidate signal shadows) ===");
    for(long ea:readFns) println(String.format("   read [%x]",ea));
    // final buffer dump
    println("=== signal buffers 0xc0002810 + conn*8 ===");
    for(int c=0;c<6;c++) println(String.format("   conn%d buf@%x = %08x %08x",c,0xc0002810L+c*8,rU32(0xc0002810L+c*8),rU32(0xc0002810L+c*8+4)));
    emu.dispose();
  }
}
