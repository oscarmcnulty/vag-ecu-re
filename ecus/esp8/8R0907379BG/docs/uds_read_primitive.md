# ESP8 8R0907379BG — UDS memory-read primitive (SBOOT-leak recon)

Goal: can we leak SBOOT over CAN via a UDS memory-read service, avoiding a die-level dump?
Status: **read primitive located and confirmed to exist + be security-gated; its bounds check
is in the degraded seg2 region and is the next thing to decompile.**

## Service dispatch table @ 0xb4d80

12-byte records: `SID(1) | flags(1) | 0x0000 | mainseg_ptr(4) | seg2/RAM_ptr(4)`.

| SID | service | flags | notes |
|----:|---------|:-----:|-------|
| 0x10 | DiagnosticSessionControl | 0xa4 | |
| 0x1a | ReadEcuIdentification (KWP) | 0xb0 | |
| **0x23** | **ReadMemoryByAddress** | **0xa0** | **the read primitive** |
| 0x30 | InputOutputControl (KWP) | 0x20 | |
| 0x31 | RoutineControl | 0x34 | |
| 0x34 | RequestDownload | 0x30 | flash |
| 0x36 | TransferData | 0x30 | flash |
| 0x37 | RequestTransferExit | 0x30 | flash |
| **0x3d** | **WriteMemoryByAddress** | **0xa0** | shares mainseg_ptr with 0x23 |
| 0x3e | TesterPresent | 0xb0 | |
| 0x81/0x82 | start/stop comms | 0x80/0xa4 | |
| 0x83 | AccessTimingParameter | 0x30 | |

DID-based services 0x22/0x2e use a separate table `diag_did_table @0xb44e4`.

## Key facts

- **0x23 ReadMemoryByAddress exists** and is gated by `flags=0xa0`. The 0x80 bit = security
  required; so a read needs SecurityAccess — the **SA2 level we already cracked** (memory
  [[abs-sa2-key]]) is the candidate. Confirm the exact level next.
- The `mainseg_ptr` column points to **session/state wrappers + a shared response finalizer**
  (0x987f4, shared by 0x23 and 0x3d), NOT the address-parsing executor. Verified by capstone
  (BE-Thumb) and Ghidra: 0x987f4 only OR-packs a status byte; FUN_0009a900 (0x34 area) only
  manages the download session state and emits NRC 0x0c via FUN_0004f730.
- **The real executors — the code that parses `addressAndLengthFormatIdentifier`, reads memory,
  and bounds-checks the address — live in seg2** (the AUTOSAR Dcm diag stack, file >0xbb045,
  VMA=fileoff+3). Ghidra has no callers for 0x987f4 and no refs to 0xb4d80 because seg2 is not
  cleanly disassembled. This is the same seg2 blocker noted in RE_findings.
- Flash address-range validation demonstrably exists: the ASW-segment-end constant **0xbd424**
  is referenced from literal pools at 0x9eba8 and 0x14b70.

## Feasibility logic for the SBOOT leak

SBOOT is **not** inside the ASW image (0x0–0x134011); it lives at a separate/protected flash
address the image doesn't cover. So a 0x23 leak needs BOTH:
1. the 0x23 bounds check to permit that region (or to be absent / have an OOB bug), **and**
2. knowledge of SBOOT's mapped address — which a permissive 0x23 lets us find by scanning.

If the bounds check restricts 0x23 to the ASW/CAL ranges only, we need an unbounded-read bug
(OOB length, integer overflow in the addr+len math, or reading RAM where SBOOT is shadowed)
instead. Either way the answer is in the seg2 0x23 executor's bounds check.

## Next step

1. Fix seg2 disassembly around the 0x23/0x34 executors (EspSeg2 + targeted BE-Thumb sweep),
   then decompile the ReadMemoryByAddress operation: read its format-id parse and the exact
   address/length bounds check.
2. Trace `flags=0xa0` to the SecurityAccess level required; confirm it is the SA2 we have.
Ties: [[esp8-flash-signature]] (why we want SBOOT), [[esp8-bench-pinout]] (how we'd talk to it),
[[abs-sa2-key]] (the unlock).

---

## UPDATE — seg2 disassembly fixed, bounds check DECODED

Fixed the seg2 coverage: added a Thumb prologue sweep over the Dcm region (0xbb048–0xe0000,
+136 functions via `EspThumbSweep2`), on top of the existing ARM prologue pass. That exposed the
memory-access validation chain. All three functions are ARM in seg2 (VMA=file+3).

### The bounds check: `FUN_000dc958` (address → region classifier)
```
r0 = requested address
if (address + 0x90000) carries  → return 0x0f   // i.e. address >= 0xFFF70000 -> NRC requestOutOfRange
table = *0x401eee                                // RAM, built at init (12 entries x 8 bytes)
for i in 0..11:
    desc  = (tbl[i].hw0 << 16) | tbl[i].hw1
    nib   = (desc >> 4) & 0xf ; if nib==0: continue
    mask  = (i < 6 ? 0xFFFFFC00 : 0xFFFF8000) << (nib-1)   // 1KB gran (i<6) / 32KB gran (i>=6)
    if (mask & address) == (mask & desc): return i          // region hit
return 0x0c                                                  // no region -> reject
```
So a read is allowed only if its address falls in one of **12 runtime-configured regions**, and
never above **0xFFF70000**.

### Callers (the memory services), all in seg2
- `FUN_000d76f4(idx, req)` — range validator: classifies the request's **start (req+4) and end
  (req+2)** via `FUN_000dc958`, packs the two region indices + permission bits
  (`iVar3<<5 | iVar4<<1 | flags & 0x1f000001`) into a per-request descriptor at `*0x401eee+... /
  DAT_000d77f8+idx*0x10`. This is the read/write-by-address + download validator.
- `FUN_000dec64(out, addr)` — helper: stores addr and its region index.
Called from 0xd778c/0xd7798/0xdec74 — the 0x23 / 0x3d / 0x34 operation handlers.

### What this means for the SBOOT leak
- The read primitive can address **almost the whole 32-bit space** (ceiling 0xFFF70000), BUT only
  addresses inside the **12-entry allowlist** pass; each region also carries permission bits
  (some may be read-only / security-gated).
- **The allowlist is runtime RAM data at `0x401eee`** (built at init from config — the same
  runtime-object-table blocker as the COM map). Its contents decide whether SBOOT's flash
  addresses are reachable. It is NOT a static flash table we can just read here.

### Next step (resolves the whole question in minutes)
Power the bench unit and **read RAM `0x401eee` (12 x 8 = 96 bytes)** — that hands over the exact
allowed regions + permissions. If a region covers the SBOOT flash address, a security-unlocked
0x23 dumps it; if not, we need the region-table builder (reverse the init that writes 0x401eee) or
an OOB bug. Either way the read/write/download validator is now fully mapped.

---

## UPDATE — heuristic hunt for the region-table init (result: it is computed, not static)

Goal: recover the 12-region allowlist statically by finding the flash config that seeds RAM
`0x401eee`, avoiding a bench read. Ran a full sweep; the table is **built at init by code, not
copied from a static flash table.** Evidence:

1. **Only the classifier references `0x401eee`.** Image-wide, `0x00401eee` as a literal appears
   once (the classifier's own pool at 0xdc9c9). No builder loads that exact base.
2. **The RAM around it is a general diag/status block, not a clean 96-byte table.** `EspRefsRange
   0x401ee0-0x401f60` shows ~15 functions reading/writing individual fields (status refresh
   `FUN_00045f20`, per-request accessors `FUN_000d5980/000d6f78/000c192c`, etc.). No single
   12x8 init loop writes it.
3. **The C-runtime `.data` copy does NOT initialise it with region data.** The startup copy that
   covers this RAM is `{src=0xb0410 flash -> dst=0x40082c..0x4060e6}` (found by copy-descriptor
   scan). The bytes at the mapped source for `0x401eee` (flash 0xb1ad2) decode to zeros/noise, not
   region descriptors — so the table is empty at .data time and filled later by init code.
4. **No static memory-range (low/high) table exists in the diag config.** Dumped the diag-config
   region (0xb4400-0xb4740): it holds session-permission arrays, the DID table, and a pointer
   table into 0xb2xxxx — no `DcmDspMemoryIdInfo`-style {low,high} array. Range-pair and high-mem
   constant scans returned only ARM-opcode / string-table noise.

**Conclusion:** the region descriptors are computed during ECU init (the same runtime-object-table
class of blocker as the COM map, `second_code_segment.md`). They are not extractable by a static
config walk.

### Two ways to get the actual regions
1. **Bench RAM read of `0x401eee` (96 bytes)** — after UDS is up + SA2 unlock, one `0x23` of the
   table itself hands over all 12 regions + permission bits. Fastest, definitive. (Circular only
   if the table gates reading itself; RAM 0x401eee is well below the 0xFFF70000 ceiling and almost
   certainly in an allowed region, so this should just work.)
2. **Emulate the Dcm init chain** to materialise `0x401eee` (heavy; prior object-table emulation
   forks stalled on the per-record loop — same blocker).

Recommended: path 1 on the bench. Everything else in the read/write/download validator is mapped.

---

## UPDATE — emulation attempt (result: table is RTOS-init state, not cold-reachable)

Ran a full-startup Unicorn capture (`emu/exp_region_table.py`): seg2 overlaid at +3, 65 RAM bases
seeded, watch writes into 0x401ee0-0x401f60, run from the ASW entry, then decode 0x401eee.

**Result: 0 writes into the table window; it stayed all-zero** (every entry `nib=0` = disabled,
which would make `FUN_000dc958` reject every address — proof the real ECU populates it later).

Why cold emulation can't reach it, verified:
- **The reset vector at flash 0x0 is a stub** (`b .` = 0xEAFFFFFE). The real reset entry lives in
  the missing **SBOOT**, which jumps to the ASW. So there's no in-image `_start` to run.
- The ASW entry we have **returns** under cold call ("ended normally") — the region-table init
  runs under the **RTOS main loop / scheduler**, which Unicorn won't drive (no tasks/interrupts).
  Same "init never starts under cold emulation" wall as the COM object table.
- **No code writes 0x401eee by that literal** (only the classifier's pool references it), and the
  functions that do touch that RAM window (`FUN_0006dd88` wheel shuffler, `FUN_00045f20` status
  refresh) write unrelated fields — there is no standalone builder to call directly.

**Conclusion:** the 12 region descriptors are materialized only by the running diagnostic/RTOS
init — the project's known runtime-object-table blocker. Getting them offline would require
reconstructing the ASW RTOS init sequence (large, uncertain; prior COM-init forks stalled here).

**Definitive resolution stays the bench read:** power up, SA2-unlock, `0x23` read 96 bytes at
`0x401eee`. That returns the live regions + permission bits in one shot and settles SBOOT
reachability. Harness kept at `emu/exp_region_table.py` for a future RTOS-init reconstruction.

---

## CORRECTION (important) — FUN_000dc958 is NOT the 0x23 bounds check

Reconstruction traced the callers of the "bounds check" and it is **mis-identified**.
`FUN_000dc958`'s only callers are `FUN_000d76f4` and `FUN_000dec64`, and those are called from
`FUN_000cdfd0` / `FUN_000d300c`, which are **communications transfer routines**: hardware
TX-ready poll loop (`do{}while((*(param_5+0xb)&1)==0)`), per-channel state blocks
(`DAT_000ce1dc/e4/e8/ec`), byte/halfword data-width selection, transfer start/wait helpers
(`FUN_000dde68`/`FUN_000ddf0c`). So:

- **`FUN_000dc958` = DMA/comms buffer-address classifier** (maps a transfer buffer address to a
  memory-type/region descriptor). The `0xFFF70000` ceiling + 12-region table (RAM `0x401eee`) are
  the transfer layer's memory-type map, **not** a UDS ReadMemoryByAddress permission allowlist.
- The behavioural search that led here (address-parse + memory ceiling) matched the wrong
  subsystem. Retracting the earlier claim that this is the 0x23 bounds check.

### Still valid
- Service table @0xb4d80: **0x23 ReadMemoryByAddress and 0x3d WriteMemoryByAddress exist and are
  security-gated (flags 0xa0)**; flash trio 0x34/0x36/0x37 + 0x31 present.
- seg2 disassembly improved (+136 Thumb fns in the Dcm region).

### Still UNKNOWN
- The actual 0x23 executor and its address bounds check. It is in the seg2 Dcm stack behind
  function-pointer/config indirection that static xref-walking and the emulation sweep (all 431
  seg2 Dcm fns, none write a memory-permission table cold) did not resolve.

### Recommended path — answer it empirically on the bench (no exact RE needed)
The question is "can 0x23 read SBOOT," and that is directly testable:
1. Power up, UDS on 37/24, `0x10 0x02` + SA2 unlock.
2. `0x23` probe reads at known-good addresses (a flash addr in the ASW, a RAM addr) to confirm the
   service works and see the addr/len format the ECU accepts.
3. `0x23` probe reads at candidate SBOOT/boot addresses (low flash below the app, and high memory
   near the 0xFFF70000 region seen in the comms map) and observe positive response vs. NRC.
This maps the real readable ranges in minutes, independent of where the static check lives.

---

## SESSION CONCLUSION (supersedes the retracted sections above)

Reconstruction from a VERIFIED anchor (the diag response buffer `diag_resp_buf 0x401854`, whose
part-number DIDs confirm it) settled the question **from the bin alone**:

**The ASW enumerated diagnostic handlers = every writer of 0x401854:**
- `FUN_000c71ac` DTC list build + bubble-sort by status
- `FUN_000dcdb4` DTC-info-by-index read (16-byte records, fields +0/+1/+4/+0xd) — UDS 0x19
- `FUN_000dd004`/`FUN_000ddf5c`/`FUN_000d2090` status/measurement responses
- `FUN_000dcd3c` checksum: sum of a FIXED buffer (`*DAT_000dcda8`, len `DAT_000dcda4+8`, cap 0x400)
- `FUN_000d5ab8`/`FUN_000dd378` split-response setup + request-field parse into a state struct
- `FUN_000dbe90`/`FUN_000dde68`/`FUN_000ddf0c` response transmit via the comms layer
- DID reads (0x22): `diag_did_table 0xb44e4` — identity/coding DIDs only (0x0405-08, 0xF1xx)

**None parse an addressAndLengthFormatIdentifier or read an arbitrary address.** The services
present are 0x22 (DID), 0x19 (DTC), routine/checksum, and response TX — all reading FIXED, indexed
structures.

**Answer: the ASW does NOT implement UDS 0x23 ReadMemoryByAddress.** Three independent lines agree:
1. No arbitrary-address read among any response-buffer writer (above).
2. The SA2 *programming* seed/key constants (0x974C58AB, 0x98765432) are ABSENT from the ASW body
   — programming security is bootloader-resident.
3. Identical to the sibling AL551 TCU ([[tcu-uds-dump]]): "app 0x23 svcNotSupInSession everywhere;
   bootloader write-only."

**Therefore a 0x23 SBOOT-over-CAN leak is not achievable through the ASW.** The memory-read +
programming-security code lives in SBOOT/CBOOT, which is NOT in this image (we have ASW+CAL only).
The config values the user expected "in the bin" for a 0x23 gate are not there because that service
does not exist at the app level. Reading SBOOT requires the bootloader (a hardware dump), or an
SBOOT/CBOOT image obtained another way.

### Retracted this session (record integrity)
- "service table @0xb4d80 = UDS dispatch" — FALSE: its code-pointer column lands mid-function in
  COM/control code (e.g. 0x9a964 is inside COM fn FUN_0009a900), not on handler entries.
- "FUN_000dc958 = 0x23 bounds check" — FALSE: it is a DMA/comms buffer-address classifier.
- "0x23 exists + security-gated" (memory esp8-uds-read-primitive, orig) — FALSE per above.
Root cause of the false leads: this firmware reuses the UDS-SID-range constants (0x10-0x3e) densely
as internal state/DTC codes, so decompile/byte pattern-matching for UDS structures misfires; only
the diag_resp_buf-anchored enumeration is reliable.
