// Ghidra headless: find where an address REGISTER holds a value pointing into a
// target cal window -- catches runtime-INDEXED array bases (e.g. the decel-limit
// table @0x8004dd90) that ResolveCalReads misses because the ld/st operand's base
// register is formed by addsc.a/add.a with a variable index, so the effective
// address never resolves to a constant.
//
// Two independent detectors, per function, after SymbolicPropogator (a0/a1/a8 seeded):
//  (1) REG: for every instruction, every address register a0..a15 whose *resolved*
//      value is a constant inside [WLO,WHI) is emitted -- this is the base pointer
//      into the table's neighborhood, regardless of how it is later consumed.
//  (2) IMM: any instruction carrying a scalar immediate equal to one of the table's
//      signature constants (low16 0xdd90/a0/b0/a6/b6, a1-offset 0x5d90.., full
//      0x8004dd9x, stride 0x10) -- catches movh/lea/addi/mov materialization even
//      when propagation cannot fold it.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript ScanCalIndexed.java [out.csv] [0xWLO 0xWHI] [funcAddr..]
// Defaults: WLO=0x8004c000 WHI=0x8004ea00. Extra 0x-args beyond the first two window
// bounds restrict to those functions. Output CSV: function,insaddr,kind,reg,value,mnemonic
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.util.SymbolicPropogator;
import ghidra.program.util.ContextEvaluatorAdapter;
import java.io.PrintWriter;
import java.io.FileWriter;

public class ScanCalIndexed extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outPath = null;
        java.util.List<Long> nums = new java.util.ArrayList<>();
        java.util.List<String> hexArgs = new java.util.ArrayList<>();
        for (String a : args) {
            if (a.startsWith("0x")) hexArgs.add(a);
            else if (outPath == null) outPath = a;
        }
        long WLO = 0x8004c000L, WHI = 0x8004ea00L;
        java.util.List<String> funcAddrs = new java.util.ArrayList<>();
        if (hexArgs.size() >= 2) { WLO = Long.parseLong(hexArgs.get(0).substring(2),16);
                                   WHI = Long.parseLong(hexArgs.get(1).substring(2),16);
                                   for (int i=2;i<hexArgs.size();i++) funcAddrs.add(hexArgs.get(i)); }
        else for (String h: hexArgs) funcAddrs.add(h);

        // signature immediates of the decel table (both a1-relative low16 and absolute low16)
        java.util.Set<Long> IMMS = new java.util.HashSet<>(java.util.Arrays.asList(
            0x5d90L,0x5da0L,0x5db0L,0x5da6L,0x5db6L,          // a1-relative offsets (a1=0x80048000)
            0xdd90L,0xdda0L,0xddb0L,0xdda6L,0xddb6L,          // absolute low16
            0x4dd90L,0x4dda0L,0x4ddb0L,0x8004dd90L,0x8004dda0L,0x8004ddb0L));

        java.util.List<Function> funcs = new java.util.ArrayList<>();
        if (!funcAddrs.isEmpty()) {
            for (String a : funcAddrs) { Function f = getFunctionAt(
                currentProgram.getAddressFactory().getAddress(a)); if (f!=null) funcs.add(f); }
        } else {
            FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
            while (it.hasNext()) funcs.add(it.next());
        }

        PrintWriter out = (outPath!=null)? new PrintWriter(new FileWriter(outPath))
                                         : new PrintWriter(System.out);
        out.println("function,insaddr,kind,reg,value,mnemonic");
        Register[] aregs = new Register[16];
        for (int i=0;i<16;i++) aregs[i]=currentProgram.getRegister("a"+i);
        int emitted=0;

        for (Function f : funcs) {
            if (monitor.isCancelled()) break;
            SymbolicPropogator sp = new SymbolicPropogator(currentProgram);
            Address entry = f.getEntryPoint();
            sp.flowConstants(entry, f.getBody(), new ContextEvaluatorAdapter(), false, monitor);
            String fname = f.getName()+"@"+entry;
            Instruction ins = getInstructionAt(entry);
            // dedup identical (reg,value) reported consecutively within a function
            java.util.Set<String> seenReg = new java.util.HashSet<>();
            while (ins != null && f.getBody().contains(ins.getAddress())) {
                String mn = ins.getMnemonicString().toLowerCase();
                // (1) REG detector: any address register holding a constant in-window
                for (int i=0;i<16;i++) {
                    if (aregs[i]==null) continue;
                    SymbolicPropogator.Value v = sp.getRegisterValue(ins.getAddress(), aregs[i]);
                    if (v==null || v.isRegisterRelativeValue()) continue;
                    long val = v.getValue() & 0xffffffffL;
                    if (val>=WLO && val<WHI) {
                        String key = "a"+i+"="+val;
                        if (seenReg.add(key)) {
                            out.println(String.format("%s,%s,REG,a%d,0x%08x,%s",
                                fname, ins.getAddress(), i, val, mn));
                            emitted++;
                        }
                    }
                }
                // (2) IMM detector: signature immediate anywhere in the instruction
                for (int op=0; op<ins.getNumOperands(); op++) {
                    for (Object o : ins.getOpObjects(op)) {
                        if (o instanceof Scalar) {
                            long s = ((Scalar)o).getUnsignedValue() & 0xffffffffL;
                            if (IMMS.contains(s)) {
                                out.println(String.format("%s,%s,IMM,-,0x%08x,%s",
                                    fname, ins.getAddress(), s, mn));
                                emitted++;
                            }
                        }
                    }
                }
                ins = ins.getNext();
            }
        }
        out.flush();
        if (outPath!=null) out.close();
        println("SCANDONE: emitted "+emitted+" rows -> "+(outPath!=null?outPath:"stdout"));
    }
}
