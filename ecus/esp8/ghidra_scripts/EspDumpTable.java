// Dump a record table: args = baseHex countDec strideBytes wordsPerRecord
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
public class EspDumpTable extends GhidraScript {
  public void run() throws Exception {
    String[] a=getScriptArgs();
    long base=Long.parseLong(a[0],16); int cnt=Integer.parseInt(a[1]);
    int stride=Integer.parseInt(a[2]); int words=Integer.parseInt(a[3]);
    Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    for(int i=0;i<cnt;i++){ long rec=base+(long)i*stride; StringBuilder sb=new StringBuilder();
      sb.append(String.format("#%3d @0x%06x:",i,rec));
      for(int w=0;w<words;w++){ int v=mem.getInt(sp.getAddress(rec+4L*w)); sb.append(String.format(" %08x",v)); }
      println(sb.toString());
    }
  }
}
