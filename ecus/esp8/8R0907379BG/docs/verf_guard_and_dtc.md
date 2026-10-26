# ESP_05 `verf` guard + DTC event machine + injection safe-envelope

ESP8 8R0907379BG (ARM BE32, TMS470). Traced from the ESP_05 packer `esp_msg_pack_525c`
(0x525c) back through the COM compose/route layer. Companion docs: `ECD_path.md`,
`epb_dynamic_braking.md`, `com_routing_decoded.md`, `route_anb_analysis.md`.

Context for the openpilot integration: the secondary panda (SAFETY_VW_EPB_RELAY) rewrites
EPB_01 (decel inject) and — in the disabled clamp path — ESP_05 `ESP_Anforderung_EPB`. A
"bare" value-2 (close) clamp latched `ESP_Verzoeg_EPB_verf` (verf) to 0 and killed sub-15 km/h
decel availability. This doc records why, and the envelope to avoid it.

## No commandable hydraulic standstill Auto-Hold (AVH) in this variant

- The only works-to-0 hydraulic path (ANB / ECD mode-4) is **reactive** to measured wheel
  decel and **releases the instant decel < ~1.12 m/s²** (arm estimator `0x4066e0`, threshold
  `0x461`) — i.e. it lets go at v=0.
- Comfort/ECD decel (mode-2) is hard-gated **off below 15 km/h** (`ecd_speed_gate` 0x844fc,
  cmp #0x78). The apply/hold/release sequencer `ecd_press_stage_state` (0x6a35c) is only
  reachable inside that speed-gated pipeline.
- The "type-3 hold" (`decel_hold_escalation_mgr` 0x431cc, state byte `0x405abb`, entered on
  winning-source status bit 0x4) is the **steady phase** of whichever decel source wins — a
  shaper, not a v=0 latch.
- `ESP_Autohold_aktiv` (ESP_05 bit56) is therefore a **status mirror** of the transient
  hold / EPB handoff, not a hold you can command from CAN.
- **Standstill hold is the EPB static clamp by design** (see `ecus/epb` RE findings).

## `verf` compose — PROVEN guard condition

`esp_msg_pack_525c` (0x525c) emits the real EPB-block values **only if ALL of**:

- group-state byte `0x406d2a`: **bit7 clear** (not "signal invalid") AND **bit1 clear** (not "error");
- global ESP comm-status word `0x40800a`: bits **{4,6,14,15}** all clear (mask 0x4050 + sign bit).
  Written by `com_group_commit` (0x827ac / 0xa2aac); read by every packer;
- the 4 per-signal DTC/fault bytes `0x404344/46/48/4a` (EPB block of the fault array at
  `0x404084`) **all zero** (DTC-driven; `0x404346` writer = DTC setter `FUN_000cc984`).

Otherwise `verf` (and `ESP_Verz_EPB_aktiv` bit58) are forced to **default 0**. So **`verf` is a
"system-healthy AND no relevant DTC" availability flag**, not an EPB-status coupling. This matches
the adversarial log re-review: once the fault clears, `verf=1` coexists with EPB closed, and `verf`
is not a monotonic latch (it resets to 1 at every ABS boot and has read healthy on every drive
since the clamp was disabled).

**`verf` VALUE source** (when the guard passes) = booleans `0x405e70/71/72/73` + decel value
`0x405e74`, routed from `esp05_status_src` (0x405f68) via `esp05_status_route_a6c8` (0xa6c8) out
of the **runtime COM object table**. The upstream app producer (what sets `verf=1` when the EPB
decel channel is truly available), the code that sets `ESP_Anforderung_EPB=2`, and the EPB_01
handshake are all behind the **object-table wall** (table base `*0x4069b4` = `0x40a1a8`, reads as
zero in the static image). **CORRECTED:** the ~5.8 s standstill-release timer **IS an ABS/ESP counter**
(a standstill-anchored hold-duration limiter on the EPB-Verzoeg path) — proven from CAN outputs in
`standstill_release_timer.md`; the "not an ABS counter / likely EPB-module or ACC interlock" guess here
is overturned. Only the exact RAM address/threshold stays behind the COM/dispatch wall.

**Single remaining static-analysis unlock = a bench RAM read of `0x404084+` and `0x406000–0x40a000`**
(materialized fault array + COM object table) while toggling inputs. Static analysis is exhausted.

## DTC event machine — PROVEN

`diag_dtc_event_report` = `FUN_0008473e(event_id, status)` writes the per-event current status as a
byte at **`0x404084 + event_id*2`** (status=1 ⇒ currently FAILED). Every ESP_05 guard "fault byte"
is thus `event_id*2` off `0x404084`. The four validity blocks in 0x525c map to these event sets
(proven by offset → `event*2` arithmetic):

| ESP_05 block | state byte | events | status bytes |
|---|---|---|---|
| **verf + `Verz_EPB_aktiv`** (block 0x543c) | `0x406d2a` | **0x160–0x163** | `0x404344/46/48/4a` |
| Autohold / `Status_Bremsdruck` / `Anforderung_EPB` byte7 (block 0x57c0) | `0x406d32` | 0xb5–0xb8 | `0x4041ee+` |
| base ESP_05 (block) | `0x406d52` | 0xd5–0xd8 | — |
| sum/counter block | `0x406d26` | 0x220–0x223 | — |

So **`verf=0` IFF** any of events 0x160–0x163 failed, OR `0x40800a` bits {4,6,14,15} set, OR
`0x406d2a` bit1/7 set.

**Not statically resolvable:** the per-event evaluator code + human DTC code for 0x160–0x163 (and
0xb5–0xb8). They are raised by table/loop monitors (bulk reporter `FUN_0003b1d8` at table 0xbc600)
plus boot-installed COM-Rx-E2E, with object-table-routed inputs. The DTC-code tables 0xb4b6c /
0xb3750 do not decode to clean VW 3-byte DTCs statically (consistent with the Simos8.5 DTC finding).
Confirming which input each of 0x160–0x163 monitors needs the bench RAM read above. The `event*2`
indexing itself is solid and bench-checkable.

## Trigger table — what our injection can trip

| # | Trigger | Gates | Exact limit | Status |
|---|---|---|---|---|
| **T1** | **EPB-handoff / EPB_01 consistency** (RANK #1 — what value-2 tripped) | **verf block 0x160–0x163** | `ESP_Anforderung_EPB=2` asserted while the ABS hold state is not legitimately entered (type-3 hold `0x405abb`≠3, or v≠0, or EPB_01 feedback inconsistent) → EPB-plausi DTC → verf=0 | inferred-strong; exact per-event threshold = bench |
| T2 | decel request-vs-measured deviation (`FUN_0008cce4`, events 0x88/0x12, **not** verf block) | adjacent | fails if \|estimated(struct `0x408848`+0x2a) − reference(+0x26)\| ≥ reference·0x333>>12 (**~20%**); precond: 4 wheel decels `0x400d96/0x40197e/0x401f72/0x40138a` all >0x2e, `0x4066e0`<0x360 | PROVEN |
| T3 | decel staleness (`decel_mode_state_set` 0x8c1e8) | ecd_mode→fault | ecd_mode→4 after **>39 stale ticks** (cnt `DAT_8c360[0xe]`; thr 0x310, −0x83 hyst) | PROVEN |
| T4 | ANB arm gates (`anb_decel_request_build` 0x4bf3c) | ANB avail | quality `0x4055b4`>12, freshness `0x4055e4`<55, substate `0x405abe`∈{0,4}, master `0x405cac`==0x10, arm mag `0x4066e0`≥0x461 (≈1.12 m/s², wheel-derived → can't synthesize) | PROVEN |
| T5 | 4-wheel plausibility (0x3bf58) | speed | internal-only unless we spoof wheel-speed (we don't) | PROVEN |
| T6 | global comm / NM `0x40800a` bits {4,6,14,15} (writers 0x827ac/0xa2aac) | **all** ESP_05 signals | keep ESP-CAN awake (NM container 0x40c + NM ≥5 Hz) or all ESP_05 signals default (if only verf drops it is T1, not T6) | PROVEN |
| T7 | E2E/counter/checksum on rewritten ABS-consumed frames (`e2e_rx_validate_846x` 0x3714c) | Rx faults | perfect rolling counter + VW MLB XOR checksum on every rewrite; never stale/dup | inferred |

## Safe envelope to keep `verf=1`

1. **Do not command `ESP_Anforderung_EPB=2` until a legitimate standstill-hold** (v=0, type-3 hold)
   with consistent EPB_01 feedback — never while moving, never before the hold state is entered.
2. Keep decel requests **within ~20% of achievable**, ramp-limited (never step).
3. **Refresh every cycle** (<39 stale ticks, quality >12, freshness <55).
4. **Perfect E2E** (rolling counter + VW MLB XOR checksum) on every rewritten frame; no dup/stale.
5. Keep the ESP-CAN awake (NM ≥5 Hz).
6. Do not spoof wheel-speed.

Ranking of the value-2 culprit: **T1 > T7 > T6 > T2/T3**. The value-2 failure was a **sequencing**
problem (clamp asserted "bare," outside the legitimate handoff state), not an inherent limit on
clamping. Re-enabling the clamp is viable within this envelope; pinning the exact T1 threshold is a
bench RAM read of `0x404084+` while toggling inputs.

Architectural note (from the EPB side, `ecus/epb` RE §11): `ESP_Anforderung_EPB` is the ABS's **own**
broadcast signal. Spoofing only the EPB-bound (bus2) copy leaves the ABS still broadcasting `anf=0`
while the EPB sees `anf=2` → the ESP↔EPB consistency check fails and the ABS sets `verf=0`. The
legitimate ACC EPB-close request is `ACC_Betaetigung_EPB` on **ACC_05** (qualified by `ACC_Status_ACC`,
not by ESP consistency) — so the correct openpilot clamp path is ACC_05, not an ESP_05 spoof.

## verf VALUE source — resolved to one hop from the wall (addresses)

The `esp_msg_pack_525c` (0x525c) literal pool is fully resolved. `verf`'s real value (when the guard
passes) comes from fixed RAM bytes **`0x405e70`** (==1 → verf bool), `0x405e71/72/73` (bools), and
**`0x405e74`** (raw decel byte, scaled `(b·0xe1e − 0x92774) >> 8` → TX staging `0x408a7a`).
`ESP_Anforderung_EPB` source is `0x405e8b`→staging `0x408a8f` or `0x405e8c`→`0x407300` (INFERRED;
needs the ESP_05 bit map to disambiguate). These source bytes have **no static writer** — only the
RAM-dispatched router `esp05_status_route_a6c8` (0xa6c8) writes them, from a boot-built object-table
DEST_PTR (stride-0x18 record, deposited by `com_signal_commit_record` 0x50090, flash descriptor
stream `0xb6a44`, +8 DEST_PTR = zero in static image = the wall). The static angle is **exhausted**
(the `0xa7e14` TLV has zero literal refs and is read only by the boot-installed iterator). Full chain,
the empirical stock handoff template, and the openpilot recipe are in
`autohold_and_standstill_handoff.md`.
