// Ghidra headless: resolve the calibration-map addresses passed to the map-lookup framework
// (interpolators + axis-search helpers). With a1 (cal base) set, the map data pointer and axis
// arrays reach each call as constant inputs -- but many are built as `cal_struct_ptr + offset`
// or through CAST/COPY/ADD, which a bare `isConstant()` check misses. This pass follows the
// decompiler pcode of every argument back through COPY/CAST/INT_ADD/PTRADD/LOAD (reading a
// pointer value straight from program memory and normalizing the 0xa0/0xb0 cached-alias to
// 0x80) so both inline-immediate AND pointer-table (Path-C) map reads resolve. That lifts
// coverage from the ~17 pure-constant hits of the old scan to ~4k across the full cal region.
//
//   analyzeHeadless <proj> <name> -process <bin> -noanalysis \
//       -scriptPath core/ghidra -postScript TraceMapCalls.java <outCsv>
// CSV columns: caller_addr,caller_name,callee,arg_idx,cal_addr,how
//   how = "const" (address built inline) | "*[0xPTR]=0xBASE ..." (resolved via a pointer load)
//@category VAG-RE
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.pcode.HighFunction;
import ghidra.program.model.pcode.PcodeOp;
import ghidra.program.model.pcode.PcodeOpAST;
import ghidra.program.model.pcode.Varnode;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import java.io.FileWriter;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.Set;

public class TraceMapCalls extends GhidraScript {
    // the map-access framework entry points (interpolators + axis-search + leaf wrappers).
    // Args that resolve into the cal range = map data ptr / axis arrays.
    static final String[] TARGETS = {
        "800a5fc0","800a5f40","800a5d40","800a5b80","800a5b00",           // kf/kl interp + axis
        "800a2d4c","800a2cd0","800a2dac","800a2e0c","800a2ddc",           // leaf wrappers
        "800a2c98","800a2e3c","800a2c7c","800a2f34","800a2bd0","800a2c48",// ecu/sensor/descriptor
        "801f0cd4","801f0d0c","801f0f88","801f0914"                       // Path-B curve helpers
    };
    static final long LO = 0x80040000L, HI = 0x80080000L;   // full cal region (both a1 sides)

    private long norm(long v) {              // 0xa0/0xb0 cached-alias -> 0x80 flash form
        long top = v >>> 28;
        return (top == 0xA || top == 0xB) ? ((v & 0x8FFFFFFFL) | 0x80000000L) : v;
    }

    // Resolve a varnode to a numeric value, following COPY/CAST/ADD and LOAD(const_ptr).
    // `how` accumulates a human-readable derivation. Returns null if not statically resolvable.
    private Long resolve(Varnode v, int depth, StringBuilder how) {
        if (v == null || depth > 16) return null;
        if (v.isConstant()) return v.getOffset() & 0xFFFFFFFFL;
        PcodeOp def = v.getDef();
        if (def == null) {
            if (v.isAddress()) return v.getAddress().getOffset() & 0xFFFFFFFFL;
            return null;
        }
        switch (def.getOpcode()) {
            case PcodeOp.COPY: case PcodeOp.CAST:
            case PcodeOp.INT_ZEXT: case PcodeOp.INT_SEXT:
            case PcodeOp.INT_2COMP: case PcodeOp.SUBPIECE:
                return resolve(def.getInput(0), depth + 1, how);
            case PcodeOp.INT_ADD: case PcodeOp.PTRSUB: {
                Long a = resolve(def.getInput(0), depth + 1, how);
                Long b = resolve(def.getInput(1), depth + 1, how);
                if (a == null || b == null) return null;
                return (a + b) & 0xFFFFFFFFL;
            }
            case PcodeOp.PTRADD: {   // base + index*size
                Long a = resolve(def.getInput(0), depth + 1, how);
                Long b = resolve(def.getInput(1), depth + 1, how);
                Long s = resolve(def.getInput(2), depth + 1, how);
                if (a == null || b == null || s == null) return null;
                return (a + b * s) & 0xFFFFFFFFL;
            }
            case PcodeOp.LOAD: {      // value = *(addr); addr must resolve to a constant location
                Long addr = resolve(def.getInput(1), depth + 1, how);
                if (addr == null) return null;
                try {
                    long val = ((long) currentProgram.getMemory()
                            .getInt(toAddr(addr & 0xFFFFFFFFL))) & 0xFFFFFFFFL;
                    long nv = norm(val);
                    how.append("*[0x").append(Long.toHexString(addr)).append("]=0x")
                       .append(Long.toHexString(nv)).append(" ");
                    return nv;
                } catch (Exception e) { return null; }
            }
            case PcodeOp.MULTIEQUAL:
                for (int i = 0; i < def.getNumInputs(); i++) {
                    Long r = resolve(def.getInput(i), depth + 1, how);
                    if (r != null) return r;
                }
                return null;
            default:
                return null;
        }
    }

    @Override
    public void run() throws Exception {
        String out = getScriptArgs().length > 0 ? getScriptArgs()[0] : "map_calls.csv";
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        ReferenceManager rm = currentProgram.getReferenceManager();
        int rows = 0, resolvedPtr = 0;

        Set<Function> callers = new LinkedHashSet<>();
        for (String t : TARGETS) {
            Address ta = toAddr(Long.parseLong(t, 16));
            for (Reference r : rm.getReferencesTo(ta)) {
                if (!r.getReferenceType().isCall()) continue;
                Function f = getFunctionContaining(r.getFromAddress());
                if (f != null) callers.add(f);
            }
        }
        println("TraceMapCalls: decompiling " + callers.size() + " caller functions ...");

        try (FileWriter w = new FileWriter(out)) {
            w.write("caller_addr,caller_name,callee,arg_idx,cal_addr,how\n");
            for (Function f : callers) {
                if (monitor.isCancelled()) break;
                DecompileResults dr = dec.decompileFunction(f, 60, monitor);
                HighFunction hf = dr != null ? dr.getHighFunction() : null;
                if (hf == null) continue;
                Iterator<PcodeOpAST> ops = hf.getPcodeOps();
                while (ops.hasNext()) {
                    PcodeOpAST op = ops.next();
                    if (op.getOpcode() != PcodeOp.CALL) continue;
                    Varnode target = op.getInput(0);
                    if (!target.isAddress()) continue;
                    String callee = target.getAddress().toString();
                    boolean isTarget = false;
                    for (String t : TARGETS) if (callee.endsWith(t)) { isTarget = true; break; }
                    if (!isTarget) continue;
                    Function tf = getFunctionAt(target.getAddress());
                    String cn = tf != null ? tf.getName() : callee;
                    for (int i = 1; i < op.getNumInputs(); i++) {
                        StringBuilder how = new StringBuilder();
                        Long rv = resolve(op.getInput(i), 0, how);
                        if (rv == null) continue;
                        long v = norm(rv);
                        if (LO <= v && v < HI) {
                            boolean viaPtr = how.length() > 0;
                            w.write(String.format("%s,%s,%s,%d,0x%08x,%s\n",
                                f.getEntryPoint(), f.getName(), cn, i, v,
                                viaPtr ? how.toString().trim() : "const"));
                            rows++;
                            if (viaPtr) resolvedPtr++;
                        }
                    }
                }
            }
        }
        println("TraceMapCalls: " + rows + " cal-map args (" + resolvedPtr
                + " via pointer+offset) -> " + out);
    }
}
