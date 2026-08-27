// Precise decompilation-coverage report over the code region.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.listing.*;
public class EspCoverage extends GhidraScript {
  public void run() throws Exception {
    long CODE_LO=0x0, CODE_HI=0xa2800;
    Listing lst=currentProgram.getListing();
    Memory mem=currentProgram.getMemory();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    long insnBytes=0, dataBytes=0, undef=0;
    // walk the code region byte-accurately via code units
    Address a=sp.getAddress(CODE_LO), end=sp.getAddress(CODE_HI-1);
    CodeUnitIterator it=lst.getCodeUnits(new AddressSet(a,end), true);
    long insnCount=0, dataCount=0;
    while(it.hasNext()){
      CodeUnit cu=it.next();
      int len=cu.getLength();
      if(cu instanceof Instruction){ insnBytes+=len; insnCount++; }
      else if(cu instanceof Data){
        Data d=(Data)cu;
        if(d.isDefined()){ dataBytes+=len; dataCount++; }
        else undef+=len;
      }
    }
    long total=CODE_HI-CODE_LO;
    // function stats
    int funcs=0; long fnBytes=0;
    FunctionIterator fi=currentProgram.getFunctionManager().getFunctions(sp.getAddress(CODE_LO),true);
    while(fi.hasNext()){ Function f=fi.next(); if(f.getEntryPoint().getOffset()>=CODE_HI) break; funcs++; fnBytes+=f.getBody().getNumAddresses(); }
    println(String.format("CODE region 0x%x-0x%x = %d bytes", CODE_LO, CODE_HI, total));
    println(String.format("  instructions: %d bytes (%.1f%%), %d insns", insnBytes, 100.0*insnBytes/total, insnCount));
    println(String.format("  defined data: %d bytes (%.1f%%), %d items", dataBytes, 100.0*dataBytes/total, dataCount));
    println(String.format("  UNDEFINED:    %d bytes (%.1f%%)  <- potential missed code/data", undef, 100.0*undef/total));
    println(String.format("  functions: %d, function-body bytes: %d (%.1f%%)", funcs, fnBytes, 100.0*fnBytes/total));
  }
}
