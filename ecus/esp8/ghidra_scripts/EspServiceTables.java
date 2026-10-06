// Recover KWP diagnostic service-handler functions that are reachable ONLY through the data-driven
// service dispatch tables, so Ghidra's auto-analysis never saw a code reference to them and left
// them UNDEFINED (DATA region) or mis-decoded as ARM. ESP8 (Bosch) stores two dispatch tables of
// 12-byte records:  { u8 SID, u8 flags, u16 x, u32 handlerPtr, u32 descriptorPtr }  (SID ascending).
// handlerPtr is a Thumb pointer (bit0=1) into CODE; descriptorPtr points into the 0xb8000..0xbf000
// descriptor cluster. This script scans for that record pattern, then disassembles + creates a
// function (ISA from the pointer's bit0) at every handler entry, clearing any conflicting ARM
// mis-decode / defined DATA first. These are the KWP service handlers (RDBI $22, RMBA $23,
// RoutineControl $31, the $27 SecurityAccess precondition gate, download/transfer $34-$37, ...).
//
// Run AFTER analysis and BEFORE EspCreateFns in reproduce.sh; EspExportFns (05c) then persists the
// recovered entries into function_entries.txt so they survive into the committed manifest.
//   analyzeHeadless <proj> <name> -process -postScript EspServiceTables.java [scanLo_hex scanHi_hex]
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.app.cmd.disassemble.ArmDisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.symbol.*;
import java.math.BigInteger;
import java.util.*;

public class EspServiceTables extends GhidraScript {
    long IMG_HI = 0x134010L, DESC_LO = 0xb0000L, DESC_HI = 0xbf000L;
    // CODE_HI: the main code region ends here; the 0xa2000..0xbb045 band is calibration/DATA. A
    // record's handlerPtr that lands >= CODE_HI is NOT a code entry but a pointer to the service's
    // cal descriptor (the service is dispatched by the generic data-driven engine via descriptorPtr).
    // Creating a function there mis-decodes calibration bytes into garbage (see docs/KWP_SERVICES.md
    // "handlerPtr is dual-natured"). Only carve functions for NATIVE handlers (handlerPtr < CODE_HI).
    long CODE_HI = 0xa2000L;
    Memory mem; AddressSpace sp; Listing lst; Register tmode;

    boolean isCodePtr(long v){ long b=v&~1L; return b>=0x1000L && b<IMG_HI; }
    boolean isDescPtr(long v){ long b=v&~1L; return b>=DESC_LO && b<DESC_HI; }
    boolean validSid(int s){ return (s>=0x10 && s<=0x3f) || (s>=0x80 && s<=0x8f); }
    int u8(long a) throws Exception { return mem.getByte(sp.getAddress(a)) & 0xff; }
    long u32(long a) throws Exception { return ((long)mem.getInt(sp.getAddress(a))) & 0xffffffffL; }
    boolean thumbAt(Address a){ if(tmode==null) return false;
        BigInteger v=currentProgram.getProgramContext().getValue(tmode,a,false); return v!=null && v.intValue()==1; }
    void setTMode(Address a, boolean t){ if(tmode==null) return;
        try { currentProgram.getProgramContext().setValue(tmode,a,a,t?BigInteger.ONE:BigInteger.ZERO); } catch(Exception e){} }

    int u16(long a) throws Exception { return mem.getShort(sp.getAddress(a)) & 0xffff; }

    // The table pointer may be a +N alternate entry into a function. If the pointer already lands on a
    // function-start construct (Thumb push {..,lr}=B5xx, a 32-bit branch/BL=F000-mask trampoline, or an
    // ARM STMDB{..,lr}), use it directly. Otherwise it is mid-function -> scan back a short window for the
    // real prologue (Thumb B5xx / ARM e92d....&0x4000). Fall back to the pointer itself.
    long prologueStart(long ptr, boolean thumb) throws Exception {
        long site=ptr&~1L;
        if (thumb){
            int hw0=u16(site);
            if ((hw0&0xff00)==0xb500) return site;      // push {..,lr}  -> real start
            if ((hw0&0xf800)==0xf000) return site;      // 32-bit B.W / BL -> trampoline entry
            for (long a=site-2; a>site-0x60 && a>=0x1000; a-=2)
                if ((u16(a)&0xff00)==0xb500) return a;   // alt-entry -> back up to the push
        } else {
            if ((site&3)==0){ long w=u32(site); if ((w>>>16)==0xe92dL && (w&0x4000)!=0) return site; }
            for (long a=site&~3L; a>site-0x60 && a>=0x1000; a-=4)
                if ((u32(a)>>>16)==0xe92dL && (u32(a)&0x4000)!=0) return a;
        }
        return site;
    }

    // one record is valid if SID ok, flags!=0, handlerPtr is code, descriptorPtr is in the desc cluster
    boolean validRec(long o) throws Exception {
        if (!validSid(u8(o))) return false;
        if (u8(o+1)==0) return false;
        if (!isCodePtr(u32(o+4))) return false;
        if (!isDescPtr(u32(o+8))) return false;
        return true;
    }

    public void run() throws Exception {
        mem=currentProgram.getMemory(); sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
        lst=currentProgram.getListing(); tmode=currentProgram.getLanguage().getRegister("TMode");
        long scanLo=0xa2000L, scanHi=0xbb045L;
        if (getScriptArgs().length>=2){ scanLo=Long.decode(getScriptArgs()[0]); scanHi=Long.decode(getScriptArgs()[1]); }

        // --- locate tables: runs of >=4 valid 12-byte records ---
        List<long[]> tables=new ArrayList<>();      // {start, count}
        long i=scanLo;
        while (i<scanHi-12){
            if (validRec(i)){
                long j=i; int n=0;
                while (j<scanHi-12 && validRec(j)){ n++; j+=12; }
                if (n>=4){ tables.add(new long[]{i,n}); i=j; continue; }
            }
            i++;
        }
        println("EspServiceTables: found "+tables.size()+" dispatch table(s) in ["
                +Long.toHexString(scanLo)+","+Long.toHexString(scanHi)+")");

        // --- collect distinct handler pointers AND descriptor pointers ---
        LinkedHashMap<Long,Integer> handlers=new LinkedHashMap<>();   // ptr(with bit0) -> SID
        LinkedHashMap<Long,Integer> descriptors=new LinkedHashMap<>(); // descriptorPtr -> SID
        for (long[] t: tables){
            long base=t[0]; int cnt=(int)t[1];
            StringBuilder sb=new StringBuilder();
            for (int k=0;k<cnt;k++){
                long o=base+12L*k; int sid=u8(o); long pa=u32(o+4); long dp=u32(o+8);
                if (!handlers.containsKey(pa)) handlers.put(pa,sid);
                if (!descriptors.containsKey(dp)) descriptors.put(dp,sid);
                sb.append(String.format("%02x ",sid));
            }
            println(String.format("  table @0x%06x  %d recs  SIDs: %s", base, cnt, sb.toString().trim()));
        }

        // --- create a function at each handler entry (correct ISA, conflicts cleared) ---
        int madeNew=0, haveEntry=0, skipContained=0, refixed=0, failed=0, dataSkipped=0;
        for (Map.Entry<Long,Integer> e: handlers.entrySet()){
            long pa=e.getKey(); int sid=e.getValue();
            boolean thumb=(pa&1)!=0;
            // DATA/cal handlerPtr (>= CODE_HI): not a function. Label it and move on so we never
            // mis-decode calibration bytes into a phantom Thumb handler.
            if ((pa&~1L) >= CODE_HI){
                try { createLabel(sp.getAddress(pa&~1L),
                        "kwp_sid"+Integer.toHexString(sid)+"_cal_"+Long.toHexString(pa&~1L),
                        true, SourceType.ANALYSIS); } catch(Exception ex){}
                dataSkipped++; continue;
            }
            Address t=sp.getAddress(prologueStart(pa, thumb));
            if (getFunctionAt(t)!=null){ haveEntry++; continue; }
            Function cont=getFunctionContaining(t);
            if (cont!=null){
                if (thumbAt(cont.getEntryPoint())==thumb){ skipContained++; continue; } // alt-entry, same ISA -> covered
                // wrong-ISA mis-decode swallowing a Thumb handler: drop the bad function + its code
                AddressSetView body=cont.getBody();
                removeFunctionAt(cont.getEntryPoint());
                clearListing(body.getMinAddress(), body.getMaxAddress());
                refixed++;
            }
            CodeUnit cu=lst.getCodeUnitContaining(t);
            if (cu!=null) clearListing(cu.getMinAddress(), cu.getMaxAddress());
            setTMode(t, thumb);
            new ArmDisassembleCommand(t, null, thumb).applyTo(currentProgram, monitor);
            boolean ok=(getFunctionAt(t)!=null) || new CreateFunctionCmd(t).applyTo(currentProgram, monitor);
            if (ok && getFunctionAt(t)!=null){
                madeNew++;
                try { getFunctionAt(t).setComment("KWP service handler (SID 0x"+Integer.toHexString(sid)
                        +"); recovered from dispatch table by EspServiceTables"); } catch(Exception ex){}
            } else failed++;
        }
        println("EspServiceTables: handlers="+handlers.size()+" created="+madeNew+" already_entry="+haveEntry
                +" alt_entry_skipped="+skipContained+" wrongISA_refixed="+refixed+" failed="+failed
                +" data_cal_skipped="+dataSkipped);

        // --- create functions at descriptorPtr entries (SEG2 per-service validation stubs) ---
        int descNew=0, descExist=0, descContained=0, descFailed=0;
        for (Map.Entry<Long,Integer> e: descriptors.entrySet()){
            long dp=e.getKey(); int sid=e.getValue();
            boolean thumb=(dp&1)!=0;
            long site=dp&~1L;
            if (site<DESC_LO || site>=DESC_HI) continue;
            Address t=sp.getAddress(site);
            if (getFunctionAt(t)!=null){ descExist++; continue; }
            Function cont=getFunctionContaining(t);
            if (cont!=null){ descContained++; continue; }
            CodeUnit cu=lst.getCodeUnitContaining(t);
            if (cu!=null) clearListing(cu.getMinAddress(), cu.getMaxAddress());
            setTMode(t, thumb);
            new ArmDisassembleCommand(t, null, thumb).applyTo(currentProgram, monitor);
            boolean ok=(getFunctionAt(t)!=null) || new CreateFunctionCmd(t).applyTo(currentProgram, monitor);
            if (ok && getFunctionAt(t)!=null){
                descNew++;
                try { getFunctionAt(t).setComment("KWP service descriptor stub (SID 0x"+Integer.toHexString(sid)
                        +"); recovered from dispatch table descriptorPtr by EspServiceTables"); } catch(Exception ex){}
            } else descFailed++;
        }
        println("EspServiceTables: descriptors="+descriptors.size()+" desc_created="+descNew
                +" desc_exist="+descExist+" desc_contained="+descContained+" desc_failed="+descFailed);
    }
}
