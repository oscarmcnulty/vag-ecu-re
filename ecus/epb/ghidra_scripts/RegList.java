import ghidra.app.script.GhidraScript; import ghidra.program.model.lang.Register;
public class RegList extends GhidraScript { public void run() throws Exception {
  for(Register r: currentProgram.getLanguage().getRegisters())
    println("  "+r.getName()+"  bits="+r.getBitLength()+(r.isProgramCounter()?" [PC]":"")+(r.getName().toUpperCase().contains("SP")?" [SP?]":""));
}}
