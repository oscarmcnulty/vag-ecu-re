import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.ProgramContext;
import java.math.BigInteger;

public class SetV850Bases extends GhidraScript {
  public void run() throws Exception {
    ProgramContext ctx=currentProgram.getProgramContext();
    AddressSpace sp=currentProgram.getAddressFactory().getDefaultAddressSpace();
    Address lo=sp.getAddress(0x0), hi=sp.getAddress(0x85fff);
    set(ctx,"gp",0xFFFF0000L,lo,hi);
    set(ctx,"tp",0x0001A238L,lo,hi);
    // define reset entry so analysis flows from crt0
    Address reset=toAddr(0x259ca);
    if(getFunctionAt(reset)==null){ disassemble(reset); createFunction(reset,"crt0_start"); }
    addEntryPoint(reset);
    println("gp=0xFFFF0000 tp=0x0001A238 set over 0..0x85fff; entry crt0_start@0x259ca");
  }
  void set(ProgramContext ctx,String rn,long val,Address a,Address b) throws Exception {
    Register r=ctx.getRegister(rn);
    if(r==null){ println("no reg "+rn); return; }
    ctx.setValue(r,a,b,BigInteger.valueOf(val));
    println("set "+rn+" = "+Long.toHexString(val));
  }
}
