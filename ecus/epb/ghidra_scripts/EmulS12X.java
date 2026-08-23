// S12X (HCS12X) emulator on Ghidra's EmulatorHelper, with a control-flow-aware shadow stack that
// solves paged CALL/RTC: Ghidra's SLEIGH computes CALL targets with a flat flash formula and RTC
// returns to a bare 16-bit local, neither matching this project's paged memory layout. We predict
// each CALL/JSR target from its operands (mapped to our global layout) and track returns on a shadow
// stack, overriding the emulator's execute address after every control-flow instruction.
// Layout: windowed 0x8000-0xBFFF -> 0x400000|(page<<14)|off ; fixed-low 0x4000-0x7FFF -> 0x7F4000+ ;
// fixed-high 0xC000-0xFFFF -> 0x7FC000+ ; RAM/regs via the `segment` userop (data path).
// Args: <entryHex> <maxSteps> [watchLo:watchHi] [mem=addr:val ...] [reg=val ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.pcode.emulate.BreakCallBack;
import ghidra.pcode.pcoderaw.PcodeOpRaw;
import java.math.BigInteger;
import java.util.ArrayDeque;

public class EmulS12X extends GhidraScript {
  // (local addr, page) -> global, per this project's layout
  long paged(int addr, int page){
    if(addr>=0x8000 && addr<=0xBFFF) return 0x400000L | ((long)(page&0xff)<<14) | (addr & 0x3FFF);
    if(addr>=0x4000 && addr<=0x7FFF) return 0x7F4000L + (addr-0x4000);   // fixed-low page 0xFD
    if(addr>=0xC000)                 return 0x7FC000L + (addr-0xC000);   // fixed-high page 0xFF
    return addr;
  }
  int globPage(long g){
    if(g>=0x780000 && g<0x79c000) return 0xE0 + (int)((g-0x780000)/0x4000);
    if(g>=0x7e0000 && g<0x7f8000) return 0xF8 + (int)((g-0x7e0000)/0x4000);
    if(g>=0x7f4000 && g<0x7f8000) return 0xFD;
    return -1;
  }
  long segData(long a){
    if(a>=0x2000 && a<=0x2FFF) return 0xFE000L | (a & 0xFFF);
    if(a>=0x3000 && a<=0x3FFF) return 0xFF000L | (a & 0xFFF);
    if(a>=0x1000 && a<=0x1FFF) return 0xFD000L | (a & 0xFFF);
    return a;
  }
  int entryPage(long g){ if(g>=0x780000&&g<0x79c000) return 0xE0+(int)((g-0x780000)/0x4000); if(g>=0x7e0000&&g<0x7f8000) return 0xF8+(int)((g-0x7e0000)/0x4000); return 0xfe; }
  void setReg(EmulatorHelper e,String n,long v){ Register r=currentProgram.getRegister(n); if(r!=null) e.writeRegister(r,BigInteger.valueOf(v)); }
  void resetCtx(EmulatorHelper e){ setReg(e,"Prefix18",0); setReg(e,"UseGPAGE",0); setReg(e,"XGATE",0); }
  int u8(long a){ try{ return getByte(toAddr(a))&0xff; }catch(Exception e){ return -1; } }

  public void run() throws Exception {
    String[] a=getScriptArgs();
    long entry=Long.decode(a[0]); int maxSteps=Integer.decode(a[1]);
    long wlo=-1,whi=-1;
    for(String s:a){ if(s.contains(":")&&!s.contains("=")){String[] p=s.split(":");wlo=Long.decode(p[0]);whi=Long.decode(p[1]);} }

    EmulatorHelper emu=new EmulatorHelper(currentProgram);
    emu.registerCallOtherCallback("segment", new BreakCallBack(){
      public boolean pcodeCallback(PcodeOpRaw op){
        long b=emulate.getMemoryState().getValue(op.getInput(1));
        long in=emulate.getMemoryState().getValue(op.getInput(2));
        emulate.getMemoryState().setValue(op.getOutput(), b ^ in); return true; }});
    emu.registerDefaultCallOtherCallback(new BreakCallBack(){ public boolean pcodeCallback(PcodeOpRaw op){
      try{ if(op.getOutput()!=null) emulate.getMemoryState().setValue(op.getOutput(), 0); }catch(Exception e){} return true; }});
    emu.writeMemory(toAddr(0x0), new byte[0x4000]);            // direct low view (regs+RAM)
    emu.writeMemory(toAddr(0xf0000L), new byte[0x10000]);       // RAM RPAGE windows (RPAGE 0xf0-0xff)
    emu.writeMemory(toAddr(0x100000L), new byte[0x8000]);       // EPAGE window
    emu.writeMemory(toAddr(0x37), new byte[]{(byte)0x08});
    emu.writeMemory(toAddr(0xfc037L), new byte[]{(byte)0x08});
    int epage=entryPage(entry);
    setReg(emu,"PPAGE",epage); setReg(emu,"RPAGE",0xfd); setReg(emu,"EPAGE",0xfe);
    setReg(emu,"physPage",epage); setReg(emu,"SP",0x3f00);
    for(String s:a){ if(s.startsWith("mem=")){String[] p=s.substring(4).split(":");long da=segData(Long.decode(p[0]));emu.writeMemory(toAddr(da),new byte[]{(byte)Long.decode(p[1]).intValue()});println("  preset "+p[0]+" -> data@"+Long.toHexString(da)+"="+p[1]);}
      else if(s.contains("=")&&!s.startsWith("mem")){String[] p=s.split("=");setReg(emu,p[0],Long.decode(p[1]));} }
    emu.writeRegister("PCE", BigInteger.valueOf(entry));
    emu.getEmulator().setExecuteAddress(entry);
    println(String.format("EMUL start=%06x SP=3f00 steps<=%d", entry, maxSteps));

    ArrayDeque<Long> shadow=new ArrayDeque<>();
    long prev=-1; int stall=0; long winLo=Long.MAX_VALUE, winHi=0; int winCnt=0; int stepN=0; int skipped=0;
    for(int i=0;i<maxSteps;i++){ stepN=i;
      long ea=emu.getExecutionAddress().getOffset();
      if(ea==prev){ if(++stall>4){ println("  STALL @"+Long.toHexString(ea)); break; } } else stall=0;
      prev=ea;
      if(i%5000==0 && i>0) println(String.format("  ...[%d] PCE=%06x B=%02x IX=%04x IY=%04x SP=%04x",i,ea,emu.readRegister("B").intValue()&0xff,emu.readRegister("IX").intValue()&0xffff,emu.readRegister("IY").intValue()&0xffff,emu.readRegister("SP").intValue()&0xffff));
      // spin-window detector: 4000 consecutive steps confined to a 0x100-byte range -> stuck loop
      if(ea<winLo)winLo=ea; if(ea>winHi)winHi=ea; winCnt++;
      if(winCnt>=4000){ if(winHi-winLo<=0x100){ println(String.format("  SPIN in [%06x,%06x] after %d steps",winLo,winHi,i)); break; } winLo=Long.MAX_VALUE; winHi=0; winCnt=0; }
      int op=u8(ea), ppg=emu.readRegister("PPAGE").intValue()&0xff, ep=globPage(ea);
      if(op<0){ println(String.format("  UNMAPPED code @%06x (off-the-rails: computed call to unpopulated ptr / absent bootloader) shadowTop=%s",ea, shadow.isEmpty()?"-":Long.toHexString(shadow.peek()))); break; }
      int kind=0; long tgt=-1, ret=0;
      if(op==0x4A){ int ad=(u8(ea+1)<<8)|u8(ea+2); int pg=u8(ea+3); tgt=paged(ad,pg); ret=ea+4; kind=1; }
      else if(op==0x16){ int ad=(u8(ea+1)<<8)|u8(ea+2); tgt=paged(ad, ep>=0?ep:ppg); ret=ea+3; kind=1; }
      else if(op==0x4B){ int pb=u8(ea+1); int len;
          if((pb&0x20)==0) len=2;
          else if((pb&0xE7)==0xE2||(pb&0xE7)==0xE3) len=4;
          else if(pb==0xE0||pb==0xE1||pb==0xE8||pb==0xE9||pb==0xF0||pb==0xF1||pb==0xF8||pb==0xF9) len=3;
          else len=2;
          ret=ea+len; kind=3; }
      else if(op==0x0A||op==0x3D){ kind=2; }
      boolean bad=false;
      try{ if(!emu.step(monitor)){ bad=true; } }catch(Exception e){ bad=true; }
      if(bad){ if(!shadow.isEmpty()){ long r=shadow.pop(); emu.getEmulator().setExecuteAddress(r);
          setReg(emu,"PCE",r); skipped++; continue; }
        else { println("  step false @"+Long.toHexString(ea)+" (top-level, done) skipped="+skipped); break; } }
      if(kind==1){ shadow.push(ret); if(tgt>=0){ emu.getEmulator().setExecuteAddress(tgt); resetCtx(emu);
          if(i<200) println(String.format("  CALL [%3d] %06x -> %06x  ret=%06x  B=%02x IX=%04x IY=%04x",i,ea,tgt,ret,emu.readRegister("B").intValue()&0xff,emu.readRegister("IX").intValue()&0xffff,emu.readRegister("IY").intValue()&0xffff)); } }
      else if(kind==2){ if(!shadow.isEmpty()){ long r=shadow.pop(); emu.getEmulator().setExecuteAddress(r); resetCtx(emu);
          if(i<200) println(String.format("  RET  [%3d] %06x -> %06x",i,ea,r)); }
          else { println(String.format("  RET  [%3d] %06x -> (top-level return, done)",i,ea)); break; } }
      else if(kind==3){ shadow.push(ret); long na=emu.getExecutionAddress().getOffset();
          if(i<300) println(String.format("  ICALL[%3d] %06x -> %06x (indexed) IY=%04x",i,ea,na,emu.readRegister("IY").intValue()&0xffff)); }
      else { long na=emu.getExecutionAddress().getOffset(); if(na<0x10000 && !shadow.isEmpty()){ long r=shadow.pop(); emu.getEmulator().setExecuteAddress(r); } }
    }
    println(String.format("EMUL end steps=%d: A=%02x B=%02x IX=%04x IY=%04x", stepN,emu.readRegister("A").intValue()&0xff,emu.readRegister("B").intValue()&0xff,emu.readRegister("IX").intValue()&0xffff,emu.readRegister("IY").intValue()&0xffff));
    if(wlo>=0){ long dl=segData(wlo); println("WATCH "+Long.toHexString(wlo)+" (data@"+Long.toHexString(dl)+"):");
      byte[] m=emu.readMemory(toAddr(dl),(int)(whi-wlo)); StringBuilder sb=new StringBuilder();
      for(int i=0;i<m.length;i++){ sb.append(String.format("%02x",m[i]&0xff)); if(i%16==15){println("  "+Long.toHexString(wlo+i-15)+": "+sb);sb.setLength(0);} }
      if(sb.length()>0) println("  "+sb); }
    emu.dispose();
  }
}
