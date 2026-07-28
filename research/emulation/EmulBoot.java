// Diagnostic boot emulator: peripheral layer (from EmulPeriph) + call/calli target log
// + per-step c03fc37c write-watch + PC-region histogram + optional trace window.
// Args: <entryHex> [budget] [traceLoHex] [traceHiHex]
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.lang.Register;
import ghidra.program.model.scalar.Scalar;
import java.util.*;

public class EmulBoot extends GhidraScript {
  EmulatorHelper emu;
  Address A(long a){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a); }
  void zero(long b,int l){ try{ emu.writeMemory(A(b),new byte[l]);}catch(Exception e){} }
  void w32(long a,long v) throws Exception { byte[] b=new byte[4]; for(int i=0;i<4;i++)b[i]=(byte)(v>>(8*i)); emu.writeMemory(A(a),b);}
  long enc(long a){ return (((a>>>28)&0xf)<<16)|((a>>>6)&0xffff);}
  long rU32(long a){ try{ byte[] b=emu.readMemory(A(a),4); long v=0; for(int j=0;j<4;j++)v|=(long)(b[j]&0xff)<<(8*j); return v;}catch(Exception e){return -1;} }
  long rreg(String r){ try{ return emu.readRegister(r).longValue(); }catch(Throwable t){ return -1; } }
  boolean isPeriph(long a){ return (a>=0xf0000000L&&a<0xf0110000L); }
  // executable code lives in flash OR in the RAM code region 0xd4000000 (vector/callback trampolines copied at boot)
  boolean inCode(long a){ return (a>=0x80020000L&&a<0x80200000L)||(a>=0xd4000000L&&a<0xd4010000L); }

  // value of the first register operand of an instruction (for calli/ji target resolution)
  long regOperand(Instruction in){
    if(in==null) return Long.MIN_VALUE;
    for(int o=0;o<in.getNumOperands();o++){
      for(Object x:in.getOpObjects(o)) if(x instanceof Register){ try{ return emu.readRegister((Register)x).longValue(); }catch(Exception e){} }
    }
    return Long.MIN_VALUE;
  }

  long loadEA(long pc){
    Instruction in=getInstructionAt(A(pc)); if(in==null) return -1;
    if(!in.getMnemonicString().toLowerCase().startsWith("ld")) return -1;
    for(int o=0;o<in.getNumOperands();o++){
      Object[] objs=in.getOpObjects(o); Register base=null; long disp=0; boolean hasScalar=false;
      for(Object x:objs){ if(x instanceof Register) base=(Register)x; else if(x instanceof Scalar){ disp=((Scalar)x).getSignedValue(); hasScalar=true; } }
      if(base!=null){ try{ return emu.readRegister(base).longValue()+disp; }catch(Exception e){} }
      if(hasScalar && disp!=0) return disp;   // absolute-address load (e.g. ld.bu d2,0xd000177a) -> a completion flag
    }
    return -1;
  }
  boolean pokeable(long a){ return isPeriph(a) || (a>=0xd0000000L&&a<0xd0010000L); }  // HW regs + RAM completion flags

  public void run() throws Exception {
    String[] args=getScriptArgs();
    long entry=Long.parseLong(args[0],16);
    long budget=args.length>1?Long.parseLong(args[1]):60000000L;
    long tlo=args.length>2?Long.parseLong(args[2],16):-1, thi=args.length>3?Long.parseLong(args[3],16):-1;
    long injStep=args.length>4?Long.parseLong(args[4]):-1;   // step at which to inject a sentinel 0x109 frame
    long bridgeStep=args.length>7?Long.parseLong(args[7]):-1;
    long invokeFn=args.length>5?Long.parseLong(args[5],16):-1;// fn to invoke (redirect PC) at injStep, e.g. RX handler
    emu=new EmulatorHelper(currentProgram);
    try{ org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emulate.Emulate", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.app.emulator.DefaultEmulator", org.apache.logging.log4j.Level.OFF);
         org.apache.logging.log4j.core.config.Configurator.setLevel("ghidra.pcode.emu", org.apache.logging.log4j.Level.OFF); }catch(Throwable t){}
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
    // GPIO port INPUT registers high: boot waits on hw "ready/enable" pins (e.g. Port1.0 @0xf0000d24)
    for(long a=0xf0000c00L;a<0xf0001000L;a+=4) w32(a,0xffffffffL);
    for(long a=0xf02fff00L;a<0xf0300000L;a+=4) w32(a,0xffffffffL);
    w32(0xc03fcb04L, 0xf0000240L);

    long lo=0x80020000L, hi=0x80200000L, ctx=0; long steps=0; String stop="budget";
    Map<Long,Long> pokeVal=new HashMap<>();
    Set<Long> tasks=new HashSet<>(Arrays.asList(0x80028348L,0x8002837eL,0x8002842cL,0x80028ccaL));
    Set<Long> tasksSeen=new LinkedHashSet<>();
    LinkedHashSet<Long> callTargets=new LinkedHashSet<>();
    Map<Long,Integer> hist=new HashMap<>();   // PC bucketed by >>8
    ArrayDeque<Long> ring=new ArrayDeque<>(); int breaks=0, skipInsn=0, traceN=0, callN=0, stubSkips=0, forceRets=0, spinStreak=0, spinDiag=0;
    long lastNonzeroCtxPC=0, prevPc=0, spinRegion=0; int nullRecover=0;
    boolean injected=false; byte[] mbase=new byte[0x340]; int sweepIdx=-1, rxStage=0;
    boolean readWatch = args.length>8 && args[8].equals("1"); Set<Long> rwSeen=new HashSet<>();
    // ACC-supervisor invoke-trace + coordinator hunt (activated when invokeFn=801e9b86)
    int accStage=0; boolean invTrace=false; LinkedHashSet<Long> invCalls=new LinkedHashSet<>();
    Set<Long> coordRdSeen=new HashSet<>(); long d7b8a_prev=-1; long tskBasePrev=0; byte[] tskShadow=new byte[0x20];
    boolean fullInit = args.length>6 && args[6].equals("1");   // arg[6]=1 -> take the 801dea38 CAN-init boot path
    Map<Long,Long> fnStub=new HashMap<>(); fnStub.put(0x800b4f80L,0x190L); fnStub.put(0x80021de0L,0x190L);
    // terminal reset/reboot handlers (deadbeef-magic + RST_REQ + do{}while(true)) -> return to caller
    Set<Long> retStub=new HashSet<>(Arrays.asList(0x801d7838L,0x8002ed62L,0x801d7902L));
    if(fullInit){   // force main onto the FULL-init path (801dea38 -> CAN init)
      fnStub.put(0x80028e76L,1L);                 // check_transfer_block -> nonzero
      retStub.add(0x801d5d7eL);                   // skip ADC init subtree (not needed for CAN RX)
    }
    long watchFrom=1000; int wlog=0; byte[] wbase=new byte[0x140];
    println(String.format("BOOT-EMU from %x budget=%d trace=[%x,%x]",entry,budget,tlo,thi));
    try{
      for(;steps<budget;steps++){
        long pc=emu.readRegister("pc").longValue();
        if(pc==SENT){
          // sweep mode: call process_ecu_command_800af8bc(idx) for idx=0..30, watching which writes mirrors
          if(sweepIdx>=0 && sweepIdx<30){ sweepIdx++;
            println(String.format("### SWEEP process_ecu_command(%d)",sweepIdx));
            emu.writeRegister("a11",SENT); emu.writeRegister("pc",0x800af8bcL);
            emu.writeRegister("d4",(long)sweepIdx); prevPc=pc; continue; }
          // RX-chain test: after 8011e8f8 (stage+enqueue) returns, run the deferred queue processor 0x801f8494
          if(rxStage==1){ rxStage=2; println("### RX-CHAIN: invoke deferred processor 0x801f8494");
            emu.writeRegister("a11",SENT); emu.writeRegister("pc",0x801f8494L); prevPc=pc; continue; }
          // then RESUME the scheduler (run-mode) so the generic Com engine can act on the flags the
          // deferred state machine set -> watch for the signal unpack (mirror writes) + any checksum call.
          if(rxStage==2){ rxStage=3; println("### RX-CHAIN: resume run-mode scheduler to catch unpack");
            emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
            emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",SENT);
            emu.writeRegister("d4",0x1200L); emu.writeRegister("pc",0x80021214L); prevPc=pc; continue; }
          // ACC-chain: 801e9b86 returned -> invoke 801df7ac (writes d0007b8a) -> resume scheduler to hunt coordinator
          if(accStage==1){ accStage=2; println(String.format("### ACC-CHAIN: 801e9b86 RETURNED @step%d; d000e2e8=%x -> invoke 801df7ac",steps,rU32(0xd000e2e8L)));
            emu.writeRegister("a11",SENT); emu.writeRegister("pc",0x801df7acL); prevPc=pc; continue; }
          if(accStage==2){ accStage=3; println(String.format("### ACC-CHAIN: 801df7ac RETURNED @step%d; d0007b8a=%x -> resume run-mode scheduler",steps,rU32(0xd0007b8aL)));
            emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
            emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",SENT);
            emu.writeRegister("d4",0x1200L); emu.writeRegister("pc",0x80021214L); prevPc=pc; continue; }
          stop="RETURNED"; break; }
        if(!inCode(pc)){
          // null call / bad indirect transfer (often calli through a 0 fn-ptr in an UNdisassembled region,
          // so the mnemonic stubs above couldn't fire) -> recover by returning to caller (a11).
          long ra=rreg("a11")&0xfffffffeL;
          if(inCode(ra) && ra!=prevPc && nullRecover<20000){ nullRecover++;
            emu.writeRegister("pc",ra); try{emu.writeRegister("d2",0L);}catch(Exception e){}
            if(nullRecover<=40) println(String.format("  [nullcall-recover from %x (pc=%x) -> a11=%x] step%d",prevPc,pc,ra,steps));
            prevPc=pc; continue; }
          Instruction pin=getInstructionAt(A(prevPc)); stop="left @"+Long.toHexString(pc)+" from "+Long.toHexString(prevPc)+" ["+(pin!=null?pin.toString():"?")+"]"; break; }
        hist.merge(pc>>>8,1,Integer::sum);
        // BRIDGE: after init-mode set up CAN (DAT_d00072c4), jump to RUN-mode (process_ecu_state) with
        // RAM/CAN state intact, so the run-mode Com engine will process a staged/mailbox frame.
        if(steps==bridgeStep){
          println(String.format("### BRIDGE to run-mode @step%d DAT_d00072c4=%x",steps,rU32(0xd00072c4L)));
          emu.writeRegister("a0",0xd0008000L); emu.writeRegister("a1",0x80048000L); emu.writeRegister("a8",0x80088800L);
          emu.writeRegister("a10",0xc03fc100L); emu.writeRegister("a11",SENT);
          emu.writeRegister("d4",0x1200L); emu.writeRegister("pc",0x80021214L); prevPc=pc; continue;
        }
        // always-on ACC mirror write-watch (find the scatter engine even from init writes)
        if(steps==watchFrom) wbase=emu.readMemory(A(0xd000d5c0L),0x140);
        if(steps>watchFrom){
          byte[] wc=emu.readMemory(A(0xd000d5c0L),0x140);
          for(int i=0;i<wc.length;i++) if(wc[i]!=wbase[i]){
            if(wlog++<200) println(String.format("  MW %x: %02x->%02x @step%d pc=%x",0xd000d5c0L+i,wbase[i]&0xff,wc[i]&0xff,steps,prevPc));
            wbase[i]=wc[i];
          }
        }
        // inject a distinctive 0x109 ACC_01 frame once, then watch mirror writes
        if(steps==injStep){
          byte[] fr={(byte)0x10,(byte)0x21,(byte)0x32,(byte)0x43,(byte)0x54,(byte)0x65,(byte)0x76,(byte)0x87};
          emu.writeMemory(A(0xd000d40aL),fr);   // staging buffer
          // also pre-load plausible CAN mailbox data regions (TwinCAN node data @0xf0004xxx) with the same
          for(long mb:new long[]{0xf0004100L,0xf0004108L,0xf00040f8L}) emu.writeMemory(A(mb),fr);
          // blast the sentinel frame across every TwinCAN message-object DATA slot + set DLC=8, so
          // read_can_message returns 8 sentinel bytes for whichever object process_ecu_command reads.
          for(long o=0;o<64;o++){ long base=0xf0004600L+o*0x20L;
            try{ emu.writeMemory(A(base+0x18),fr); }catch(Exception e){}   // MODATAL/H
            w32(base,0x08000000L); }                                       // MOFCR DLC=8
          // read_can_message's read loop exits on NCR bit0 (or NFCR bit23); set them so it reads once & returns
          for(long nd=0;nd<8;nd++){ w32(0xf0004200L+nd*0x40L,0x1L); }      // CAN_NCRx |= 1
          w32(0xd000d408L,1L);                 // new-frame flag
          try{ emu.writeMemory(A(0xd000d412L),new byte[]{0}); }catch(Exception e){}
          try{ emu.writeMemory(A(0xd000ad52L),new byte[]{0}); }catch(Exception e){}   // gate open
          try{ emu.writeMemory(A(0xd000d3dcL),new byte[]{1}); }catch(Exception e){}   // mode -> mailbox offset 0
          // ACC-CONSUMER experiment: poke the ACC mirror region with live inputs so 801e9b86 AND the
          // non-analyzed longitudinal coordinator have a real accel/speed/status to process.
          for(long a=0xd000d5c0L;a<0xd000d700L;a++){ try{ emu.writeMemory(A(a),new byte[]{(byte)(0x40|(int)(a&0x3f))}); }catch(Exception e){} }
          w32(0xd000d604L,0x03440344L);   // accel mirror d606 area, distinctive (~ -3.0 raw)
          w32(0xd000d644L,0x00001000L);   // speed mirror d644 (nonzero, above min)
          mbase=emu.readMemory(A(0xd000d000L),0x1000);   // broad mirror baseline d000d000-d000e000
          injected=true;
          println(String.format("### INJECT 0x109 frame F1..F8 @step%d",steps));
          if(invokeFn>0){ emu.writeRegister("a11",SENT); emu.writeRegister("pc",invokeFn);
            if(invokeFn==0x800af8bcL){ sweepIdx=0; emu.writeRegister("d4",0L); println("### SWEEP process_ecu_command(0)"); }
            else if(invokeFn==0x8011e8f8L){ rxStage=1; }   // RX-chain test: stage+enqueue, then deferred proc
            else if(invokeFn==0x801e9b86L){ accStage=1; invTrace=true; println("### ACC-CHAIN: invoke supervisor 801e9b86 (invTrace on)"); }
            else { emu.writeRegister("d4",0xd000d40aL); emu.writeRegister("d5",0L); }
            println(String.format("### INVOKE fn %x (a11=SENT)",invokeFn)); prevPc=pc; continue; }
        }
        if(injected && (steps-injStep)<5000000){
          byte[] cur=emu.readMemory(A(0xd000d000L),0x1000);
          for(int i=0;i<cur.length;i++) if(cur[i]!=mbase[i]){
            println(String.format("  MIRROR %x: %02x -> %02x  @step%d pc=%x",0xd000d000L+i,mbase[i]&0xff,cur[i]&0xff,steps,pc));
            mbase[i]=cur[i];
          }
        }
        if((steps&0xf)==0){ long vt=0x40*(steps/16); for(long a=0xf0000210L;a<=0xf0000228L;a+=4) w32(a,vt); }
        if(steps%15000==0){ w32(0xf0000240L, 0x2000L); }
        // per-step ctx watch
        long c=rU32(0xc03fc37cL);
        if(c!=ctx){ println(String.format(">>> c03fc37c %x->%x @step%d pc=%x  [prev insn / here]",ctx,c,steps,pc)); ctx=c; if(c!=0) lastNonzeroCtxPC=pc; }
        if(tasks.contains(pc)&&tasksSeen.add(pc)) println(String.format("*** TASK %x runs @step%d ctx=%x",pc,steps,c));
        // fn-return stubs: boot-reason readers must return a valid code {0x190,0x290,0x191,0x291} or the
        // firmware self-resets (801d78f4 in CAN init, 8002ed62). Force 0x190 (normal boot).
        if(fnStub.containsKey(pc)){ long ra=rreg("a11")&0xfffffffeL;
          if(ra>=lo&&ra<hi){ emu.writeRegister("d2",fnStub.get(pc)); emu.writeRegister("pc",ra);
            if(stubSkips++<40) println(String.format("  [fn-stub %x -> d2=%x ret %x]",pc,fnStub.get(pc),ra)); prevPc=pc; continue; } }
        // terminal reset/reboot handlers hang (do{}while(true)); we can't reboot -> return to caller so boot continues
        if(retStub.contains(pc)){ long ra=rreg("a11")&0xfffffffeL;
          if(ra>=lo&&ra<hi){ emu.writeRegister("pc",ra);
            if(stubSkips++<40) println(String.format("  [ret-stub reset-handler %x -> ret %x] step%d",pc,ra,steps)); prevPc=pc; continue; } }
        Instruction in=getInstructionAt(A(pc));
        String mn=in!=null?in.getMnemonicString().toLowerCase():"?";
        boolean isCall = mn.startsWith("call");
        // READ-WATCH: catch whoever reads the raw 0x109 frame — staging buffer d000d40a-d000d411 and the
        // TwinCAN message-object DATA regs 0xf0004600-0xf00046ff. The reader is the Com RX unpack we seek.
        if(readWatch && injected && mn.startsWith("ld")){ long ea=loadEA(pc);
          if(ea>=0 && (ea>=0xd000d5c0L&&ea<0xd000d700L) && rwSeen.add(pc)){   // ACC mirror region (accel d606 etc.)
            ghidra.program.model.listing.Function fn=getFunctionContaining(A(pc));
            println(String.format("  RD-ACC %x reads [%x] %s (fn %s) @step%d",pc,ea,in.toString(),fn!=null?fn.getName():"?",steps)); } }
        // COORDINATOR read-watch: whoever reads the decel cal 0x8004dd90 curve OR d0007b8a (ACC torque limit) is the
        // longitudinal coordinator (both have ZERO static readers per handoff). Active during the ACC-chain invoke.
        if(invTrace && mn.startsWith("ld")){ long ea=loadEA(pc); long eap=ea&0x9fffffffL;
          if(ea>=0 && ((eap>=0x8004dd90L&&eap<0x8004ddc0L) || (ea>=0xd0007b88L&&ea<0xd0007b90L)) && coordRdSeen.add(pc)){
            ghidra.program.model.listing.Function fn=getFunctionContaining(A(pc));
            println(String.format("  !!! COORD-RD %x reads [%x] %s (fn %s) @step%d",pc,ea,in.toString(),fn!=null?fn.getName():"?",steps)); } }
        // stub-skip indirect CALLs to non-flash-code targets (null/ROM/RAM fn-pointers we can't execute).
        // ROM/bootloader (0-0x20000) is blank in this OBD dump, so any fn-ptr read from there is 0.
        if(mn.equals("calli")||mn.equals("jli")){
          long tgt=regOperand(in)&0xfffffffeL;
          if(!inCode(tgt)){
            int len=in.getLength(); emu.writeRegister("pc",pc+len);
            try{ emu.writeRegister("d2",0L);}catch(Exception e){}
            stubSkips++;
            if(stubSkips<=40) println(String.format("  [stub-skip %s @%x -> %x] step%d",mn,pc,tgt,steps));
            prevPc=pc; continue;
          }
        }
        // indirect JUMP (ji) to a bad target = tail-call through a null ROM pointer -> return to caller (a11)
        if(mn.equals("ji")){
          long tgt=regOperand(in)&0xfffffffeL;
          if(!inCode(tgt)){
            long ra=rreg("a11")&0xfffffffeL;
            if(inCode(ra)){ emu.writeRegister("pc",ra); stubSkips++;
              if(stubSkips<=40) println(String.format("  [ji-ret @%x tgt=%x -> a11=%x] step%d",pc,tgt,ra,steps));
              prevPc=pc; continue; }
          }
        }
        // optional trace window
        if(tlo>=0 && pc>=tlo && pc<thi && traceN<400){ traceN++;
          println(String.format("  T %x %-18s d8=%x d9=%x d15=%x a15=%x a12=%x a4=%x",pc,in!=null?in.toString():"?",
              rreg("d8"),rreg("d9"),rreg("d15"),rreg("a15"),rreg("a12"),rreg("a4"))); }
        // spin detection / region-based busy-wait breaker with force-return escalation.
        // Exempt the scheduler dispatch loop (we WANT that to run once reached; its poke makes it tick).
        boolean inSched = (pc>=0x80021300L && pc<0x80021372L);
        ring.addLast(pc); if(ring.size()>6000){ ring.pollFirst();
          if((steps&0xfff)==0){ HashSet<Long> s=new HashSet<>(ring);
            if(s.size()<=120){                 // stuck in a small PC region (single- or multi-insn poll loop)
              long region=Long.MAX_VALUE; for(long x:s) region=Math.min(region,x);
              if(region==spinRegion) spinStreak++; else { spinRegion=region; spinStreak=1; }
              // DIAGNOSTIC: on first detection, dump the loop's PCs + what each load reads (find the polled reg)
              if(spinStreak==1 && spinDiag<12){ spinDiag++;
                java.util.List<Long> sl=new java.util.ArrayList<>(s); java.util.Collections.sort(sl);
                StringBuilder sb=new StringBuilder(String.format("  SPINDIAG reg=%x n=%d @step%d loads:",region,s.size(),steps));
                for(long ppc:sl){ Instruction li=getInstructionAt(A(ppc)); long ea=loadEA(ppc);
                  if(li!=null && li.getMnemonicString().toLowerCase().startsWith("ld") && ea>0) sb.append(String.format(" %x=[%x]",ppc,ea)); }
                println(sb.toString());
                StringBuilder pb=new StringBuilder("    pcs:"); for(long ppc:sl) pb.append(String.format(" %x",ppc)); println(pb.toString()); }
              // Only intervene on HARDWARE-WAIT loops (they read a peripheral 0xf000xxxx). Legitimate long
              // loops (memset/memcpy/init-pattern fills, compute state machines) read only RAM -> LET THEM RUN.
              boolean poked=false;
              for(long ppc:s){ long ea=loadEA(ppc); if(ea>=0 && pokeable(ea)){ w32(ea&~3L,0xffffffffL); poked=true; } }
              // known HW handshakes whose polled address is computed (loadEA can't resolve): treat as HW wait
              boolean canSpin = (region>=0x8002e3a4L && region<0x8002e520L);
              if(canSpin){ for(long a=0xf0004000L;a<0xf0005000L;a+=4) w32(a,0xffffffffL); }
              if(poked||canSpin){                      // a genuine peripheral wait
                breaks++; if(breaks<=25) println(String.format("  [poke HW spin @%x reg=%x streak=%d can=%b] step%d",pc,region,spinStreak,canSpin,steps));
                if(spinStreak>(canSpin?400:60) && !inSched){   // poking didn't escape -> force-return
                  long ra=rreg("a11")&0xfffffffeL;
                  if(ra>=lo&&ra<hi){ emu.writeRegister("pc",ra); try{emu.writeRegister("d2",0L);}catch(Exception e){}
                    forceRets++; spinStreak=0; spinRegion=0; ring.clear();
                    if(forceRets<=40) println(String.format("  [force-ret spin reg=%x -> a11=%x] step%d",region,ra,steps));
                    prevPc=pc; continue; } }
              }
              ring.clear(); } } }
        prevPc=pc;
        try{ emu.step(monitor); }catch(Exception se){}
        long np=emu.readRegister("pc").longValue();
        // CHECKSUM-CALL WATCH: flag any call/transfer to a checksum primitive during the RX chain
        if(injected && (np==0x800a5a18L||np==0x800a59f0L||np==0x800a5a5eL||(np>=0x801f8340L&&np<0x801f83f0L)))
          println(String.format("  !!! CHECKSUM-FN reached %x from %x @step%d",np,pc,steps));
        if(isCall && np>=lo && np<hi && np!=pc+ (in!=null?in.getLength():2)){
          if(callTargets.add(np)){ callN++;
            if(callN<=300) println(String.format("  call %x -> %x  (ctx=%x)",pc,np,c)); }
          // uncapped call-trace for the invoked ACC chain (distinct caller->target pairs)
          if(invTrace && invCalls.add((pc<<20)^np)) println(String.format("  INV-CALL %x -> %x @step%d",pc,np,steps));
        }
        // WRITE-WATCH on d0007b8a (ACC torque limit) while invoke-tracing: prevPc = the writer PC
        if(invTrace){ long v=rU32(0xd0007b8aL); if(v!=d7b8a_prev){
          if(d7b8a_prev!=-1) println(String.format("  WW d0007b8a: %x->%x @step%d pc=%x",d7b8a_prev,v,steps,prevPc)); d7b8a_prev=v; } }
        if(np==pc){
          Instruction in2=getInstructionAt(A(pc)); int len=in2!=null?in2.getLength():2;
          try{ emu.writeMemory(A(pc), new byte[len]); }catch(Exception e){}
          emu.writeRegister("pc", pc+len); skipInsn++;
          if(skipInsn<=60) println(String.format("  [nop-patch @%x %s]",pc,mn));
        }
      }
    }catch(Exception e){
      long pc=rreg("pc");
      stop="FAULT @pc="+Long.toHexString(pc)+" : "+e.getMessage();
    }
    println("STOP "+steps+" steps, hw-breaks="+breaks+" skip-insn="+skipInsn+" callTargets="+callTargets.size()+": "+stop);
    println(String.format("FINAL c03fc37c=%x c03fcb04=%x tasks_ran=%s lastNonzeroCtxPC=%x",rU32(0xc03fc37cL),rU32(0xc03fcb04L),tasksSeen,lastNonzeroCtxPC));
    // top PC buckets
    List<Map.Entry<Long,Integer>> hs=new ArrayList<>(hist.entrySet());
    hs.sort((x,y)->y.getValue()-x.getValue());
    StringBuilder sb=new StringBuilder("HOT PC-regions (bucket<<8): ");
    for(int i=0;i<Math.min(12,hs.size());i++) sb.append(String.format("%x:%d ",hs.get(i).getKey()<<8,hs.get(i).getValue()));
    println(sb.toString());
    StringBuilder mb=new StringBuilder("ACC mirrors d000d5c0-d000d6ff:");
    for(long a=0xd000d5c0L;a<0xd000d700L;a+=4){ long v=rU32(a); if(v!=0) mb.append(String.format(" [%x]=%x",a,v)); }
    println(mb.toString());
    // walk the materialized Com context so the RX PDU chain / shadow buffers are visible
    long cctx=rU32(0xc03fc37cL);
    println(String.format("=== CONTEXT WALK ctx=%x ===",cctx));
    if(cctx>0 && cctx<0xe0000000L){
      dumpMem("ctx",cctx,0x40);
      long p1c=rU32(cctx+0x1c), p10=rU32(cctx+0x10), p18=rU32(cctx+0x18), p14=rU32(cctx+0x14);
      println(String.format("ctx+0x10=%x +0x14=%x +0x18=%x +0x1c=%x",p10,p14,p18,p1c));
      if(p1c>0&&p1c<0xe0000000L){ dumpMem("ctx.1c",p1c,0x60);
        long q14=rU32(p1c+0x14),q24=rU32(p1c+0x24),q3c=rU32(p1c+0x3c),q44=rU32(p1c+0x44);
        println(String.format("  [1c]+0x14=%x +0x24=%x +0x3c=%x +0x44=%x",q14,q24,q3c,q44));
        for(long[] q:new long[][]{{q14,0x20},{q24,0x40},{q44,0x20}}) if(q[0]>0&&q[0]<0xe0000000L) dumpMem("  sub",q[0],(int)q[1]);
      }
      if(p10>0&&p10<0xe0000000L) dumpMem("ctx.10",p10,0x40);
      if(p18>0&&p18<0xe0000000L) dumpMem("ctx.18",p18,0x30);
    }
    // dump the post-staging 0x109 RAM trampoline (halt_baddata_d40016f8) + its arg DAT_d4001bc8
    println("=== 0x109 post-staging: RAM trampoline @d40016f8, arg DAT_d4001bc8 ===");
    dumpMem("  d40016f8",0xd40016f8L,0x30);
    println(String.format("  DAT_d4001bc8 = %x  DAT_d000d400 = %x  DAT_d000d3dc=%x",rU32(0xd4001bc8L),rU32(0xd000d400L),rU32(0xd000d3dcL)));
    dumpMem("  d40016c0",0xd40016c0L,0x40);
    // SCAN RAM for checksum-fn pointers (dynamically-assigned E2E/checksum tables). If Com/E2E_Init
    // wrote 0x800a5a18 (CRC8-H2F) / 0x800a59f0 (CRC16) into a runtime table, find where.
    println("=== scan RAM for checksum-fn pointers (dynamic assignment?) ===");
    // find the ACC dispatch table OR a runtime-resolved pointer to the decel cal curve 0x8004dd90
    long[] targets={0x801e9b86L,0x801df7acL,0x8004dd90L,0x8004dda0L,0xa004dd90L,0xa004dda0L,0x8004dd8eL,0x8004dd92L};
    for(long[] rg:new long[][]{{0xc0000000L,0x420000},{0xd0000000L,0x10000},{0xd4000000L,0x10000}}){
      for(long a=rg[0];a<rg[0]+rg[1];a+=4){ long v=rU32(a);
        for(long t:targets) if(v==t){ println(String.format("  RAM[%x]=%x  table: -8=%x -4=%x +4=%x +8=%x +c=%x +10=%x",a,v,rU32(a-8),rU32(a-4),rU32(a+4),rU32(a+8),rU32(a+0xc),rU32(a+0x10))); } } }
    // walk the deferred RX queue at DAT_d4001bc8 (0xd4001970) and its nodes (+0x4 = process handler)
    long q=rU32(0xd4001bc8L); println(String.format("=== RX queue DAT_d4001bc8=%x head=%x ===",0xd4001bc8L,q));
    if(q>0xd0000000L){ dumpMem("  queuehead",q,0x20); for(int k=0;k<6;k++){ long nx=rU32(q); if(nx<=0xd0000000L||nx==q)break; dumpMem("  qnode",nx,0x18); q=nx; } }
    // the background callbacks dispatched by the watchdog-service helper (800b3d22/2e)
    long cb0=rU32(0xc00028a0L), cb1=rU32(0xc00028a4L);
    println(String.format("=== bg callbacks: *(c00028a0)=%x *(c00028a4)=%x ===",cb0,cb1));
    for(long cb:new long[]{cb0,cb1}){ if(cb>=lo&&cb<hi){ dumpMem("  cbstruct",cb,0x10);
      long fn=rU32(cb); println(String.format("    callback fn=%x arg=%x",fn,rU32(cb+4))); } }
    // resolve the 0x109 RX dispatch target: 8011e8f8 -> 800b15d6 -> *(DAT_d00072c4+0x28..0x34)
    long d72c4=rU32(0xd00072c4L);
    println(String.format("=== DAT_d00072c4=%x  handlers +0x28..+0x34: %x %x %x %x ===",d72c4,
      rU32(d72c4+0x28),rU32(d72c4+0x2c),rU32(d72c4+0x30),rU32(d72c4+0x34)));
    // dump the RAM interrupt-vector table (BIV=0xd4000000): find entries that reach CAN driver code
    println("=== BIV vector table 0xd4000000 (nonzero 32-byte entries) ===");
    for(long pr=0;pr<128;pr++){ long base=0xd4000000L+pr*0x20; long w0=rU32(base),w1=rU32(base+4),w2=rU32(base+8),w3=rU32(base+0xc);
      if((w0|w1|w2|w3)!=0) println(String.format("  pri%d @%x: %08x %08x %08x %08x %08x %08x %08x %08x",pr,base,
        w0,w1,w2,w3,rU32(base+0x10),rU32(base+0x14),rU32(base+0x18),rU32(base+0x1c))); }
    emu.dispose();
  }
  void dumpMem(String tag,long a,int n){
    StringBuilder s=new StringBuilder(String.format("%s @%x:",tag,a));
    for(int i=0;i<n;i+=4){ long v=rU32(a+i); s.append(String.format(" %08x",v)); if((i&0x1c)==0x1c) s.append("\n   "); }
    println(s.toString());
  }
}
