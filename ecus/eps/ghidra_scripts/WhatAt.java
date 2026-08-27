import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
public class WhatAt extends GhidraScript {
  public void run() throws Exception {
    for(String s: getScriptArgs()){
      Address a=toAddr(Long.decode(s));
      Function f=getFunctionContaining(a);
      Instruction in=getInstructionContaining(a);
      Data d=getDataContaining(a);
      String what = f!=null?("FUNC "+f.getName()+" @"+f.getEntryPoint()+" end="+f.getBody().getMaxAddress())
                   : in!=null?("INSTR "+in) : d!=null?("DATA "+d.getDataType()) : "UNDEFINED";
      println(s+" -> "+what);
    }
  }
}
