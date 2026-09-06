# COM RX routing — bootstrap-emulation result & static signal-table decode

Focused attempt to materialize the CAN-ID → signal-buffer routing by emulation and byte-prove
`EPB_01 → decel_src_type5`. Outcome below is honest: the signal→buffer layer is recovered
statically; the CAN-ID binding and the EPB→type5 proof are **blocked by SBOOT-initialized `.data`
that is absent from this ASW image**. Every claim here is emulation- or byte-verified.

## Bottom line
- **EPB_01 → type5: NOT byte-proven.** type5 (`0x403d76`/staging `0x403d6e`/`0x403d66`/enable
  `0x403d7d`) appears **only in code literal pools, nowhere in flash config**. type1's and
  type4's COM source signals *do* appear in flash config (`0x403fa2`, `0x407ce8`…). So type5's
  feed is entirely runtime-indirect — neither confirmable nor cleanly refutable from this image.
- **CAN-ID → buffer bindings recovered: 0 complete.** The signal→buffer half is recovered
  (`decode/com_signal_table.txt`), but signal→PDU→CAN-ID grouping lives in SBOOT-initialized
  `.data` and cannot be reconstructed from the ASW image alone.
- **Which approach worked:** C (static flash decode) partially; A and B **blocked** (below).

## The bootstrap blocker (emulation-verified, the decisive new finding)
`_start` is at **0x8f440**. Emulated for 200 insns it issues **10 SBOOT monitor SVCs**
(`svc #0x13..#0x16`, `#0xff10`) to bring up CPU modes / OS. The `.data` section — which holds the
COM **object table** (`*0x4069b4`), the runtime **signal descriptors**, the bump pointer
(`0x4069b0`), the message count (`0x4069fc`), and the PDU→CAN-ID grouping — is initialized by
**SBOOT**, which is not in this image (reset vector `0x0` = `b #0`, self-loop). Consequences:
- `FUN_0006b936` (bump allocator) run from zeroed RAM makes **3 writes, allocates nothing** — it
  needs the seeded object table/descriptors. (emu-verified, `emu/exp_com_bootstrap.py`.)
- So **approach A (emulate config-init) cannot bootstrap** from this image, and **approach B
  (replicate)** has no object table / grouping to replicate.

## Parent's "allocator" correction — CONFIRMED by emulation
The "COM handle-allocator veneers" are trivial thunks (parent finding, now emulation-checked):
- `0x49e80` = **byteswap16**: `byteswap16(0x0102) → 0x0201` ✓
- `0x49e64` = **memset(ptr,0,n)** ✓
- `0x4a48c` = bounds check. There is **no runtime handle allocator**; the routing is config-driven.

## What IS recovered software-only: the flash COM signal→buffer table
`FUN_0006b936` assigns buffers from a **static flash config**. One block decoded (proven, stride
0x10, marker `0x01000000`): `{sig_id u16, len u8, flags u8, RAM_buffer u32, extraction_link u32}`.
- **43 records @ flash 0xb03fc–0xb06cc** (block continues further); full list in
  `decode/com_signal_table.txt`. `RAM_buffer` = where the COM layer deposits that signal; buffers
  land in `0x405xxx–0x409xxx`. `extraction_link` → per-signal unpack code/descriptor.
- Anchor examples proving it is real: sig `0x037f` → buffer `0x403fa2` (adjacent to type1 staging
  `0x403fa4`); sig `0x004f` → `0x407ce8`, sig `0x03bc` → `0x407cf0` (type4/ANB source signals).
- This is the **signal→buffer half of the routing, recovered without a bench** — the layer prior
  work believed was fully opaque is not.

## Why type5/EPB specifically stays unresolved
All four decel **staging** buffers (type1 `0x403fa4`, type4 `0x407bac`, comfort `0x403a6c`,
type5 `0x403d6e`) are **absent** from the flash COM signal table — they are outputs of app
*builders* fed from the COM signal buffers, not direct COM deposits. type1/type4/comfort have COM
source signals sitting next to them in flash config (`0x403fa2`, `0x407ce8`, …); **type5 has no
COM signal anywhere near it and zero flash-config footprint**. Its writer is runtime-indirect
(no static writer — parent finding, re-confirmed). Binding EPB_Verzoeg_Anf (EPB_01 byte 2) to
type5 therefore needs the SBOOT-resident descriptors: **not recoverable from this image**.

## To actually close it (unchanged, but now precisely scoped)
1. **SBOOT/BDM dump** — supplies the initialized `.data` (object table + descriptors + PDU→CAN-ID
   grouping) directly; then the static decode here completes and the emulation runs. This is the
   real unlock (also gives the valve MMIO map). Downgraded from "required for the whole wall" to
   "required only for the CAN-ID grouping + type5 feed".
2. **On-car capture** — log `EPB_01` during a low-speed lever-hold, correlate `EPB_Verzoeg_Anf`
   with `ESP_05` brake-active + wheel decel. Decisive for the EPB channel; not software-only.

## Artifacts
- `emu/exp_com_bootstrap.py` — veneer-correction check, `_start` SBOOT-SVC blocker demo, allocator
  -needs-config demo, signal-table decoder.
- `decode/com_signal_table.txt` — the recovered flash COM signal→buffer table.

## CORRECTION (2026-09-02, later) — the mappings ARE in the ASW bin; SBOOT is NOT required

The "needs SBOOT-resident .data" conclusion was WRONG for the grouping. SBOOT is a generic
bootloader and contains NO application COM config. What SBOOT does is run the C-runtime startup
(the `.data` copy, whose SOURCE is our flash) and provide monitor SVCs — that is only why emulating
`_start` (0x8f440) hit SVCs.

**The full COM PB-config is in our flash bin, region ~0xb0000-0xb7800** (~30 KB, dense with RAM
`.data` pointers): the signal->buffer table `0xb038c` (54 recs), `com_sig_group_table` 0xb6a44,
`com_pdu_descriptor` 0xb6ffc, and nested per-PDU descriptor records (e.g. @0xb38c0: RAM buffer
pointers + size + `0x008001xx` bit/len encodings). **The message->signal grouping is part of this
config** — it is present, just in a complex nested multi-format AUTOSAR-COM layout.

**Corrected status:** recovering CAN-ID -> buffer is a **static PB-config PARSING problem** (or a
config-init emulation seeded with the root pointers we apply ourselves from this flash region) — NOT
blocked by SBOOT, and NOT requiring a bench/BDM dump. The remaining difficulty is purely the
format-reversal of the nested PB-config. To run the config-init in emulation instead, apply the
`.data` init (source in-bin) then call `FUN_000892a0`/`FUN_0006b936` with `*0x4069b4` seeded.

## STATIC PB-CONFIG PARSE (2026-09-02) — EPB_01 -> type5 DISPROVEN; type5 is a dead source

Static parse of the flash COM PB-config (no bench/emulation). Parser: `decode/parse_pb_config.py`,
table: `decode/can_to_buffer.csv`.

### Result 1 (DECISIVE, bin-wide proof): EPB_01 -> type5 is FALSE
Every type5 address is referenced ONLY in code, NEVER in the flash COM config:
- `0x403d76` (current): code 0x65090/0x7f728/0x86974  | `0x403d6e` (staging): code 0x65094
- `0x403d66` (commit-dest): code 0x64ff8            | `0x403d7d` (enable): code 0x431f4
- flash-config (>=0xa2000) occurrences: **ZERO**.
The staging `0x403d6e` has **no writer of any kind** (not static, not a COM descriptor dest -- if a
descriptor targeted it, `0x403d66` would be a flash literal; it is not, anywhere in the 1.2 MB image).
So type5's value is permanently 0 and can never win arbitration (`value>0` gate). **type5 is a
reserved/UNUSED decel source in this variant.** The parent's "type5 = EPB pass-through" inference is
refuted: no CAN signal, EPB or otherwise, reaches type5.

By contrast the live COM-fed decel inputs DO appear in flash config: type1 `0x403fa2` (@0xb0694/0xb0850),
type4-input `0x407ce8` (@0xb05a4/0xb07a8/0xb57b8).

### Result 2: the live decel inputs are FRONT-SENSOR messages, not EPB
Recovered two explicit-buffer COM signal tables (the only ones with static buffers; the ~200-msg bulk
uses the runtime object table): `com_signal_table_full` 0xb038c (53 sigs) and `com_pdu_signal_table`
0xb06f0 (34 sigs, groups 0x02/0xff). The PDU that feeds decel **type1** (`0x403fa2`/`0x403fd4`, sigs
0x037f/0x0383) is grp 0x02 = a **17-signal** PDU with bit-lengths {6,4,4,10,2,2,12,2,2,6,2,2,4,8,8,8,8}.
EPB_01's DBC length multiset is {8,4,1,1,1,1,8,8,8,1,1,2,2,1,1,5,2,1} -- **NO match**. The 10/12-bit
signals + brake-assist consumer (`FUN_00043228` reads the ANB/pre-sense region) mark this as a
front-camera/radar message, consistent with type1 = pre-sense/brake-assist. type4 input `0x407ce8`
(sig 0x004f) is likewise in a front-sensor PDU (grp 0xff, 26-bit object signals). **None of the four
decel sources traces to EPB_01.**

### Result 3 (blocker + implication)
EPB_01's own signals are NOT in these statically-explicit tables -- EPB_01 is in the runtime
object-table (bump-allocated) RX set, whose per-message buffer addresses materialize only when
config-init runs (they are computed, not flash literals). So a *positive* static bind of
EPB_Verzoeg_Anf's buffer was not reached. BUT combined with Result 1 (type5 dead) and Result 2
(type1/2/4 are ACC/front-sensor), the evidence indicates **EPB dynamic braking does NOT enter the ECD
decel arbitration (type1/2/4/5) at all** -- it is very likely a separate dedicated hydraulic-request
path. This reframes the earlier `epb_dynamic_braking.md` inference: "EPB -> a decel arbitration source"
is unsupported; the mechanism-level story (ESP reads EPB_01, executes a decel request hydraulically)
stands, but the specific internal channel is NOT type5 and NOT the parsed decel sources.

NEXT to positively bind EPB: run the seeded config-init emulation (materialize the object table) OR
find EPB_01's dedicated handler by its state_ram, then trace EPB_Verzoeg_Anf forward.

## EMULATION ATTEMPT (2026-09-02) — config-init runs; blocked ONLY on locating the object-table .data image

Tried the config-init bump-allocator emulation (`emu/exp_epb_cominit.py`). RESULTS:
- `FUN_0006b936` (the bump allocator) is **THUMB**, not ARM (2-aligned entry) — runs cleanly
  (returns 1). Earlier "3 writes, nothing allocated" was from running it as ARM AND from zeroed config.
- Confirmed the config is a **flash-copied `.data` blob** (findable in-bin, per the user's point): the
  flash signal table `0xb038c` is a *verbatim* image whose buffer pointers are fixed `.bss` addresses
  (`0x407xxx-0x409xxx`), i.e. copied, not relocated. Signal table `0xb038c` and PDU table `0xb06f0`
  have **zero code literal refs** → accessed via a runtime base pointer, i.e. they ARE `.data`.
- The bump allocator needs the **object table** (`*0x4069b4`) + its per-message signal **descriptors**
  seeded. My earlier "object-table candidates" `0xb041c/0xb059c` were WRONG — they are entries of the
  *signal* table (`0x01000000` marker), not the object table.
- Structural scans did **not** cleanly isolate the object-table image among the many similar COM
  descriptor tables in `0xb0000-0xb7800`, and the `.data` **section descriptor** (LMA/VMA/size) is not
  cleanly decodable from the ASW header (`0xbff30/0xbff40` read as code/obfuscated).

**EPB status:** EPB_01 = COM handle `0x25b` (mailbox `0xaeaa5`, HW reg `0xfff7ea00`). Its signal buffer
is object-table/bump-allocated, so `EPB_Verzoeg_Anf`'s address is materialised at init — one emulation
seed away, but that seed (the object-table `.data` image location) is the persistent blocker.

**Realistic unlocks (ranked):** (1) a **live RAM dump** `0x406000-0x40a000` on a bench (a plain memory
read, hands over the materialised object table + all buffers directly — minutes); (2) find the `.data`
section descriptor / trace the object-table builder (deep, multi-session, in-bin); (3) SBOOT/BDM dump.
The pure-static + function-emulation avenues are exhausted for this specific binding without one of these.

## THREE-FORK CONVERGENCE (2026-09-02) — routes closed + refined target

Ran three parallel heuristics. All closed cleanly; net result sharpens EPB and the object-table problem.
- **Output-trace (docs/epb_output_trace.md): EPB is PROVEN out of the ECD subsystem.** Exhaustive writer
  enumeration of the pressure setpoints (0x403d94), ecd_mode (0x405aba), ecd_ctrl_struct (0x403a14) and
  the actuation pipeline shows NO non-ECD writer. EPB dynamic braking touches none of it. => if the ESP
  brakes for EPB at all, it must use the **base ESP/ABS active-pressure-buildup controller** (yaw/ABS
  hydraulics), separate from ECD — NOT yet traced. Open possibility: this variant may not do autonomous
  ESP-hydraulic lever braking at all (consistent with the empty ECD result + only-4-decel-sources).
- **.data alignment (docs/epb_data_alignment.md): there is NO .data image to align.** Known init
  constants (0xb6a44/0xb6ffc/0xbda34) occur ONLY in code literal pools => the COM config is **.rodata,
  direct-addressed**, not copied to RAM. The object table (com_obj_table_base_ptr 0x4069b4) is
  **runtime-BUILT** from that .rodata; every accessor reads the base already-set. So static alignment /
  function-emulation can't materialize it. Correct remaining in-bin target = the **object-table builder**
  (writes *0x4069b4 from .rodata; base written via register — needs a data-flow sweep of the COM-init
  tree 0x50xxx/0x89xxx).
- **Boot emulation (docs/epb_boot_emu.md): blocked by SBOOT.** crt0 hands off via `bx sp` to
  SBOOT-provided context targets; SBOOT absent => can't reach COM-init. Definitively closed.

**Bottom line:** two independent negatives put EPB firmly outside the ECD path, and prove the object
table is runtime-built (no .data image). The two live software-only leads are (1) trace the **base ESP
hydraulic controller** for an EPB input (targets EPB directly, no object table needed), and (2) reverse
the **object-table builder** to materialize handle 0x25b's buffer. A live RAM read remains the trivial
non-software confirm.

## BASE-HYDRAULIC TRACE (2026-09-02) — inconclusive; leans "no external ESP hydraulic interface here"
Fork traced the ECD actuation thread: ecd_executor 0x9d75c -> base_dispatcher 0xa0da0 -> 0xa1d88 ->
esp_pressure_tx_packer 0x70ec0 — which is a **CAN-TX pressure packer**, NOT a valve/pump driver. The
real base ABS/ESC valve+pump MMIO driver is a separate main-loop subsystem behind the HW-ISR/MMIO
(0xfff7xxxx) indirection and was not reachable in a bounded pass. FINDING: in all reachable code the
ESP's ONLY external decel-request interface is the 4 ECD sources (type1/2/4/5) — no separate
external/driver/EPB pressure-request input feeds the actuation thread. => evidence LEANS toward "no
autonomous ESP-hydraulic external-brake interface beyond ECD on this variant" (i.e. lever-hold dynamic
hydraulic braking may not be an ESP feature here), but this is INFERENCE not proof: the base ABS/ESC
yaw/slip loop + terminal solenoid MMIO were not entered (large subsystem + HW indirection). Full: docs/esp_base_hydraulic.md.
