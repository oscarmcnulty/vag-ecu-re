import ghidra.app.script.GhidraScript;
import ghidra.program.model.lang.Register;
public class RegList extends GhidraScript {
  public void run() throws Exception {
    for (Register r: currentProgram.getLanguage().getRegisters()){
      String n=r.getName().toLowerCase();
      if(n.contains("cx")||n.contains("psw")||n.contains("pc")||n.equals("fcx")||n.contains("ctx"))
        println("REG "+r.getName()+"  bits="+r.getBitLength());
    }
  }
}
