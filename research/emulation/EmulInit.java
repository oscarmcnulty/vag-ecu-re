// Attempt init emulation with CSA context free-list + peripheral zero-stub + loop detection.
// Args: <entryHex> [stepBudget]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.math.BigInteger;
import java.util.*;

public class EmulInit extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long base,int len){ try{ emu.writeMemory(A(base),new byte[len]); }catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b); }

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    int budget=args.length>1?Integer.parseInt(args[1]):200000;
    emu=new EmulatorHelper(currentProgram);
    // RAM + peripherals (zero so loads don't fault)
    zero(0xc0000000L,0x10000); zero(0xc0400000L,0x2000);
    zero(0xd0000000L,0x10000); zero(0xd0400000L,0x2000);
    zero(0xf0000000L,0x40000); zero(0xf0100000L,0x4000);
    // CSA free list: 128 CSAs @0xd000c000, 64 bytes each; FCX enc = (seg<<16)|(off), addr=(seg<<28)|(off<<6)
    long csaBase=0xd000c000L; int nCSA=128;
    for(int i=0;i<nCSA;i++){
      long ai=csaBase+i*64;
      long nextEnc = (i<nCSA-1)? enc(csaBase+(i+1)*64) : 0;
      w32(ai,nextEnc);
    }
    emu.writeRegister("FCX", enc(csaBase));
    emu.writeRegister("PCXI", 0L); try{emu.writeRegister("LCX", enc(0xd000c000L+120*64));}catch(Exception e){}
    // base regs, stack, return sentinel
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xd000bf00L);          // SP
    long SENT=0xd000baf0L; emu.writeRegister("a11",SENT);
    emu.writeRegister("pc",entry);

    long lo=0x80020000L, hi=0x80200000L;
    println(String.format("entry=%x budget=%d  (watching writes to c03fc37c context + 0xc00027xx)",entry,budget));
    // loop detection
    ArrayDeque<Long> recent=new ArrayDeque<>(); Map<Long,Integer> hot=new HashMap<>();
    int steps=0; String stop="budget"; long lastCtx=0;
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){ stop="RETURNED to sentinel"; break; }
        if(pc<lo||pc>=hi){ stop="left-code @"+Long.toHexString(pc); break; }
        // watch the context pointer forming
        try{ long ctx=readU32(0xc03fc37cL); if(ctx!=lastCtx){ println(String.format("  [%d] c03fc37c := %x",steps,ctx)); lastCtx=ctx; } }catch(Exception e){}
        // hot-loop detect
        hot.merge(pc,1,Integer::sum);
        if(hot.get(pc)>4000){ stop="HOT-LOOP @"+Long.toHexString(pc)+" (busy-wait?)"; break; }
        emu.step(monitor);
      }
    }catch(Exception e){
      long pc=0; try{pc=emu.readRegister("pc").longValue();}catch(Exception e2){}
      stop="FAULT @pc="+Long.toHexString(pc)+" : "+e.getMessage();
    }
    println("STOP after "+steps+" steps: "+stop);
    try{ println(String.format("final c03fc37c = %x", readU32(0xc03fc37cL))); }catch(Exception e){}
    // dump C-RAM Com area
    try{ byte[] b=emu.readMemory(A(0xc0002790L),0x30); StringBuilder s=new StringBuilder();
      for(int i=0;i<b.length;i+=4){ long v=0; for(int j=0;j<4;j++)v|=(long)(b[i+j]&0xff)<<(8*j); s.append(String.format("%08x ",v)); }
      println("c0002790: "+s); }catch(Exception e){}
    emu.dispose();
  }
  long enc(long addr){ long seg=(addr>>>28)&0xf; long off=(addr>>>6)&0xffff; return (seg<<16)|off; }
  long readU32(long a) throws Exception { byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v; }
}
