# Simos 8.5 — findings guide

`RESULTS.md` is the **append-only lab log** of this reverse-engineering effort: 66 dated
`UPDATE` entries, warts and retractions left in place so the reasoning trail is auditable.
That makes it authoritative but not approachable. This file is the front door: it says what
is *currently* believed, what has been *retracted*, and where the settled write-ups live.

> **How to read the log:** later entries supersede earlier ones. When an `UPDATE` is
> retracted, the retraction is a *later* entry that names it — the original is kept for the
> trail, not because it is still true. Always trust the highest-numbered entry on a topic.

## Current state as of UPDATE 66 (2026-07-15)

The settled conclusions live in these curated docs (kept current), not in the raw log:

| Doc | Topic |
|---|---|
| `acc_flow.md` | ACC ingress → engine → ESP data flow, end to end (corrected per UPDATE 65) |
| `cruc_state_machine.md` | `STATE_CRU_CTL` end-to-end; settles "does the engine stay engaged to 0 km/h?" (yes) |
| `decel_limit_flow.md` | the −3.0 m/s² decel clamp: on-car evidence + the editable cal lever |
| `can_signal_map.md` | CAN/Com signal ↔ handler map (the wire-level bindings) |
| `fr_alignment.md` | Funktionsrahmen ↔ binary alignment for the decel/cruise tables |
| `cruise_control_flow.md` | cruise/ACC-engage path and the sub-15 km/h speed floors |
| `dispatch_tables.md`, `performance_maps.md`, `tune_diff_analysis.md` | Com dispatch, perf maps, tuner-diff attribution |

The openpilot-relevant bottom line the log reaches (see UPDATE 66 for the synthesis): the
engine is a **follower** in both the compiled-out F2S soft-stop and the cal-gated ACC_05/EPB
hold architectures; factory stop-and-go is not present and cannot be cal-flashed into this
image. The editable levers that *do* exist (the −3.0 decel cal, the layered sub-15 km/h
speed floors) are documented with addresses in `decel_limit_flow.md` and `cruise_control_flow.md`.

## Retraction map (do not cite these as current)

| Retracted / corrected | By | What changed |
|---|---|---|
| UPDATES 43–49 (the −3.0 "wrong curve") | CORRECTION 2026-07-12 → UPDATE 57 | the real −3.0 clamp is calibration Kennfeld data (offset-binary, −3.0 = 0x7237), not the 0x8004dd90 curve |
| UPDATE 46 "complete scan" | UPDATE 48 | the scan ran over an incomplete corpus (27 KB of ACC code was RAM-dispatch-hidden) |
| UPDATE 54 "aggregator path is dead" | UPDATE 55 | the aggregator *does* drive status-3, via d744 → d8e2.bit2 |
| UPDATE 56 "−3.0 not a raisable cal" | UPDATE 57 | it is a raisable cal after all |
| UPDATE 61 "TSK_Anhalten is constant 0" | UPDATE 63 | it is a live, gated pass-through of the incoming ACC_Anhalten CAN bit |
| `acc_flow §1` RX-decoder labels | UPDATE 65 | all three ingress decoders were mislabeled; 80106db8 = ESP_05 (0x106), an ESP→engine feedback frame |
| "C_VS_MIN_CRU_MON is status-only" | CORRECTION 2026-07-15 | it *does* latch a key-cycle fault below 15 km/h (on-car ground truth) |
| UPDATE 66 "the `1000` literal / 7.84–7.60 km/h creep is the dominant sub-15 barrier, firmware-patch-only" | CORRECTION 2026-07-27 (`cruc_state_machine.md`) | overstated — those thresholds feed CRUC sub-state flags, not a hard floor; there is no single "dominant barrier" cell/literal, and `d0007e84` isn't ego speed |
| open item "engaged to 0 km/h? (MEDIUM)" | RESOLVED 2026-07-27 (`cruc_state_machine.md`) | `STATE_CRU_CTL` has no ego-speed transition out of {1,5}; it stays regulating to standstill → hold/decel relay live to 0 |

## Provenance

Function names in `../analysis/symbols_merged.csv` carry a `source` column — most are
`llm` (hypotheses); only `verified` / `re-trace` / `fr-trace` are confirmed. Cal objects
and their provenance live in the canonical A2L (`simos85.a2l`). Addresses cited in the log
are against `8R0907551F_Original.bin` (load base `0x80000000`).

> A hand-written executive summary by the RE author would be the ideal complement to this
> index; this file deliberately only restates the log's own current/retracted verdicts and
> points at the curated docs, rather than re-deriving any technical claim.
