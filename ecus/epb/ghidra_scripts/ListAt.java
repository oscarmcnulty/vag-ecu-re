import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
public class ListAt extends GhidraScript { public void run() throws Exception {
  long s=Long.decode(getScriptArgs()[0]); int n=Integer.decode(getScriptArgs()[1]);
  Address a=toAddr(s);
  for(int i=0;i<n;i++){ Instruction ins=getInstructionAt(a); if(ins==null){println(String.format("%06x  <no-insn> byte=%02x",a.getOffset(),getByte(a)&0xff)); a=a.add(1);} else {println(String.format("%06x  %s",a.getOffset(),ins.toString())); a=a.add(ins.getLength());} }
}}
