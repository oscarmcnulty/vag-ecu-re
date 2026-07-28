// Emulate from main() (0x80021140) with startup machine-state, to run BSW init incl Com_Init.
// Args: <entryHex> [stepBudget]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.util.*;

public class EmulMain extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long base,int len){ try{ emu.writeMemory(A(base),new byte[len]); }catch(Exception e){ println("zero fail "+Long.toHexString(base)); } }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b); }
  long enc(long addr){ return (((addr>>>28)&0xf)<<16)|((addr>>>6)&0xffff); }
  long rU32(long a) throws Exception { byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v; }

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    int budget=args.length>1?Integer.parseInt(args[1]):2000000;
    emu=new EmulatorHelper(currentProgram);
    // RAM + peripherals
    for(long[] r: new long[][]{{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x8000},{0xf0000000L,0x40000},{0xf0100000L,0x8000},{0xe8000000L,0x1000}}) zero(r[0],(int)r[1]);
    // CSA free list @0xd0004000, 82 x 0x40 (mimic startup)
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa));
    emu.writeRegister("LCX",enc(csa+(n-2)*0x40));
    emu.writeRegister("PCXI",0L);
    emu.writeRegister("PSW",0x00000980L);   // enable CDE/IS-ish; benign
    // base regs + SP + return sentinel
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT);
    emu.writeRegister("pc",entry);

    long lo=0x80020000L, hi=0x80200000L;
    println(String.format("EMULATE main entry=%x budget=%d",entry,budget));
    Map<Long,Integer> hot=new HashMap<>(); long lastCtx=0, maxpc=0; int steps=0; String stop="budget";
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){ stop="main RETURNED"; break; }
        if(pc<lo||pc>=hi){ stop="left-code @"+Long.toHexString(pc); break; }
        if(pc>maxpc)maxpc=pc;
        int c=hot.merge(pc,1,Integer::sum);
        if(c==300000){ stop="HOT-LOOP @"+Long.toHexString(pc); break; }
        if((steps&0x3ffff)==0){
          long ctx=0; try{ctx=rU32(0xc03fc37cL);}catch(Exception e){}
          println(String.format("  step %d  pc=%x  c03fc37c=%x",steps,pc,ctx));
        }
        emu.step(monitor);
      }
    }catch(Exception e){
      long pc=0; try{pc=emu.readRegister("pc").longValue();}catch(Exception e2){}
      stop="FAULT @pc="+Long.toHexString(pc)+" : "+e.getMessage();
    }
    println("STOP after "+steps+" steps: "+stop+"  maxpc="+Long.toHexString(maxpc));
    try{ println(String.format("c03fc37c = %x",rU32(0xc03fc37cL))); }catch(Exception e){}
    // top hot PCs
    hot.entrySet().stream().sorted((x,y)->y.getValue()-x.getValue()).limit(6)
       .forEach(en->println(String.format("  hot pc=%x x%d",en.getKey(),en.getValue())));
    emu.dispose();
  }
}
