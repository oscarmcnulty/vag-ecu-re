# ACC_Anhalten / TSK_Anhalten — Simos8.5 vs MED17.1.1, and the "L2 monitor = 0" question

Comparative study (2026-07-27). Both ECUs sit on the same MLB powertrain CAN, RX **ACC_01 (0x109)** and TX
**TSK_02 (0x10C)** with identical wire layout (`ACC_Anhalten` = ACC_01 57|1; `TSK_Anhalten` = TSK_02 12|1).
Tags: [C]=read code/bytes, [I]=inferred, [G]=gap.

## Q1 — how `ACC_Anhalten` reaches `TSK_Anhalten` in each ECU

### Simos8.5 — DIRECT gated relay of the received CAN bit [C, from simos85/maps/acc_flow.md §6]
`ACC_01 (0x109) byte7·bit1` → decoder `801383e8` (E2E seed 0x08) → **`d000a7ae`** → `8013ef46:937-943`
(`a58d = a7ae` when the gate holds) → **`d000a58d`** → packer `80137a00` → **TSK_02 byte2·bit4**.
- Forward gate: `ad0f≠0` (compute-enable) ∧ `a757≠0` (Basic-ACC coded) ∧ `a5a8==0` (cal-fixed 0 on Q5) ∧
  **`b28e∈{1,5}`** (cruise actively regulating).
- So Simos **passes the driver/radar `ACC_Anhalten` bit straight through** to TSK_Anhalten, gated by runtime
  engage state.

### MED17 — relay of a DIFFERENT received bit, coding-gated [C]
`80140922` (TSK_02 handler) mode-muxes on `d000a454`:
- **GRA (`a454==1`)**: `d000a35c = d000a7ef` (GRA hold value).
- **ACC (`a454==2`)** (`80140922:96-101`):
  `bVar13 = 0; if (d0000195 & 0x10) bVar13 = PTR_DAT_80104094[0x13] != 0; d000a35c = bVar13;`
  where `PTR_DAT_80104094 = *(a9+0xc30)` = cal object **#780 @0x803dba70**, and **`[0x13] = 0x01` on this
  image** (Anhalten coding-enabled). So **`TSK_Anhalten = d0000195.4` (AND coding const = 1)**.
- **`d0000195.4` is a received bit**: `800b0e94:89-96` (ACC-cluster decoder, sub-frames param `0x29`/`0x2a`)
  sets `d0000195 |= 0x10` iff `d000a59a.0 == 1`, where `d000a59a` is an unpacked ACC-cluster shadow. So the
  chain is **received `a59a.0` → `d0000195.4` → (coding `#780[0x13]`) → `d000a35c` → TSK_Anhalten (12|1)**.
- **`a59a` is an INTERNALLY-ROUTED signal, not the raw ACC_01 wire bit** (traced 2026-07-27): `a59a` =
  byte[2] of a 12-byte block at `d000a598` that the Com signal-routing layer copies in (descriptor
  `@0x800349b4`: `{src-handle 0x800286c6, dest 0xd000a598, len 0x0c}`). The source `0x800286c6` is a handle
  table of **internal PDU/signal IDs in the `0x38x–0x39x` range — NOT CAN IDs (`0x10x`)**. So `a59a.0` is a
  bit of an *internal ACC-subsystem signal* (routed/processed through the signal layer), **not** a direct copy
  of `ACC_01` byte7·bit1. `801434de`/`8008b17c` only clear `a598`; the wire value arrives via this routing copy.
- **RESOLVED — it is a RECEIVED ACC signal, not internally derived [C].** The whole decoded-shadow block
  `d000a590..a5a4` (which contains `a59a`) has **zero app-computed writers** — every byte is populated only by
  the generic Com RX/routing copy. The processor `800b0e94` is dispatched by `800b13ce` over the ACC message
  set (internal signal handles **`0x1c0..0x1c9`**, gated by presence bits `d000a652/a657/a65b` and validity
  `FUN_800981cc(0x1c9)`). So `a59a.0` is a **received ACC-command bit** routed in from the ACC messages — i.e.
  **openpilot, as the ACC command source, CAN drive MED17's `TSK_Anhalten`** (same end capability as Simos:
  openpilot owns the hold). It is NOT computed from ego speed/standstill.
- **[G] the ONLY thing left unpinned** is the exact wire signal/bit that maps to `a59a.0`
  (`ACC_Anhalten` vs `ACC_StartStopp_Info` vs an ACC status bit), because it passes through ≥2 Com handle-remap
  layers (`0x1cx → 0x38x → CAN 0x10x → bit`) that live in **ROM Com-config tables, not in the decompiled code**.
  Resolving it needs the Com signal database (A2L/DAMOS) or a bench bus capture — not further static tracing.
- **Bottom line vs Simos:** both derive `TSK_Anhalten` from a *received* ACC bit (openpilot-controllable), but
  via **different signals, different routing, and different gates** — Simos = raw `ACC_01` byte7·bit1 relay
  gated by runtime engage; MED17 = a routed ACC signal (`a59a.0`) gated by a coding constant. Same capability,
  not the same bit — bit-exact equivalence must be confirmed on a bus capture.

**Net Q1:** both ultimately relay a *received* stop bit, but via **different signals and different gates** —
Simos = ACC_01 byte7·bit1 gated by runtime engage (`b28e∈{1,5}`, `a5a8`, `a757`, `ad0f`); MED17 = a decoded
ACC-cluster bit (`a59a.0`→`d0000195.4`) gated by a **coding constant** (cal#780[0x13]) + `a454==2`.

## Low-speed barriers per ECU, and what "L2 monitor = 0" removes

| barrier | Simos8.5 | removed by L2→0? | MED17 | removed by L2→0? |
|---|---|---|---|---|
| EGAS-L2 min-speed monitor | `C_VS_MIN_CRU_MON`=15 km/h @0x800794ef/f2 | **yes** (that's the edit) | `0x80389809`=15 km/h (+L1 family) | **yes** |
| low-speed creep/permission state | Simos routes hold/decel through the CRUC state machine (`8013ef46`/`8013e8aa`) with several sub-15 permission/sub-state flags (2.34 km/h cal, a `1000`≈7.81 km/h launch latch `d000118a`, a `d0007e84` hysteresis) | partial — these are permission inputs, not a single removable floor | decel/hold path is **cal-map driven, no CRUC creep state machine, no hardcoded speed literal** | different mechanism |
| creep hysteresis cals | ~7.8 km/h @0x800439f8/fa | no (separate cal edit) | none identified as a hard gate | n/a |
| regulating gate | `b28e∈{1,5}` | no (runtime) | `a361∈{1,5}` | no (runtime) |
| Anhalten enable | runtime `a5a8`(=0 cal-fixed)/`a757`/`ad0f` | no | coding `cal#780[0x13]` (=1) | no |

## Q2 — with the L2 monitor zeroed, do both send EXACTLY the same low-speed signals incl. Anhalten?

**NO. [C/I]** Two independent reasons they diverge:

1. **Different low-speed mechanism (not a single removable floor).** Simos gates hold/decel behind the CRUC
   state machine (`STATE_CRU_CTL∈{1,5}`) fed by several sub-15 permission/creep flags (2.34 km/h cal → `d0001171`;
   a `1000`≈7.81 km/h launch latch → `d000118a`; a `d0007e84` hysteresis → `uRamc0001118`). MED17's hold/decel
   path is **cal-map driven with no such CRUC creep state machine and no hardcoded speed literal**. So the two
   diverge in low-speed behaviour by construction, and zeroing the L2 monitor does not make them equivalent.
   *(Correction: an earlier version claimed the `1000` literal is a "hardcoded barrier that truncates Simos below
   7.81 km/h, firmware-patch-only"; that overstated it — see acc_flow.md/RESULTS.md 2026-07-27. The literal is
   one permission input to the CRUC state, not a direct cutoff; whether Simos brakes to true 0 is decided by the
   CRUC state machine as a whole, which is untraced.)* **[C mechanism differs / G on exact Simos engaged-to-0]**

2. **The Anhalten signal itself is derived differently.** Simos = direct pass-through of `ACC_01.ACC_Anhalten`
   (byte7·bit1); MED17 = a *different* received ACC-cluster bit (`a59a.0`→`d0000195.4`) AND a coding constant.
   For the same on-wire ACC_01 input the two will not necessarily assert `TSK_Anhalten` on the same condition or
   at the same instant — different source bit, different gate. **[C mechanism / G on exact a59a.0 identity]**

**So even with identical hardware, identical ACC_01 input, and both L2 monitors = 0, the two ECUs will NOT emit
byte-identical low-speed TSK_02.** The robust reason is the **different `TSK_Anhalten` source + gate** (Simos =
raw `ACC_01` byte7·bit1 relay gated by `STATE_CRU_CTL∈{1,5}`; MED17 = routed signal `a59a.0` gated by coding).
Their low-speed *decel* behaviour also diverges by construction (Simos = CRUC creep state machine; MED17 =
cal-map to 0). Whether Simos actually reaches true standstill is decided by its CRUC state machine as a whole
(untraced) — it is NOT settled by one hardcoded literal, so no single Simos code patch guarantees convergence.

## To make them match (if that's the goal)
- MED17: zero the #208 L2 permit floor `0x80389809`=15 **and** its CLEAR edge `0x8038980e`=7 (both →0; see
  `maps/l2_monitors.md`). No code patch needed (cal-map driven). No L1 cell needs to move with it (the L1/L2
  "move together" idea was refuted 2026-07-27). Confirm `a59a.0` is the intended stop bit and `cal#780[0x13]` stays 1.
- Simos: zero `C_VS_MIN_CRU_MON`; the sub-15 CRUC creep/permission flags (2.34 km/h cal, the `1000` launch
  latch, the `d0007e84` hysteresis) feed the state machine rather than acting as a single removable floor, so
  matching Simos's engaged-to-0 behaviour requires understanding the CRUC state machine (`8013e8aa`/`8013e47c`),
  not just patching the `1000` literal. **Untraced — do not assume a one-literal fix.**
- Residual (dominant): the `TSK_Anhalten` *source signal* differs (byte7·bit1 relay vs `a59a.0`), so bit-exact
  equivalence of the hold bit is not guaranteed regardless — verify on a bus capture.

## Key addresses
- Simos: `801383e8` (ACC_01 decode), `8013ef46` (relay + `STATE_CRU_CTL∈{1,5}` gate; `1000` launch-latch literal), `80137a00` (TSK_02 packer),
  `C_VS_MIN_CRU_MON` 0x800794ef/f2, creep 0x800439f8/fa.
- MED17: `80140922` (TSK_02 handler, a35c @:101), `800b0e94` (ACC-cluster decode, `d0000195.4 ← a59a.0` @:89-96),
  cal#780 `0x803dba70[0x13]`=1 (Anhalten coding), L2 floor `0x80389809`=15 km/h. a9 = cal-object table 0x80103464.
