import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;

// Iterate ALL defined instructions; print any ldsr/stsr (system reg moves) and any callt.
public class FindCTBP extends GhidraScript {
  public void run() throws Exception {
    Listing lis = currentProgram.getListing();
    InstructionIterator it = lis.getInstructions(true);
    int ldsr = 0, callt = 0;
    while (it.hasNext()) {
      Instruction ins = it.next();
      String m = ins.getMnemonicString().toLowerCase();
      if (m.equals("ldsr") || m.equals("stsr")) {
        println(String.format("SR %08x: %s", ins.getAddress().getOffset(), ins.toString()));
        ldsr++;
      } else if (m.equals("callt")) {
        Function f = getFunctionContaining(ins.getAddress());
        println(String.format("CALLT %08x: %s   in %s", ins.getAddress().getOffset(), ins.toString(), f==null?"?":f.getName()));
        callt++;
      }
    }
    println("total ldsr/stsr=" + ldsr + " callt=" + callt);
  }
}
