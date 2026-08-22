// SH-2A init emulator (batch): run boot init functions under EmulatorHelper with RAM+peripherals
// mapped zeroed, accumulating RAM state across all entries, then emit every RAM word that ends
// holding a pointer. Authoritative resolver for RAM base installs (validated more correct than
// the static init-stub deref, which mis-resolved some pool words).
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript InitEmu.java <out.csv> <entriesFile|entry[:r4] ...>
// entriesFile: a file of space/line-separated hex entries. Output CSV: ram_addr,value.
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import java.io.*; import java.nio.file.*; import java.util.*;
public class InitEmu extends GhidraScript {
  static final long RLO=0xfff80000L, RLEN=0x40000L, STACK=0xfffbf000L, RET=0x2L;
  public void run() throws Exception {
    String[] a=getScriptArgs();
    String out=a[0];
    List<long[]> ents=new ArrayList<>();
    for(int i=1;i<a.length;i++){
      String arg=a[i];
      File f=new File(arg);
      if(f.exists()){
        for(String tok: new String(Files.readAllBytes(f.toPath())).split("\\s+"))
          if(!tok.isEmpty()) ents.add(new long[]{Long.parseLong(tok.trim(),16),0});
      } else {
        String[] pp=arg.split(":");
        ents.add(new long[]{Long.parseLong(pp[0],16), pp.length>1?Long.parseLong(pp[1],16):0});
      }
    }
    EmulatorHelper eh=new EmulatorHelper(currentProgram);
    byte[] zeros=new byte[0x10000];
    for(long base=0xfff80000L; base<0x100000000L; base+=0x10000L) eh.writeMemory(toAddr(base),zeros);
    byte[] before=eh.readMemory(toAddr(RLO),(int)RLEN);
    int ran=0, aborted=0;
    for(long[] e: ents){
      try {
        eh.writeRegister("r4",e[1]); eh.writeRegister("r15",STACK); eh.writeRegister("pr",RET);
        eh.writeRegister("pc",e[0]); eh.setBreakpoint(toAddr(RET));
        for(int s=0;s<200000;s++){
          long pc=eh.readRegister("pc").longValue()&0xffffffffL;
          if(pc==RET||pc==0) break;
          if(!eh.step(monitor)) break;
        }
        ran++;
      } catch(Throwable t){ aborted++; }
    }
    byte[] after=eh.readMemory(toAddr(RLO),(int)RLEN);
    TreeMap<Long,Long> inst=new TreeMap<>();
    for(int o=0;o+3<after.length;o+=4){
      long bv=word(before,o), av=word(after,o);
      if(bv==av) continue;
      if((0x6000<=av&&av<0x200000)||(0xfff80000L<=av&&av<=0xfffbffffL)) inst.put(RLO+o,av);
    }
    StringBuilder sb=new StringBuilder("ram_addr,value\n");
    for(Map.Entry<Long,Long> en: inst.entrySet()) sb.append(String.format("0x%08x,0x%08x%n",en.getKey(),en.getValue()));
    try(FileWriter fw=new FileWriter(out)){ fw.write(sb.toString()); }
    eh.dispose();
    println("InitEmu: ran="+ran+" aborted="+aborted+" -> "+inst.size()+" pointer RAM installs -> "+out);
  }
  static long word(byte[] b,int o){ return ((b[o]&0xffL)<<24)|((b[o+1]&0xffL)<<16)|((b[o+2]&0xffL)<<8)|(b[o+3]&0xffL); }
}
