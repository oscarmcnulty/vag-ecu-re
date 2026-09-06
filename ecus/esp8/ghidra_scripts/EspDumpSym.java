// Dump symbol name + plate comment at each address arg (hex). Verification helper.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.listing.CodeUnit;
public class EspDumpSym extends GhidraScript {
  public void run() throws Exception {
    for (String s: getScriptArgs()) {
      Address a=currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(Long.decode(s));
      Symbol sym=getSymbolAt(a);
      String cmt=null;
      try { cmt=currentProgram.getListing().getComment(CodeUnit.PLATE_COMMENT,a); } catch(Exception e){}
      println(String.format("%s : sym=%s src=%s | plate=%s", s,
        sym!=null?sym.getName():"(none)", sym!=null?sym.getSource():"-",
        cmt!=null?cmt.replaceAll("\\s+"," ").substring(0,Math.min(90,cmt.length())):"(none)"));
    }
  }
}
