# A2L coverage of the 8R0907551F Stage1/Stage2 tune — and how the diffs map to FR

Input: `ce04091d-8R0907551F.ols` (WinOLS 5.0 project, 6,614,687 bytes) carrying **three**
2 MB TC1796 images — *Original*, *Stage 1*, *Stage 2* of an Audi Q5 3.0 TFSI `8R0907551F`
(`S8500L2000000`). This is the same tune set the earlier `tune_diff_analysis.md` describes;
this file is the coverage-audit companion, driven from the OLS directly.

## 1. Extracting the three bins from the `.ols`

The three raw images are stored back-to-back at the tail of the project file:

| field | value |
|---|---|
| bin start (file offset) | **`0x4ee9f`** |
| image size | `0x200000` (2 MB) each, `3 × 2 MB` = tail of file exactly |
| stored order (from the OLS header string) | **`Original, Stage 2, Stage 1`** |

The start offset is pinned by structure, not guesswork: at `0x4ee9f` the boot region
`0x0–0x20000` is 100 % blank (an OBD read), code begins exactly at image `0x20000`
(`ecu.conf` `CODE_RANGES` start `0x80020000`), and the part-number string `8R0907551F`
lands at image `0x40060` (cal region start `0x40000`).

> **Ordering caveat (important).** The OLS header lists the images as
> `"2 (Original, Stage 2: NOCS, Stage 1: NOCS)"` — i.e. the **middle** stored image is
> **Stage 2**, the **last** is **Stage 1**. Verified against the top-speed limiter
> `0x43c2c` (documented 159 → 234 → 250 km/h for Orig → S1 → S2): stored copy 1 = 250 km/h
> (Stage 2), copy 2 = 234 km/h (Stage 1). Extract with the labels swapped or every
> stage-direction claim inverts.

Bins are firmware-derived and are **not** committed (kept in the scratchpad only), per the
repo's hard rule.

## 2. The diff (`core/diff/diff3.py`)

```
diff3.py 8R0907551F_Original.bin 8R0907551F_Stage1.bin 8R0907551F_Stage2.bin \
    --region 0x40000:0x80000 --gap 16
```

→ **50 changed blocks, 4392 bytes, all inside the calibration window `0x40940–0x7a393`;
zero code bytes differ.** Identical block set to the earlier analysis. Stage split of the
50 blocks: `S1=S2` 30 · `S1&S2` 11 · `S2-only` 8 · `S1-only` 1.

## 3. Coverage verdict

| | before | after |
|---|---|---|
| changed blocks covered by an A2L object | **32 / 50** | **50 / 50** |
| uncovered | **18** | 0 |

**Answer to "does the current A2L cover all changed cal values?" — No, it covered 32 of 50.**
The 18 uncovered blocks have now been added to `simos85.a2l` (see §4). The full per-block
map is `maps/tune_coverage.csv` (vaddr, len, stage, new?, A2L object).

The 32 already-covered blocks are the headline tuning targets already in the A2L: the AT/MT/eco
torque ceilings (`ip_tq_pow_max_*`), the `ip_tqi_ref` 16×12 torque model, HPFP rail pressure
(`ip_fup_sp_hom`), rev limiter (`Max_RPM_for_*`), top-speed limiter (`speed_limiter_setpoint_table_43c2c`),
the L2 torque monitor (`torque_monitor_permissible_dev_40940`), the `ABC` load window
(`monitor_load_window_4eb6c`), and the first ignition bank (`ip_iga_spark_correction_bank`).

## 4. The 18 newly-added objects and their FR mapping

Names are grounded in, in order: the diff (address/length/values, hard), `maps/map_consumers.csv`
(committed Ghidra trace: consumer fn + bound axes), and the FR families in `tune_diff_analysis.md`
/ `fr_alignment.md`. **The Funktionsrahmen carries no addresses**, so an FR *characteristic
token* is never pinned to an address here — names stay address-anchored and each A2L comment
states its confidence, exactly as the pre-existing unattributed objects do
(`tq_factor_block_55e64_unattributed`, `block_6d3ac_consumer_unresolved`, …).

Confidence key: **MED** = a map-call resolves *into* the block (`map_consumers.csv`), FR family
from the verified consumer → `source=re-trace`. **LOW** = no map-call resolved; name is a
diff-grounded hypothesis → `source=llm`.

| vaddr | new A2L object | conf | FR family / role | change |
|---|---|---|---|---|
| `0x40956` | `torque_monitor_config_flags_40956` | LOW | Momentenüberwachung (EGAS L2) config flags, next to `0x40940` | S2 zeros first 16 B |
| `0x4119e` | `component_monitor_thresh_4119e` | LOW | EGTR/BTS component-monitor thresholds (FUN_801564d0) | S1=S2 +~3 % |
| `0x4449e` | `rev_limiter_curve_bank_4449e` | **MED** | `N_MAX` rev-limiter curve bank (FUN_8017a1e0, verified) | S1&S2 raise limiter |
| `0x449fc` | `thermal_prot_tq_limiter_params_449fc` | LOW | per-bank thermal-protection torque limiter (FUN_8018e814) | S1&S2 +~2 % |
| `0x48c18` | `torque_correction_struct_48c18` | LOW | `IP_EFF_TQI_COR_CUS` / `EFF_*` correction structure (FUN_800faef8) | S1=S2 lift corner/top |
| `0x48dde` | `charge_torque_ref_curve_48dde` | **MED** | 1-D charge↔torque reference curve vs N (FUN_8014fe88, verified) | S1&S2 raised |
| `0x48e2c` | `torque_bank_axis_48e2c` | **MED** | two-plateau axis in the EFF/torque bank (FUN_800faef8 / FUN_8013273c) | S1&S2 raise low plateau |
| `0x49114` | `torque_model_ceiling_49114` | **MED** | `TQI_MAX`-type ceiling (FUN_800faef8 kf_interp, verified) | S1=S2 +5.0 % |
| `0x4925c` | `rpm_fill_curve_4925c` | **MED** | rpm fill/correction curve (FUN_8014fe88, verified) | S1=S2 +~30 % |
| `0x53235` | `charge_boost_gate_bank0_53235` | LOW | per-bank charge/boost gate curve, bank[0] | S1&S2 shift up |
| `0x532f5` | `charge_boost_gate_bank1_532f5` | LOW | charge/boost gate, bank[1] (twin) | S1=S2 shift up |
| `0x5774e` | `tq_upper_limit_companion_5774e` | LOW | companion clamp to `tq_upper_limit_57620` | S1=S2 922→891 |
| `0x6567a` | `limiter_monitor_table_6567a` | LOW | structured limiter/monitor table | S2 zeros whole table |
| `0x6d3c4` | `block_6d3c4_factor_cont` | LOW | continuation of the unity=1024 MFF factor block `0x6d3ac` | S2 reshape |
| `0x74084` | `ign_charge_time_corr_74084` | LOW | ignition / charge-time correction (3-col) | S1=S2 +~2 raw |
| `0x7870e` | `spark_correction_bank2_7870e` | **MED** | 2nd IGA/Zündwinkel map, sibling of `0x7865b` | S1=S2 +1 (more advance) |
| `0x787c2` | `spark_correction_bank3_787c2` | **MED** | 3rd IGA map, sibling of `0x7865b` | S1=S2 +1 (more advance) |
| `0x7a38c` | `acc_accel_profile_curve_7a38c` | LOW | ACC/cruise accel-profile curve | S1&S2 raise profile |

Symbol names for these 18 addresses are added to `analysis/symbols_merged.csv`
(`type=DATA`, `source=re-trace` for MED / `llm` for LOW).

## 5. Funktionsrahmen PDF — not re-indexed this session

The task asked to download `https://files.s4wiki.com/docs/Simos8.5.pdf` and re-index it with
`core/pdf/fr_index.py`. **Both egress routes are blocked for this session:** the agent
egress proxy denies the CONNECT to `files.s4wiki.com` by org policy (`403`), and `WebFetch`
reaches the origin but it returns `403` (hotlink protection). Additionally `pdftotext`
(poppler-utils) — which `fr_index.py` shells out to — is not installed here.

The FR mapping above therefore rests on the FR knowledge already committed to the repo
(`fr_alignment.md`, `tune_diff_analysis.md`, and the FR-derived names already in the A2L),
which was itself built from this exact document (project S859300C, 13,002 pp). To refresh it
against the PDF directly: place `Simos8.5.pdf` locally, install poppler-utils, then
`core/pdf/fr_index.py Simos8.5.pdf ecus/simos85/analysis/fr` and re-check the MED/LOW FR
families with `core/pdf/fr_search.py`.
