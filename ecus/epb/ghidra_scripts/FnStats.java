import ghidra.app.script.GhidraScript; import ghidra.program.model.listing.*;
public class FnStats extends GhidraScript { public void run() throws Exception {
  FunctionManager fm=currentProgram.getFunctionManager(); int tiny=0,sm=0,med=0,big=0,tot=0; long body=0;
  for(Function f: fm.getFunctions(true)){ long sz=f.getBody().getNumAddresses(); tot++; body+=sz;
    if(sz<=6) tiny++; else if(sz<32) sm++; else if(sz<128) med++; else big++; }
  println(String.format("functions=%d bodyBytes=%d  <=6B:%d  7-31B:%d  32-127B:%d  >=128B:%d", tot,body,tiny,sm,med,big));
}}
