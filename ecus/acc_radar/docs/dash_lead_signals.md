# Lead-distance on the CAN bus — ACC_02 dash display, and the unknown messages

Since the radar won't give objects over diagnostics (`diagnostic_access_model.md`), this is the
analysis of what lead/object information the **stock ACC broadcasts on the bus** to drive the
cluster display. Source: old stock‑ACC route `15e6fc3f7f90b0c5/00000051--957a33a9e7` (comma
connect), segments where stock ACC was engaged (3/4/7/9/10). Ground truth for lead distance =
openpilot `modelV2` vision lead (`radarState` is never populated on this VW).

## The dash lead display = ACC_02 (0x30c), bus 2
Active **only when stock ACC is engaged** (TSK_04 status 1). Key signals:
- **`ACC_Relevantes_Objekt`** (bit 46) — lead‑detected flag (the cluster lead‑car icon): `0`
  no target → `1` lead locked.
- **`ACC_Abstandsindex`** (bits 24–33) — the **gap/distance value**, inverse to range (higher =
  closer). Sentinel `1022/1023` = no object.

### Calibration (5 ACC‑engaged segments, 1560 object‑present frames)
Pearson r(idx, dist) = **−0.88**. Best functional form (linear, R²=0.77):

> **dist[m] ≈ 81.7 − 0.0885 × Abstandsindex**

Monotonic, and **tight at close range** (idx 400–800 ≈ 15–42 m holds ±1.5–4 m); far range is
noisier only because the *vision* ground truth degrades past ~60 m. A 2‑segment subset of the
cleanest data gave `dist ≈ 86.5 − 0.098 × idx`, R²=0.90. Practical close‑range model is solid.

### Emission condition — only while stock ACC is ENGAGED
Verified across 7 segments (TSK_04 ACC status vs Abstandsindex realness):

| TSK_04 status | real distance | sentinel | lead present but still sentinel |
|---|---|---|---|
| 0 — off/available | 40 | **4477 (99%)** | **1509** |
| 1 — engaged | **1572 (70%)** | 649 | 73 |
| 2 — engaged+override | 17 | 128 | — |

When stock ACC is not engaged, `Abstandsindex` is the sentinel 99% of the time **even with a
lead directly ahead** (1509 frames). The radar publishes the gap only when it is the regulating
controller.

**Consequence for the openpilot integration:** this channel is readable off the bus only while
the driver has stock ACC engaged, and goes dark the instant openpilot takes over longitudinal
(which disengages stock ACC) — exactly when you'd want it. So `Abstandsindex` is **not** a
usable radar substitute for OP longitudinal; it works only in a "stock ACC engaged, OP observes"
arrangement. Same structural wall as diagnostics: the radar shares lead data only when it is the
engaged controller. Always‑on radar range still needs the internal‑bus tap / donor / firmware.

## openpilot ACC_02 spoof vs stock — field diff
openpilot builds ACC_02 in `opendbc/car/volkswagen/mlbcan.py:create_acc_hud_control`. Decoding
the stock message (1465 engaged frames) against what OP sets:

| Signal | Stock sends | openpilot spoofs | Diff |
|---|---|---|---|
| **ACC_Abstandsindex** | varies 30–1023 (real gap) | `1022/1023` sentinel, hardcoded | ⚠️ cluster gap bar dead under OP (OP *has* a usable dRel it could fill) |
| **ACC_Display_Prio** | `3` | `0` | ⚠️ lowest priority → cluster may suppress ACC display |
| **ACC_Typ_Tachokranz** | `1` | `0` (unset) | ⚠️ wrong speedo‑ring type |
| ACC_Gesetzte_Zeitluecke | `3` (fixed) | `leadDistanceBars` | minor (gap‑bar) |
| ACC_Anzeige_Zeitluecke | mostly `0` | `1` when active | minor |
| Wunschgeschw / Status_Prim_Anz / Relevantes_Objekt / Tachokranz / Status_Anzeige / Akustik | — | — | ✓ equivalent |

None are safety‑relevant (ACC_02 is HUD‑only), but they explain cluster cosmetic glitches under
OP longitudinal; filling `Abstandsindex` from OP's lead and setting `Display_Prio=3` /
`Typ_Tachokranz=1` would make the cluster render correctly.

## Unknown messages (not in `vw_mlb.dbc`) — content & source
Canonical names are **not public** (cross‑referenced all opendbc VW DBCs + web search; only
`0x5a0` matched). The only authoritative source for this car is ODIS‑E's AU48X DB (PBL‑compiled).
Empirical characterization:

| ID | bus | rate | len | content (from data) | likely source |
|---|---|---|---|---|---|
| **0x311** | 2 | 17 Hz | 4 | **vehicle speed** (b0+b2) + counter (b1) + `b3=0x08`; corr(vEgo)=+0.83, corr(leadDist)=+0.04 — **not** object data | gateway→ADAS speed broadcast |
| 0x3e2 | 0 | 10 Hz | 8 | static `04 00…` | chassis/pt status |
| 0x63a | 2 | 1 Hz | 8 | slow housekeeping | front ADAS sensor |
| 0x63c / 0x63d | 2 | 1 Hz | 3 | slow, bytes 1–2 | front ADAS sensor |
| 0x5a0 | 0 | 5 Hz | 5 | byte0 varies | **RLS_01** rain/light sensor (matches MQB/MQBevo) |
| 0x21f / 0x514 / 0x600 | — | rare | — | intermittent, absent in ACC segments | — |

Note: `0x311` was initially mistaken for an object message (byte2 rose with a lead in seg3) —
deeper analysis showed byte2 tracks **speed**, which merely co‑varied with the lead‑follow.

### How to identify a transmitting module (no firmware)
1. **Native bus** — bus 2 = ADAS CAN (radar J428 / front camera / SWA / gateway port); bus 0/1 =
   chassis/powertrain.
2. **Co‑transmission grouping** — one ECU's messages share a rate and boot together.
3. **Diagnostic‑halt test** — session a candidate module over UDS/TP2.0 and watch which
   broadcasts go silent (VAG ECUs stop normal TX during diagnosis, as the radar does). Pins the
   transmitter with just the Openport.
4. **Physical unplug / fuse pull** — definitive.
5. **ODIS gateway installation list** — authoritative transmitter + name.

## Scripts (`../scripts/`)
- `leadcorr.py` — brute‑force field↔lead‑distance correlation
- `refine_fit.py` — pooled Abstandsindex→meters fit (linear/inverse/sqrt/log, binned)
- `dist_cond.py` — ACC‑status vs Abstandsindex emission‑condition table
- `acc02_diff.py` — stock ACC_02 field decode vs openpilot's spoof
- `characterize.py` — unknown‑message native bus / rate / dynamics / correlations
- `dl_route.py` — comma‑connect rlog downloader (resilient, resumable)
