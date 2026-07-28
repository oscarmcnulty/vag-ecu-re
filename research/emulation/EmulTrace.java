// Emulate from main() with call-tracing + c03fc37c write-watch + spin punch-through.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import java.util.*;

public class EmulTrace extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a) throws Exception { byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    int budget=args.length>1?Integer.parseInt(args[1]):5000000;
    emu=new EmulatorHelper(currentProgram);
    for(long[] r: new long[][]{{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x8000},{0xf0000000L,0x40000},{0xf0100000L,0x8000},{0xe8000000L,0x1000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);

    long lo=0x80020000L, hi=0x80200000L;
    LinkedHashSet<Long> calls=new LinkedHashSet<>();
    Map<Long,Integer> hot=new HashMap<>();
    long ctx=0; int steps=0, skips=0; String stop="budget"; long lastCallSite=0;
    println(String.format("TRACE from %x budget=%d",entry,budget));
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){ stop="RETURNED to sentinel"; break; }
        if(pc<lo||pc>=hi){ stop="left @"+Long.toHexString(pc); break; }
        // watch ctx
        if((steps&0xfff)==0){ long c=rU32(0xc03fc37cL); if(c!=ctx){ println(String.format(">>> c03fc37c: %x -> %x @step%d pc=%x",ctx,c,steps,pc)); ctx=c; } }
        // call logging
        Instruction in=getInstructionAt(A(pc));
        boolean isCall = in!=null && in.getMnemonicString().toLowerCase().startsWith("call");
        if(isCall) lastCallSite=pc;
        // spin punch-through
        int c=hot.merge(pc,1,Integer::sum);
        if(c>40000){
          // force-return: pop to a11 (return addr reg)
          long ra=emu.readRegister("a11").longValue();
          if(ra>=lo&&ra<hi&&ra!=pc){ emu.writeRegister("pc",ra); hot.clear(); skips++;
            if(skips<=40) println(String.format("  [skip spin @%x -> ret %x] step%d",pc,ra,steps));
            if(skips>2000){ stop="too many skips, last spin @"+Long.toHexString(pc); break; }
            continue; }
          else { stop="SPIN @"+Long.toHexString(pc)+" ra="+Long.toHexString(ra)+" (uncskippable)"; break; }
        }
        emu.step(monitor);
        if(isCall){ long np=emu.readRegister("pc").longValue(); if(np>=lo&&np<hi&&calls.add(np) && ctx==0 && calls.size()<=250)
            println(String.format("  call %x -> %x",pc,np)); }
      }
    }catch(Exception e){
      long pc=0; try{pc=emu.readRegister("pc").longValue();}catch(Exception e2){}
      stop="FAULT @pc="+Long.toHexString(pc)+" : "+e.getMessage();
    }
    println("STOP "+steps+" steps, skips="+skips+": "+stop);
    try{ println(String.format("FINAL c03fc37c=%x  (ctx seen=%x)",rU32(0xc03fc37cL),ctx)); }catch(Exception e){}
    emu.dispose();
  }
}
