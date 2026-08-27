import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.lang.Register;
import java.util.*;

public class FindV850Bases extends GhidraScript {
  public void run() throws Exception {
    Listing lst=currentProgram.getListing();
    Set<String> want=new HashSet<>(Arrays.asList("gp","tp","ep","r4","r5","r30"));
    InstructionIterator it=lst.getInstructions(true);
    int shown=0;
    for(Instruction ins: iterable(it)){
      for(Object o: ins.getResultObjects()){
        if(o instanceof Register){
          String rn=((Register)o).getName();
          if(want.contains(rn)){
            println(String.format("%08x  %-6s -> %s", ins.getAddress().getOffset(),
              ins.getMnemonicString(), ins.toString()));
            shown++;
          }
        }
      }
      if(shown>120) break;
    }
    println("total writes to gp/tp/ep shown="+shown);
  }
  Iterable<Instruction> iterable(InstructionIterator it){ return ()-> new Iterator<Instruction>(){
    public boolean hasNext(){return it.hasNext();} public Instruction next(){return it.next();}};}
}
