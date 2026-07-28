// Ghidra headless postScript: scan data ranges for 32-bit code pointers (into the
// PFLASH code segment), create a function at each undefined target, decompile to
// <outDir>/<addr>.c, and report. For recovering CAN-stack/ISR handlers that are only
// reachable via function-pointer tables (not direct calls).
//   analyzeHeadless <proj> <name> -process -postScript CodePtrSweep.java <outDir> <start1> <end1> [<start2> <end2> ...]
//@category VAG-RE
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.app.cmd.function.CreateFunctionCmd;
import ghidra.program.model.mem.MemoryAccessException;
import java.io.File;
import java.io.FileWriter;
import java.util.LinkedHashSet;
import java.util.Set;

public class CodePtrSweep extends GhidraScript {
    static final long CODE_LO = 0x80020000L, CODE_HI = 0x80200000L;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        String outDir = args[0];
        new File(outDir).mkdirs();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);

        Set<Long> targets = new LinkedHashSet<>();
        for (int i = 1; i + 1 < args.length; i += 2) {
            long s = parse(args[i]), e = parse(args[i + 1]);
            for (long a = s; a < e; a += 4) {
                try {
                    long v = Integer.toUnsignedLong(getInt(toAddr(a)));
                    if (v >= CODE_LO && v < CODE_HI && (v & 1) == 0) targets.add(v);
                } catch (MemoryAccessException ex) { /* skip */ }
            }
        }
        println("CodePtrSweep: " + targets.size() + " candidate code pointers");
        int created = 0, ok = 0;
        for (long v : targets) {
            Address ep = toAddr(v);
            Function fn = getFunctionAt(ep);
            if (fn == null) {
                disassemble(ep);
                new CreateFunctionCmd(ep).applyTo(currentProgram, monitor);
                fn = getFunctionAt(ep);
                if (fn != null) created++;
            }
            if (fn == null) continue;
            DecompileResults r = dec.decompileFunction(fn, 60, monitor);
            if (r != null && r.decompileCompleted() && r.getDecompiledFunction() != null) {
                try (FileWriter w = new FileWriter(new File(outDir, fn.getEntryPoint() + ".c"))) {
                    w.write(r.getDecompiledFunction().getC());
                }
                ok++;
            }
        }
        println("CodePtrSweep: created=" + created + " decompiled=" + ok + " out=" + outDir);
    }

    long parse(String s) { return Long.decode(s); }
}
