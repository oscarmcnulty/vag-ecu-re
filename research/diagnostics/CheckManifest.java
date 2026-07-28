// Report function_entries.txt entries that did NOT become a function (CreateFunctions failures),
// so the manifest can be kept pristine. Args: <manifest>
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import java.io.BufferedReader;
import java.io.FileReader;

public class CheckManifest extends GhidraScript {
  @Override public void run() throws Exception {
    String[] a=getScriptArgs();
    int miss=0, ok=0;
    try (BufferedReader br=new BufferedReader(new FileReader(a[0]))) {
      String line;
      while ((line=br.readLine())!=null) {
        line=line.trim();
        if (line.isEmpty()||line.startsWith("#")) continue;
        Address ep=currentProgram.getAddressFactory().getAddress(line);
        if (ep==null) { println("BAD-ADDR: "+line); miss++; continue; }
        if (getFunctionAt(ep)==null) {
          println(String.format("NO-FN: %s  (instr here: %s)", line,
            getInstructionAt(ep)!=null?getInstructionAt(ep).toString():"<none>"));
          miss++;
        } else ok++;
      }
    }
    println("CheckManifest: functions="+ok+" missing="+miss);
  }
}
