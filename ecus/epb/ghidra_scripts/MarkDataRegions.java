// Clear any code/functions in the given [lo,hi) ranges and mark them as data (byte array), so
// misdisassembled data tables stop inflating the function set. Ranges are DATA (CAN matrix / config
// tables / pointer tables) identified by structure+zero-density. Args: lo:hi lo:hi ...
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.ByteDataType;
public class MarkDataRegions extends GhidraScript {
  public void run() throws Exception {
    Listing lis=currentProgram.getListing(); int cleared=0;
    for(String s:getScriptArgs()){
      String[] p=s.split(":"); long lo=Long.decode(p[0]), hi=Long.decode(p[1]);
      Address a=toAddr(lo), e=toAddr(hi-1);
      // remove functions whose entry is in range
      FunctionManager fm=currentProgram.getFunctionManager();
      FunctionIterator it=fm.getFunctions(a,true);
      java.util.List<Address> del=new java.util.ArrayList<>();
      while(it.hasNext()){ Function f=it.next(); if(f.getEntryPoint().getOffset()>=hi) break; del.add(f.getEntryPoint()); }
      for(Address d:del) removeFunctionAt(d);
      clearListing(a,e);
      // create byte array over the range
      lis.createData(a, new ghidra.program.model.data.ArrayDataType(ByteDataType.dataType,(int)(hi-lo),1));
      cleared++;
      println(String.format("MarkDataRegions: [%x,%x) cleared %d fns + marked bytes", lo,hi,del.size()));
    }
    println("MarkDataRegions: done "+cleared+" ranges");
  }
}
