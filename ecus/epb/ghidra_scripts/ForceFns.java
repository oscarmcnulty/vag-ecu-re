// Force-create functions at every FUNCTION entry in symbols.csv, even computed-call/jump targets
// that auto-analysis left unfunctionized. Clears any conflicting instruction, disassembles fresh,
// creates the function. Run BEFORE ApplySymbols so names/comments always land on a real function.
//   -postScript ForceFns.java <symbols.csv>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import java.io.*; import java.nio.file.*;
public class ForceFns extends GhidraScript { public void run() throws Exception {
  int made=0, had=0, fail=0;
  for(String raw: Files.readAllLines(Paths.get(getScriptArgs()[0]))){
    String[] f=raw.split(",");
    if(f.length<3 || !f[2].trim().equals("FUNCTION")) continue;
    Address a; try{ a=toAddr(Long.decode(f[0].trim())); }catch(Exception e){ continue; }
    if(getFunctionAt(a)!=null){ had++; continue; }
    if(getInstructionAt(a)==null){ new DisassembleCommand(a,null,false).applyTo(currentProgram,monitor); }
    Function fn = createFunction(a,null);
    if(fn!=null) made++; else fail++;
  }
  println("ForceFns: created "+made+" (existing "+had+", failed "+fail+")");
}}
