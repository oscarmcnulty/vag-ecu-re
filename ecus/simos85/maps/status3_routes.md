# TSK_Status_GRA_ACC_01 = 3 — the three routes into the latching ACC fault

`TSK_Status_GRA_ACC_01` (TSK_02 / 0x10C, byte3 bits 1-0) is the CAN copy of the CRUC state
machine's state: `d000b28d` (`STATE_CRU_CTL_CAN`). Value **3 = Fehler_GRA_ACC**, and it is the
only value that stops ACC — states 0/1/2/5 are normal operation.

**Why it latches.** `8013e8aa` (the state dispatcher) has **no dispatch case for state 3** —
verified in disassembly at `8013e8ac`:

```
8013e8ac:  ld.bu d15, d0001165        ; d15 = internal state shadow
8013e8b0:  jeq d15,#1, 8013eaba        ; state 1 handler
8013e8b6:  jeq d15,#2, 8013eb86        ; state 2 handler
8013e8ba:  jeq d15,#4, 8013ed68        ; state 4 handler
8013e8be:  jeq d15,#5, 8013ed80        ; state 5 handler
8013e8c2:  j 8013ee5c                  ; state 3 (and 6) -> straight to exit, NO transition code
```

Once `d0001165 = 3`, every later cycle falls through to the exit and re-emits 3. The **only**
way out is a full CRUC re-init (`801abc7c`, which writes `d0001165 = 0`), and that runs only on
an ACC master-mode cycle inside `800d9ea8` — i.e. **ACC disengage + re-arm, or a key cycle**.
Streaming clean CAN afterwards does *not* clear it.

Addresses: load base `0x80000000`; cal file offset = `addr & 0x1FFFFFFF`. Names are those in
`../analysis/symbols_merged.csv`. Every store below was cross-checked against the corrected
instruction-level write map (`DumpAllWrites` re-run with Simos85 base regs
`a0=0xd0008000 a1=0x80048000 a8=0x80088800`; the committed script hardcodes MED17's, off by
0x4420 for this ECU).

All 8 writers of `d000b28d`:

| store addr | function | value | route |
|---|---|---|---|
| `8013e484` | `8013e47c` (state-1 handler) | 1 | — |
| `8013e3fe` | `8013e3f8` (state-5 handler) | 1 | — |
| `8013e67a` | `8013e674` (state-2 handler) | 2 | — |
| `8013ebbc` | `8013e8aa` (1->6) | 0 | — |
| `8013edb0` | `8013e8aa` (5->0) | 0 | — |
| `801abca8` | `801abc7c` (CRUC init) | 0 | the un-latch |
| **`8013e926`** | **`8013e8aa` (fault entry `LAB_8013e910`)** | **3** | **A + B** |
| **`8013fd5e`** | **`8013ef46` (coding-reset branch)** | **0 or 3** | **C** |

---

## Route A — the external-fault OR (`d000a59c`), from ANY state

The dominant route. `8013ef46` builds condition-word bit 3, and every state handler in `8013e8aa`
transitions to 3 when bit 3 is set (states 0,1,2,4,5 — verified: `jnz.t d1,#3,8013e910` in the
1/5 handlers, equivalents in 0/2/4).

```c
// 8013ef46:731-737  — CRUC condition word, bit 0x08
if (d000a59c == 0 && d000b298 != 3)  cond_word &= ~0x08;   // bit3 clear
else                                 cond_word |=  0x08;   // bit3 set -> state 3

// 8013e8aa, e.g. state-1 handler @8013eaba:
//   8013eac0: jnz.t cond,#3, 8013e910   ; bit3 set -> LAB_8013e910 -> STATE_CRU_CTL = 3
```

So Route A fires when **`a59c != 0` OR `b298 == 3`**.

### A.1  `a59c` — the 16-bit input-fault OR

```c
// 801408bc:224-302  (acc_master_request_producer)
fault_word = 0;                                             // c000118a
fault_word |= (a68a)                       ? 0x0001 : 0;
fault_word |= (a690 || a691)               ? 0x0002 : 0;
fault_word |= (aab5)                       ? 0x0004 : 0;
fault_word |= (!a3b4 && aa3f)              ? 0x0008 : 0;
fault_word |= (aa3f && (d0007bba & 0x1101))? 0x0010 : 0;   // cal 0x80043cec = 0x1101
fault_word |= (aab9 || aabe || aabf)       ? 0x0020 : 0;
fault_word |= (a03b)                       ? 0x0040 : 0;   // EGAS-L2 torque monitor
fault_word |= (a9d7)                       ? 0x0080 : 0;
fault_word |= (aa2c)                       ? 0x0100 : 0;
fault_word |= (a9a5)                       ? 0x0200 : 0;
fault_word |= (aa6f)                       ? 0x0400 : 0;
fault_word |= (a9ed)                       ? 0x0800 : 0;
fault_word |= (aac2 || aac3)               ? 0x1000 : 0;
fault_word |= (aa30)                       ? 0x2000 : 0;
fault_word |= (aa4e)                       ? 0x4000 : 0;
fault_word |= (aa39 || aa38)               ? 0x8000 : 0;

a59c = ((fault_word & 0x80043cf2) != 0)        // cal mask = 0xFFFF -> ALL 16 bits live
       || (d00016e9 != 0);                     // 17th independent term (sensor/actuator OR)
```

**What the 16 bits are.** With one exception (bit 6) they are *ACC input-signal validity /
DTC-active* flags. Each source flag is produced by a sampler that either reads the live COM
signal-descriptor status (`PTR_DAT_80086xxx[2] >> 2 & 1` = "signal invalid / timed-out") or
substitutes the stored DTC state (`update_ecu_state_800a8ebc(<dtc#>, …)`). In plain terms: **ACC
depends on a set of CAN inputs from other ECUs; if any required one is missing, E2E/timeout-
invalid, or carries a stored fault, its bit sets and the CRUC machine latches status 3.**

| bit | mask | source flag(s) | writer | identity / how to read it |
|---|---|---|---|---|
| 0 | 0x0001 | `a68a` | `8010ce2c` | aggregate present/valid: `a68a = a9a9\|a9aa\|a9ab\|a690\|a691` |
| 1 | 0x0002 | `a690`,`a691` | `8010ce2c` | set from `aa6c`/`aa6d` (subset of bit 0) |
| 2 | 0x0004 | `aab5` | `80147738` | COM signal-invalid (indexed descriptor `80086160[]`) |
| 3 | 0x0008 | `aa3f`&`!a3b4` | `aa3f`←`801a6310` | **DTC 0x9F**, COM `0x80086b50`; gated by `a3b4==0` |
| 4 | 0x0010 | `aa3f`&qualifier | `aa3f`←`801a6310` | same DTC 0x9F, ANDed with `d0007bba & cal 0x80043cec(0x1101)` |
| 5 | 0x0020 | `aab9`,`aabe`,`aabf` | `80147738` | three COM signal-invalid flags |
| 6 | 0x0040 | `a03b` | `8009c0b4` | **EGAS-L2 torque monitor** (see A.2) — NOT a CAN input |
| 7 | 0x0080 | `a9d7` | *indexed DTC (GAP)* | consumed by `8010a6ec`; no resolvable writer |
| 8 | 0x0100 | `aa2c` | *indexed DTC (GAP)* | consumed widely (`801108f8`,`80153270`,`801df398/7f4`) |
| 9 | 0x0200 | `a9a5` | `80174730` | plausibility flag (paired with `a9a6`) |
| 10 | 0x0400 | `aa6f` | *indexed DTC (GAP)* | consumed by `8010a314`,`801383d4`,`8013b0ec` |
| 11 | 0x0800 | `a9ed` | *indexed DTC (GAP)* | consumed by `8013bee8`,`8013b0ec` |
| 12 | 0x1000 | `aac2`,`aac3` | `80147738` | two COM signal-invalid flags |
| 13 | 0x2000 | `aa30` | *indexed DTC (GAP)* | consumed by `800f9304`,`80153270`,`801df398` |
| 14 | 0x4000 | `aa4e` | `801a78c4` | COM signal-invalid, COM `0x80086c40` |
| 15 | 0x8000 | `aa39`,`aa38` | `801a6310` | **DTC 0x99/0x98**, COM `0x80086af0`/`0x80086ae0` |
| +  | (17th) | `d00016e9` | `801408bc:220` | sensor/actuator-validity OR, masked by cal 0x80043296(0xFF) |

Five bits (7,8,10,11,13) are **read all over the ACC diagnostics but have no writer resolvable
statically** — they are written through an indexed DTC-status-array store (the class of writes the
constant-propagation leaves unresolved). They are real fault inputs; their exact DTC identity is a
**GAP** (needs the external DTC/DBC table). The 6 samplers cover DTC numbers 0x98–0xAF against COM
handles `0x80086ae0…0x80086d90`.

Practical note for an external ACC master (openpilot): dropping or corrupting *any* of the ~16
required input frames on the interposed bus is sufficient to latch status 3. This is the standard
"loss of a required bus input → ACC unavailable" behaviour, not a speed floor.

### A.2  `b298 == 3` and the GRA-side latch

`b298` is the ACC main-state enum, and `b286` is the GRA main-state; either reaching 3 drives
Route A.

```c
// 801408bc:449-500 — b298 (d00016ea) reaches 3 when:
//   * coding-OFF path (bVar2), OR
//   * assist-fault selector: bits of bVar23 (cal 0x8004327a[0xf]) via d00016ee/ec/ed, OR
//   * mirror of the GRA main state b286.

// 8013a754  — GRA main state
if (a551 != 0)  b286 = 3;      // LAB_8013aa62 : GRA fault park

// 8013b0ec:236-239 — the GRA fault latch a551
d00011a0  = bit0:(aa6f|a9ed sensor)  bit1:(a9a5)  bit2:(aa3f & a3b4 brake-signal)
          | bit4:(a68a|a62e|a62f|a07a|a03b|a62d cluster, incl. EGAS-L2)  bit5:(b28a);
if ((d00011a0 & 0x8004340e /*=0x77*/) != 0)  a551 = 1;   // -> b286=3 -> b298=3 -> status 3
```

So the same physical faults feed status 3 through two parallel paths (`a59c` directly, and
`a551 → b286 → b298`); the EGAS-L2 monitor (`a03b`) appears in both.

---

## Route B — the brake-override fault timer (`d0001177`), from STATE 0 only

This is the subtle one. Condition-word **bit 4** is checked **only in the state-0 handler**
(`8013e8aa:8013e8cc: jz.t cond,#4,8013e92c` — bit4 set falls through to `LAB_8013e910` = state 3).
In states 1/2/4/5 bit 4 is never consulted.

```c
// 8013ef46:106-130 — bit4 source (d0001177)
if (b296 == 1) {                              // b296==1 = DRIVER BRAKING / override active
    d0001176 = (timer116e-- reached 0);        // 3-cycle debounce, cal 0x8004377a
    if (b297 == 1) {                           // b297==1 = high-level cruise STILL ENGAGED
        d0001177 = (timer1170-- reached 0);    // 20-cycle debounce, cal 0x8004377c
    } else {
        d0001177 = 0;  timer1170 = 20;         // b297 left "engaged" -> reset, no fault
    }
} else {
    d0001176 = 0;  timer116e = 3;
    d0001177 = 0;  timer1170 = 20;             // not braking -> reset both
}

// 8013ef46:738 — bit4 = d0001177
// 8013e8aa state-0 : bit4 set -> STATE_CRU_CTL = 3
```

### What Route B is actually preventing (answering "isn't state 0 off, so braking is normal?")

State 0 is **standby**, not "ECU off": ACC is still armed and computing (`acc_master_compute_enable
= 1`, cruise/ACC coded). Two different things happen when the driver brakes:

1. **The normal cancel** (`d0001176`, 3 cycles). Driver taps the brake → `b296 = 1` → after
   3 cycles `d0001176` sets → it feeds the inhibit word `d0001169.bit0 → d0001160 (mask
   0x80043422=0xEF) → cond-word bit 1`, which forces the machine out of `{1,5}` down to standby
   (state 0). Status goes **1 → 0**. This is exactly the "braking cancels active regulation, ACC
   waits in standby" behaviour you'd expect, and it is *not* a fault — state 0 can re-engage to 1
   when conditions return.

2. **The escalation to a fault** (`d0001177`, 20 cycles). The fault fires **only** when, for
   20 consecutive cycles, the driver is braking (`b296 == 1`) **AND the high-level cruise/ACC
   engage-state still reports itself ENGAGED** (`b297 == 1`, = GRA main-state `b286` when
   GRA-coded, else DCC substate `b29d`). The moment the brake properly cancels cruise, `b297`
   leaves 1 and the 20-cycle timer resets — so a normal braked stop never trips it.

The condition it catches is therefore a **contradiction**, not ordinary braking: the low-level
regulator has been driven to standby by the brake, yet the high-level engage bookkeeping is *stuck
at "engaged"* while the driver keeps braking. That is a failed-cancel / stuck-override plausibility
violation. Rather than sit indefinitely in a state where the lever thinks ACC is engaged while the
driver overrides it, the monitor raises Fehler_GRA_ACC and latches.

So Route B "prevents" the ACC from **silently re-engaging (or lingering armed) after a brake
override that never resolved into a clean cancel** — it converts that stuck state into a fault that
forces a disengage/re-arm. (Cycle rate is the ACC task period; if 20 ms, 20 cycles ≈ 0.4 s —
**INFERRED**, task rate not pinned here.)

---

## Route C — the coding / unsupported-mode reset

```c
// 8013ef46:73-84 — entered when ACC is running but the coding is wrong:
//   (coding_GRA_ena == 0) && (LV_DCC_ENA == 0 || acc_mode_ACC05_Momentenanf_sel != 0)
if (aab5 != 0 && cal_0x80043d7f != 0)  STATE_CRU_CTL_CAN = 3;   // cal = 0x01 (live)
else                                   STATE_CRU_CTL_CAN = 0;
```

Fires when the ECU is **neither GRA- nor DCC/ACC-coded**, or ACC_05 (Macan) mode is selected —
a wrong-coding / unsupported-configuration fault. `cal 0x80043d7f = 0x01` in this image, so with
`aab5` set the branch emits status 3. This is why VCDS rejects follow-to-stop (cell 27 = 3): the
coding asserts a mode the firmware stub doesn't implement → status 3. This route is **not** a
runtime fault — it's config-driven and clears when the coding is corrected.

---

## One-line summary

| route | trigger | from state | mask/cal to move it |
|---|---|---|---|
| **A** | `a59c != 0` (any of 16 input-fault bits + `d16e9`) OR `b298==3`/`b286==3` (GRA latch `a551`) | any (0,1,2,4,5) | fault mask `0x80043cf2`=0xFFFF; GRA mask `0x8004340e`=0x77 |
| **B** | driver braking **and** high-level cruise still "engaged" for 20 cycles | 0 only | debounce `0x8004377c`=20 |
| **C** | wrong/unsupported coding **and** `aab5` set | (reset branch) | gate `0x80043d7f`=0x01 |

**None of the three is keyed on an internal vehicle-speed threshold**, and none is the ESP's
`ECD_nicht_verfuegbar` (that shifts state 1↔5, both still status 1). The ESP reaches status 3 only
through Route B, via `ESP_Fahrer_bremst` (driver braking), not via its 15 km/h ECD bit.

---

## Appendix — the acceleration side & the "L2 monitor / 15 km/h" story (2026-08-20)

Two questions that arise alongside the routes above, resolved by tracing:

**Is there an acceleration analog to the ESP's ECD (decel) gate?** No speed-gated one. Positive
torque is engine-delivered, so nothing external permits it. The acceleration-side safety net is the
**EGAS-L2 torque monitor** (`8009c0b4` + `8009cf94` → `a03b` → **Route A** bit `0x40` / GRA latch
`a551`). It arms on `acc_ACC_Status_ACC ∈ {3,4}` and faults when positive ACC torque is commanded
while un-armed — a **torque-vs-ACC-status consistency check**. It reads **no ego speed** (verified by
grep and disassembly), so it is not a 15 km/h fault; it applies at all speeds. For an external master:
inject positive torque only with `ACC_Status_ACC ∈ {3,4}` and it stays quiet. (Below the 3 km/h
`C_VS_MIN_CRU` floor the cruise-torque PI resets its integrator — a floor, not a fault; and the OEM
standstill launch-torque path (`80141528`, ACC_05) is cal-gated off on the Q5.)

**Why did earlier notes think "the L2 EGAS monitors flag under 15 km/h"?** An inverted reading of the
FR. The cals named `C_VS_MIN_CRU_MON` (=15) live in the EGAS-L2 layer, but:
- In `8009c0b4` the 15/13 constants are **debounce-counter presets**, not speed compares (disasm
  `8009ce4a: d9 = d9 - (d9!=0)` — a countdown). No reader of `0x456bd/c0/c3` or their shadow copies
  compares them against vehicle speed.
- FR ch.14.16.2 p.2202 shows the quantity drives **SET of the SR latch `LV_CRU_MON_ACT_MON`** (“active
  monitoring of cruise control”), **RST by `STATE_CAN_CRUS_OFF`** — i.e. `C_VS_MIN_CRU_MON` is the speed
  at which the L2 cruise monitor **ARMS** (active *above* ~15, disarmed below), not a fault/cutoff.
- So the FR is consistent with "no L2 fault below 15": below the threshold the monitor is *off*. The
  only genuine sub-15 behavior is the ESP's ECD decel withdrawal (external), not this monitor.

The one live `VS_MON`-vs-15 compare in the engine (`80102f60`, cal `0x794ef`) is **reporting-only** —
it feeds `d88b` bits nothing reads plus the `a35f` telltale on frame **0x5C0**; it does not set either
status enum (`b28d` on TSK_02 or `d91d` on 0x5C0) and does not gate control (`low_speed_floors.md` §1).
