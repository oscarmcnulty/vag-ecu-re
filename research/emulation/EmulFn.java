// Surgically emulate one function with full CSA/SP/base-reg setup; watch c03fc37c; report spins/faults precisely.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import java.util.*;

public class EmulFn extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a) throws Exception { byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    long param=args.length>1?Long.parseLong(args[1],16):0x1200;
    int budget=args.length>2?Integer.parseInt(args[2]):6000000;
    emu=new EmulatorHelper(currentProgram);
    for(long[] r: new long[][]{{0x0L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x8000},{0xf0000000L,0x40000},{0xf0100000L,0x8000},{0xe8000000L,0x1000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    emu.writeRegister("d4",param); emu.writeRegister("a4",param);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);

    long lo=0x80020000L, hi=0x80200000L, ctx=0, cb04=0; int steps=0; String stop="budget";
    println(String.format("EMUL-FN %x(param=%x) budget=%d",entry,param,budget));
    ArrayDeque<Long> ring=new ArrayDeque<>();
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){ stop="RETURNED (fn complete)"; break; }
        if(pc<lo||pc>=hi){ stop="left @"+Long.toHexString(pc); break; }
        if((steps&0x3ff)==0){ long c=rU32(0xc03fc37cL); if(c!=ctx){ println(String.format(">>> c03fc37c %x->%x @step%d pc=%x",ctx,c,steps,pc)); ctx=c; }
          long p=rU32(0xc03fcb04L); if(p!=cb04){ println(String.format("    c03fcb04 -> %x @step%d",p,steps)); cb04=p; } }
        // spin detect: last 8000 steps within a <=6-PC window
        ring.addLast(pc); if(ring.size()>8000){ ring.pollFirst();
          if((steps&0x1fff)==0){ HashSet<Long> s=new HashSet<>(ring); if(s.size()<=6){
            StringBuilder sb=new StringBuilder(); List<Long> sl=new ArrayList<>(s); Collections.sort(sl);
            for(long p:sl){ Instruction in=getInstructionAt(A(p)); sb.append(String.format("%x[%s] ",p,in!=null?in.toString():"?")); }
            stop="SPIN in {"+sb+"} @step"+steps; break; } } }
        emu.step(monitor);
      }
    }catch(Exception e){
      long pc=0; try{pc=emu.readRegister("pc").longValue();}catch(Exception e2){}
      Instruction in=null; try{in=getInstructionAt(A(pc));}catch(Exception e2){}
      stop="FAULT @pc="+Long.toHexString(pc)+" ["+(in!=null?in.toString():"?")+"] : "+e.getMessage();
    }
    println("STOP "+steps+" steps: "+stop);
    try{ println(String.format("c03fc37c=%x c03fcb04=%x",rU32(0xc03fc37cL),rU32(0xc03fcb04L))); }catch(Exception e){}
    emu.dispose();
  }
}
