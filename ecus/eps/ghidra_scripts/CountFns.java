import ghidra.app.script.GhidraScript;
public class CountFns extends GhidraScript {
  public void run() throws Exception {
    int n = currentProgram.getFunctionManager().getFunctionCount();
    long instr = currentProgram.getListing().getNumInstructions();
    println("RESULT fns="+n+" instrs="+instr+" lang="+currentProgram.getLanguageID());
  }
}
