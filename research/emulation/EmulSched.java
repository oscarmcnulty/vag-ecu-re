// Drive the cyclic scheduler by injecting the polled STM timer flag; run tasks; watch c03fc37c.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import java.util.*;

public class EmulSched extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a) throws Exception { byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    int budget=args.length>1?Integer.parseInt(args[1]):20000000;
    emu=new EmulatorHelper(currentProgram);
    for(long[] r: new long[][]{{0x00000000L,0x1000},{0xc0000000L,0x10000},{0xc03f0000L,0x10000},{0xd0000000L,0x10000},
        {0xd4000000L,0x8000},{0xf0000000L,0x40000},{0xf0100000L,0x8000},{0xe8000000L,0x1000}}) zero(r[0],(int)r[1]);
    long csa=0xd0004000L; int n=82;
    for(int i=0;i<n;i++) w32(csa+i*0x40, i<n-1?enc(csa+(i+1)*0x40):0);
    emu.writeRegister("FCX",enc(csa)); emu.writeRegister("LCX",enc(csa+(n-2)*0x40)); emu.writeRegister("PCXI",0L);
    emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
    emu.writeRegister("a10",0xc03fc100L);
    long SENT=0xd0003ff0L; emu.writeRegister("a11",SENT); emu.writeRegister("pc",entry);

    long lo=0x80020000L, hi=0x80200000L;
    long ctx=0, cb04=0; int steps=0, ticks=0, skips=0; String stop="budget";
    Map<Long,Integer> win=new HashMap<>(); long winStart=0;
    Set<Long> tasks=new HashSet<>(Arrays.asList(0x80028348L,0x8002837eL,0x8002842cL,0x80028ccaL));
    println("SCHED-DRIVE from "+Long.toHexString(entry));
    long lastpc=0; int same=0;
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){ stop="RETURNED"; break; }
        if(pc<lo||pc>=hi){ stop="left @"+Long.toHexString(pc); break; }
        if(tasks.contains(pc) && steps%1==0){ /* task entered */ }
        // ctx watch
        if((steps&0x7ff)==0){ long c=rU32(0xc03fc37cL); if(c!=ctx){ println(String.format(">>> c03fc37c %x->%x @step%d pc=%x ticks=%d",ctx,c,steps,pc,ticks)); ctx=c; }
          long p=rU32(0xc03fcb04L); if(p!=cb04){ println(String.format("    c03fcb04(STM ptr) -> %x @step%d",p,steps)); cb04=p; } }
        // spin window detect over 3000-step windows
        if(steps-winStart>3000){
          if(win.size()<=6){ // tight spin -> inject STM flag bit13 at *c03fcb04
            long p=0; try{p=rU32(0xc03fcb04L);}catch(Exception e){}
            boolean injected=false;
            if(p>=0xf0000000L && p<0xf0110000L){ try{ long v=rU32(p); w32(p, v|0x2000L); ticks++; injected=true; }catch(Exception e){} }
            if(!injected){ // not STM -> force-return to punch busy-wait
              long ra=emu.readRegister("a11").longValue();
              if(ra>=lo&&ra<hi){ emu.writeRegister("pc",ra); skips++;
                if(skips<=30) println(String.format("  [skip @%x ret %x] step%d win=%s",pc,ra,steps, win.keySet().stream().map(Long::toHexString).sorted().reduce((x,y)->x+","+y).orElse("")));
                if(skips>5000){ stop="too many skips @"+Long.toHexString(pc); break; } }
            }
            if(ticks%2000==1 && injected) println(String.format("  [STM tick %d @step%d] ctx=%x",ticks,steps,rU32(0xc03fc37cL)));
          }
          win.clear(); winStart=steps;
        }
        win.merge(pc,1,Integer::sum);
        emu.step(monitor);
      }
    }catch(Exception e){
      long pc=0; try{pc=emu.readRegister("pc").longValue();}catch(Exception e2){}
      stop="FAULT @pc="+Long.toHexString(pc)+" : "+e.getMessage();
    }
    println("STOP "+steps+" steps ticks="+ticks+" skips="+skips+": "+stop);
    try{ println(String.format("FINAL c03fc37c=%x  c03fcb04=%x",rU32(0xc03fc37cL),rU32(0xc03fcb04L))); }catch(Exception e){}
    emu.dispose();
  }
}
