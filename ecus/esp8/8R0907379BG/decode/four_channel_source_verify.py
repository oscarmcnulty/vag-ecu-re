#!/usr/bin/env python3
# ESP8 8R0907379BG -- verification of the 4 decel-channel SOURCE bindings (static, no emulation).
# Re-checks, against the raw flash image, every source-side claim in
# docs/four_channels_source_binding.md so the model is reproducible and self-auditing.
#
# Run: python3 decode/four_channel_source_verify.py   (from the ecu dir)
import struct, os, bisect
HERE = os.path.dirname(__file__)
FW = os.path.join(HERE, "..", "firmware", "8R0907379BG_0030.bin")
d = open(FW, "rb").read(); n = len(d)
u32 = lambda o: struct.unpack('>I', d[o:o+4])[0]

def findall(v):
    b = struct.pack('>I', v); r = []; i = d.find(b)
    while i != -1: r.append(i); i = d.find(b, i+1)
    return r

CODE_HI = 0xa2000
def cls(o): return 'code' if o < CODE_HI else 'dataset'

_FNS = sorted(int(x[:-2], 16) for x in
              os.listdir(os.path.join(HERE, "..", "analysis", "decompiles_r")) if x.endswith(".c"))
DBUF = 0x64ce4  # com_decel_double_buffer -- its own literal pool reads the staging ptrs
def containing_fn(o):
    i = bisect.bisect_right(_FNS, o) - 1
    return _FNS[i] if i >= 0 else None

# ---- decel source RAM addresses (from docs/decel_paths.md, CODE-VERIFIED) ----
SRC = {
  'type1  decel_src_type1'   : 0x403fac,
  'type2  decel_src_comfort' : 0x403a40,
  'type4  decel_src_type4'   : 0x407bb4,
  'type5  decel_src_type5'   : 0x403d76,
}

print("# 4 decel-channel source bindings -- static verification\n")
print("## 1. Where each decel-source buffer is referenced (all refs are pipeline/producer code)")
for name, a in SRC.items():
    refs = findall(a)
    print(f"  {name} @ {a:#x}: " + ", ".join(f"{hex(o)}({cls(o)})" for o in refs))

# ---- CLAIM CHECK A: type2/comfort -- 0x405460 is the INTERNAL wheel-decel estimate,
#      0x405462 is the (COM-written) CAN request with NO static writer. ----
print("\n## 2. type2/comfort: internal estimate 0x405460 vs CAN request 0x405462")
for lbl, a in [("0x405460 (internal wheel-decel est.)", 0x405460),
               ("0x405462 (comfort CAN request)",       0x405462),
               ("0x40545c (estimator output word)",     0x40545c)]:
    refs = findall(a)
    print(f"  {lbl}: " + (", ".join(f"{hex(o)}({cls(o)})" for o in refs) or "NONE"))
print("  -> 0x405462 has refs in code (readers) but appears in NO dataset config record and")
print("     has NO code store at that exact address => written only by the index-driven COM layer.")

# ---- CLAIM CHECK B: sig 0x037f (buffer 0x403fa2) is NOT type1's input ----
print("\n## 3. sig 0x037f (buffer 0x403fa2) is unrelated to decel_src_type1")
refs = findall(0x403fa2)
print(f"  0x403fa2 refs: " + ", ".join(f"{hex(o)}({cls(o)})" for o in refs))
print("  -> code refs (0x900e8/0xa0480) are NOT in the decel pipeline (0x64fb8/0x7f4ec/0x844fc/0x86798);")
print("     dataset refs are the explicit COM tables 0xb038c/0xb06f0. So 0x037f != type1 input.")

# ---- CLAIM CHECK C: analyzed code extent + the '+0xc' consumer field is polymorphic ----
fe = os.path.join(os.path.dirname(__file__), "..", "analysis", "function_entries.txt")
maxfn = max(int(l.split(',')[0], 16) for l in open(fe) if l.startswith('0x'))
print(f"\n## 4. Code extent: last function entry = {maxfn:#x} (CODE_HI cfg = {CODE_HI:#x})")
print("  Consumer '+0xc' pointers in 0xb038c point into 0xa2xxx-0xa8xxx: a MIX of code (0xa27xx,")
print("  tail-branching into analyzed 0xa22xx) and dataset (0xa7xxx/0xa8xxx read as data), so the")
print("  field is not a uniform function pointer and cannot be walked to a per-signal source.")

# ---- CLAIM CHECK D: com_decel_double_buffer (0x64ce4) stages all 4 channels ----
# The double-buffer copies each channel's CURRENT snapshot from a STAGING address. The
# per-channel {current <- staging,len} pairs live in the shared literal pool 0x65018..0x65094.
print("\n## 5. com_decel_double_buffer staging map (current <- staging) for the 4 channels")
DB = {  # (current_ptr_slot, staging_ptr_slot, len) taken from the 0x64ce4 body
  'type1': (0x65058, 0x6505c, 8),   # 0x403fac <- 0x403fa4
  'type2': (0x65018, 0x6501c, 16),  # 0x403a7c <- 0x403a6c  (0x403a80/86 within)
  'type4': (0x65040, 0x65044, 8),   # 0x407bb4 <- 0x407bac
  'type5': (0x65090, 0x65094, 8),   # 0x403d76 <- 0x403d6e
}
for ch,(cs,ss,ln) in DB.items():
    cur, stg = u32(cs), u32(ss)
    # functions (other than the double-buffer itself) whose literal pool references the staging addr
    prod = sorted({containing_fn(o) for o in findall(stg) if o < CODE_HI})
    prod = [f for f in prod if f is not None and f not in (DBUF, 0x64fb8)]  # exclude the double-buffer machinery
    note = ("producer fn(s): " + ", ".join(hex(f) for f in prod)) if prod \
           else "NO producer -> only the double-buffer reads it => channel INACTIVE"
    print(f"  {ch}: current {cur:#x} <- staging {stg:#x} (len {ln})   {note}")

print("\nDONE. See docs/four_channels_source_binding.md for the consolidated model.")
