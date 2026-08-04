# Symbol-name audit — why the `llm` names were retired from the canonical store

## What changed
`analysis/symbols_merged.csv` now holds **only confirmed names** (`source ∈ {verified,
re-trace, fr-trace}`, 144 rows). The ~2509 `source=llm` machine-proposed names were moved to
**`analysis/llm_name_hints.csv`** — same columns, explicitly **UNVERIFIED**, and **not applied
by the pipeline** (`ApplySymbols` reads `symbols_merged.csv` only). Nothing is deleted; the
hints remain greppable as starting hypotheses.

## Why (evidence)
A 20-function random audit of `source=llm` rows (each judged against its actual decompiled C):

| verdict | count | meaning |
|---|---|---|
| HIGH (specific & correct) | 3 (15%) | e.g. `clear_bit_in_status`, a real `state_machine_handler` |
| MEDIUM (vague/generic, not wrong) | 13 (65%) | `process_ecu_data`, `task_dispatch_loop` — low information |
| **LOW / WRONG (misleading)** | **4 (20%)** | two `empty_stub`s that actually call functions; two `update_checksum`s that do **no** checksum (buffer alloc/zero) |

A **20% actively-wrong rate** is the problem: a wrong name is worse than `FUN_<addr>` because
it substitutes false confidence for a neutral unknown. This session hit exactly that failure
five times — `handle_uds_command`@`800aa922`, `handle_diagnostic_request`@`800b3e6e`,
`update_ecu_parameter`@`800b3f40`, `process_ecu_data`@`801d8590` are all **GPTA / injection-
timing** code wearing "uds"/"diagnostic" names, and `read_memory_value`@`800a2c54` is a cal
indexer, not a memory read. Trusting those names sent the first dispatch-table trace into the
wrong subsystem; the real UDS table was only found by ignoring names and searching the image
for a behaviourally-confirmed handler pointer (see `uds_dispatch.md`).

"Keep only the HIGH ones" isn't operable: identifying the 15% requires the same per-function
review for all ~2500 rows that the names were meant to save. So the honest default is to treat
the whole `llm` set as untrusted, stop surfacing it in analysis, and let `FUN_<addr>` mean
"unknown" until a name is *earned* by tracing (→ `re-trace`) or matched to the Funktionsrahmen
(→ `fr-trace`).

## How to use the hints
`llm_name_hints.csv` is a **hypothesis pool**, not ground truth. When working a function, you may
grep it for a starting guess — but verify against the code before believing it, and when you
confirm one, promote it into `symbols_merged.csv` with the right `source`
(`verified`/`re-trace`/`fr-trace`) and a provenance note. That is how the canonical store grows.
