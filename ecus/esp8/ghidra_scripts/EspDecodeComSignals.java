// Decode the ESP8 AUTOSAR-COM explicit signal tables and label every signal destination buffer,
// so COM functions decompile with named buffers (com_sig_<id>_buf) instead of DAT_004xxxxx.
//
// Tables (flash, static): 0xb038c stride 0x10 {marker 0x01000000, sig u16@+4, len u8@+6,
// flags @+7, RAM_buffer u32@+8, extraction_link u32@+c}; 0xb06f0 stride 0xc {sig u16@+0,
// len u8@+2, flags @+3, RAM_buffer u32@+4, idx u16@+8, grp u8@+a}. Both list the front-sensor/
// ACC/ANB signals with static app buffers (the object-table bulk set is NOT here).
//   analyzeHeadless <proj> ESP8 -process 8R0907379BG_0030.bin -noanalysis \
//       -scriptPath ecus/esp8/ghidra_scripts -postScript EspDecodeComSignals.java
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.symbol.SourceType;

public class EspDecodeComSignals extends GhidraScript {
    Memory mem;
    Address a(long v){ return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v); }
    int u8(long o) throws Exception { return mem.getByte(a(o))&0xff; }
    int u16(long o) throws Exception { return ((u8(o))<<8)|u8(o+1); }
    long u32(long o) throws Exception { return ((long)u16(o)<<16)|u16(o+2); }

    void labelBuf(long buf,int sig,int len,String src,java.util.Set<Long> seen) throws Exception {
        if (buf<0x403000L || buf>=0x40b000L) return;
        if (!seen.add(buf)) return;
        Address ba=a(buf);
        if (getSymbolAt(ba)!=null && getSymbolAt(ba).getSource()==SourceType.USER_DEFINED) return; // CSV label wins
        String nm=String.format("com_sig_%04x_buf", sig);
        try { createLabel(ba, nm, true, SourceType.USER_DEFINED); } catch(Exception e){}
        setPlateComment(ba, String.format("COM signal 0x%04x dest buffer (%dB, %s). Front-sensor/ACC/ANB set.", sig,len,src));
    }
    public void run() throws Exception {
        mem=currentProgram.getMemory();
        java.util.Set<Long> seen=new java.util.HashSet<>();
        int n1=0,n2=0;
        // table 1: 0xb038c
        long o=0xb038cL;
        while (u32(o)==0x01000000L && u16(o+4)!=0 && o<0xb0800L){
            int sig=u16(o+4), len=u8(o+6); long buf=u32(o+8);
            labelBuf(buf,sig,len,"038c",seen); n1++; o+=0x10;
        }
        // table 2: 0xb06f0
        o=0xb06f0L;
        while (true){
            long buf=u32(o+4); int len=u8(o+2);
            if (!(buf>=0x403000L && buf<0x40b000L && len>=1 && len<=80)) break;
            int sig=u16(o), grp=u8(o+0xa);
            labelBuf(buf,sig,len,String.format("grp%02x",grp),seen); n2++; o+=0xc;
        }
        println("EspDecodeComSignals: table1="+n1+" table2="+n2+" distinct buffers labeled="+seen.size());
    }
}
