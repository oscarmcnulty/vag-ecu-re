# ACC radar — diagnostic access model & why it can't yield live objects

B8 Q5 factory ACC radar: **J428, 8R0907561A, "ACC3"**, Bosch RB8‑658 (HW serial
`RB8-65826.06.1303030457`), SW `0100`, HW `H11`. Reached as **VW TP2.0 logical address
`0x0B`** (VCDS "address 13"), KWP2000‑over‑TP2.0, directly on panda **bus 2** (the extended /
ADAS CAN where stock `ACC_01` is received). Transport recipe is in `../README.md`.

This document records the **complete, bus‑observable access surface** (enumerated 2026‑10,
Linux Openport, read‑only) and the conclusion that **the diagnostic interface cannot expose
live radar objects in any reachable state**.

## Sessions — `StartDiagnosticSession 0x10` (full 0x00–0xFF sweep)
`op_acc_sessions.py`, `op_acc_access.py`.

| Session | Response | Meaning |
|---|---|---|
| `0x89` application | `50 89` POSITIVE | the only openly usable session |
| `0x86` coding | `7F 10 33` | exists, **SecurityAccess‑gated** |
| `0x85` programming | `7F 10 22` | exists, conditionsNotCorrect (precondition‑gated; may also reflect moving vehicle) |
| everything else | `7F 10 12` | **not implemented** |

There is **no engineering/measurement session** (`0x83` → NRC `0x12`). Default and `0x89`
return identical measuring blocks.

## Security — `SecurityAccess 0x27`
Only **level `0x03`** exists (all others NRC `0x12`). `27 03` returns a live non‑zero seed
(e.g. `10 01 C3 64`), offered even in the default session (only the key send is gated). Level
`0x03`→`0x04` unlocks the **coding** session and is the likely precondition for **programming**.
Coding/programming are write‑side (config/flash), not live reads. To crack it without firmware:
sniff a real VCDS/ODIS coding/adaptation on address 13 (`op_sniff.py`) to capture `27 03 seed →
27 04 key` pairs; older VAG SA is simple (cracked ESP8/EPS/TCU this way) or matches an SA2
bytecode in ODIS‑E AU48X.

## Readable data — `ReadDataByIdentifier 0x22` sweep (`op_acc_did.py`)
Swept 0x02xx / 0xF1xx / 0x10xx–0x12xx / 0xF4xx / 0xF8xx / 0xFDxx–0xFFxx (2560 DIDs).
**Only 17 DIDs respond, all `0xF1xx` identification** (part/HW/SW/component/serial/session/
prog‑status). Everything else `NEG 0x31` (requestOutOfRange, 2456×). The VW `0x02xx`
"measurement" band is empty. **No hidden readable data DIDs.** (Channel drops every few hundred
requests — flood protection / moving‑vehicle; the tool auto‑reconnects.)

So the entire readable diagnostic surface is: ident DIDs (`22 F1xx`) + measuring blocks (`21`)
+ DTCs (`18`).

## Measuring blocks (`21 NN`) — live capture (`op_acc_live.py`)
Decoded via VAG self‑describing formula bytes (see `../README.md`). Blocks with data:
voltages, internal temperature, radar azimuth/alignment angles, counters, and two "raw" blocks
48 (80 B) / 49 (28 B).

**Live‑capture result (stationary with a moving target, AND while driving behind a real car):**
- Object slots (blocks 1 & 14) stay `0xFFFF` (no target) the entire time.
- Block 48 is byte‑for‑byte constant; block 49 is constant except a trailing temperature/counter
  byte. All other blocks are housekeeping (V / temp / angles), unchanged by the scene.

## Conclusion — proven from every angle
Holding **any** diagnostic session suppresses the radar's detection/tracking output:
- Standstill diag → radar runs no detection pipeline (housekeeping only).
- Driving diag behind a real lead → object blocks still `0xFFFF`.
- VCDS independently: **stock ACC will not engage while a VCDS session is open.**

The radar only populates objects when it is the **engaged ACC controller**, which is mutually
exclusive with holding its diagnostic channel. No session, vehicle state, or measuring block
exposes raw targets. **The diagnostic approach is exhausted** for live radar data; the remaining
paths are the radar's internal object bus at the connector, a donor radar, or firmware RE.

## Scripts (`../scripts/`, Linux Openport, `/usr/local/lib/j2534.so`, read‑only)
- `op_acc_sessions.py` — session acceptance + per‑session measuring‑block sweep/diff
- `op_acc_access.py` — full `0x10` session sweep + `0x27` SecurityAccess seed enumeration
- `op_acc_did.py` — resilient `0x22` DID sweep (auto‑reconnect)
- `op_acc_live.py` — live per‑byte variance capture of measuring blocks
