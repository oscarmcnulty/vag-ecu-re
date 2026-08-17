# Funktionsrahmen ↔ binary alignment

Source: `Simos8.5.pdf` — the Continental Funktionsrahmen for project **S859300C**, 13,002 pages —
indexed by `core/pdf/fr_index.py` into `../analysis/fr/{fr_pages.jsonl,fr_labels.tsv}` and searched with
`core/pdf/fr_search.py`.

The FR gives label names, types, units and scaling but **no addresses**. Addresses come from matching to
the binary: descriptor table, axis signatures, consuming function, and tuner-diff anchoring. This file is
the FR-side reference — what a label means and which binary object it turned out to be.

**Naming convention** (Continental, not Bosch-German):

| prefix | meaning |
|---|---|
| `C_*` | calibration constant |
| `KF*`, `IP_*` | Kennfeld / interpolation object (map or curve) |
| `LV_*` | logical / boolean variable |
| `LF_*` | logical field |
| `NC_*`, `AC_*` | configuration / application constant |
| `TQI_*` | indicated torque |
| `VS_*` | vehicle speed |

## Cruise / ACC speed constants

Cruise control is **VHSC** (Vehicle Speed Control): ch.70 (pp.12213–12303 logic), ch.14.16 "Monitoring of
cruise control conditions" (p.2193), ch.48 CAN (p.9089), Audi task `AUDI_GRA_TSK` (pp.10352+). Labels use
the `CRU_` infix.

| constant | FR meaning (verbatim) | type | res | def. p. | binary |
|---|---|---|---|---|---|
| **`C_VS_MIN_CRU`** | "minimal vehicle speed for cruise **activation**" — an activation floor, not a set-speed | u16 | 0.01 km/h (FR); **operative 1/128** | 12415 | **`0x8007a26a` = 3.0 km/h**, read by `cruise_torque_pi_controller` |
| **`C_VS_MIN_CRU_MON`** | "Minimum threshold for vehicle speed control active"; "Derived from level-1 calibration of `C_VS_MIN_CRU_OFF` minus 2 km/h" (p.2351) | u8 | 1 km/h | 2196 | **`0x800794ef` / `0x800794f2` = 15**, read by `acc_status_error_aggregator`; EGAS-L2 twin `0x800456c0` / `0x800456bd` |
| `C_VS_MIN_AC_CTL_CRU` | "Lower limit of vehicle speed for acceleration control" | u16 | 0.01 km/h (FR); operative 1/128 | 12502 | **`0x80079536` = 3.0 km/h** (candidate) |
| `C_VS_MIN_CRU_MPH` | MPH-market variant | u8 | 1 mph | — | not located |

The FR states no numeric value for `C_VS_MIN_CRU` (the level-1 value lives in the dataset/DAMOS), so the
binary's 3.0 km/h is fully FR-consistent. Gate logic is a direct raw compare against the 1/128 km/h ego
signal: `if (ego_speed < C_VS_MIN_CRU) → not active`. The full trace, the operative-versus-FR scale
caveat and the two independent sub-15 km/h mechanisms are in **`low_speed_floors.md`**.

Related setpoint variables: `VS_SP_CRU` (active setpoint), `VS_SP_CRU_DISP` (display), `VS_MAX_CRU`
(max), `STATE_CRU_CTL` (engagement state machine), `CRU_SWI_POS` (stalk).

## ACC deceleration limit and its monitor

The −3.0 m/s² clamp is the FR **`AC_MIN_CRU` / `AC_DCRU_PLAUS`** mechanism (VHSC ch.70, diagnosis
ch.70.6). Two different scales are in play — the functional clamp is a Kennlinie in cal data at
u16 850e-6 m/s² **offset-binary** (−3.0 = `0x7237`), while the L2 plausibility monitor works at 0.001
(−3.0 = −3000). The label-by-label alignment table lives with the mechanism in
**`decel_limit_flow.md` §5**.

## Performance-tuning labels

FR families for the tuning targets; the pinned addresses and what the Stage1/Stage2 tunes actually
change are in `performance_maps.md` and `tune_diff_analysis.md`.

**Torque structure (ceilings — the top tuning targets):** `TQI_MAX` (p.562), `TQI_BAS_MAX` (561),
`TQI_POW_MAX` (563), `TQI_VS_MAX` (565), `TQ_MAX_CLU` (558), `TQ_LIH_MAX` (557);
`LV_TQ_LIM_INTV` (441) is the torque-limit intervention flag. The pedal→torque request map feeds this
structure.

**Limiters:** rev limit `N_MAX_THD` (p.464), `LV_N_MAX` (416); top-speed limiter `V_PVS_MAX` (567),
`VS_MAX` / `LV_VS_MAX` (447).

**Boost / charge pressure:** `VBOOST` (568), `MFP_BOOST` (7117), wastegate `LV_PWM_WG_EXT_ADJ` (423).

**Ignition / knock:** `KNKS`, `N_KNK` (464), knock adaptation `FAC_AD_KNK` (203); the ignition-timing
(Zündwinkel) bank feeds torque.

## Known limitations

- The descriptor→FR join is not complete. Where `tune_diff_analysis.md` marks a row ★ or low ★★, the FR
  entry is a **family**, not a name-matched address.
- `Simos8.5.pdf` must be staged locally to re-index (`core/pdf/fr_index.py`); `files.s4wiki.com` is
  egress-blocked in the sandbox.
