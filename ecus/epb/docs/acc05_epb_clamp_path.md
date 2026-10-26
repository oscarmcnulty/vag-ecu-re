# ACC_05 → EPB external-clamp control path (openpilot standstill hold)

EPB 8K0907801N (HCS12X). How to command the EPB to clamp over CAN via **ACC_05**, the exact
signal, its value semantics, and the sequence for holding a stop past the ESP hydraulic timeout.
Everything below is traced from the firmware image (functions named in `analysis/symbols.csv`,
decode diagram in `swc_dispatch_resolved.md`); items marked **[bench]** are the few hops that
static analysis can't close. Companion: `RE_findings.md` §11/§24/§25,
`../../esp8/8R0907379BG/docs/verf_guard_and_dtc.md`, `standstill_release_timer.md`.

## TL;DR — answers to the three questions

1. **What to send:** `ACC_05` — **CAN ID `0x10D`, 8 bytes**. The clamp request is **byte 7, bit 4
   (mask `0x10`)** = `ACC_Betaetigung_EPB`. Set it to **1** to request clamp.
2. **Value semantics:** it is a **sustained ENABLE level**, *not* a momentary switch and *not* an
   enable/disable pair sent as separate messages. Hold `bit4 = 1` → clamp held; set `bit4 = 0`
   → request drops to idle and the arbiter releases. The ACC path has **no distinct "open"
   command** (unlike ESP, which has `2=close / 1=open`): on the ACC path you release by
   *deasserting the same bit*.
3. **For extended standstill:** assert `ACC_Betaetigung_EPB = 1` and **keep asserting it for the
   whole stop** — through and past the ~5.8 s ESP hydraulic timeout — then deassert (→ release)
   only when resuming. The ~5.8 s limit is on the ESP hydraulic (EPB-Verzoeg) path, not on this
   EPB clamp level; no independent release timeout on the EPB external-clamp level was found in
   the image **[bench: confirm a sustained request holds indefinitely]**.

## The message — verified byte layout (`acc05_epb_decode` 0x7e4c15)

`ACC_05` is RX-subscribed by the EPB (`can_rx_matrix.csv` idx 20: `0x10d`, dlc 8, buf `0x10d6`).
Only **byte 7** carries EPB-relevant bits; the decoder reads `acc05_rxbuf+7` (`0x10dd`):

| byte 7 bits | mask | meaning | where it lands |
|---|---|---|---|
| bit 4 | `0x10` | **`ACC_Betaetigung_EPB`** — the EPB-close request | `acc_epb_req_state`.0 (`0x2806`.0) |
| bits 1–3 | `0x0e` | 3-bit **status/mode field** (graded qualifier, *not* a force value) | `acc_epb_req_state`.1–3 |
| bit 6 | `0x40` | aux flag | `acc_epb_req_state`.4 |

Plus COM E2E on the frame as usual for VW MLB (byte 0 = XOR checksum, byte 1 low nibble =
rolling counter) — the EPB's COM layer requires the frame **fresh with a valid counter +
checksum** or it is ignored. Use the verified ACC_05 XOR seed (see memory `vw-mlb-checksums`,
"ACC_05 vector"); `acc05_epb_decode` sets freshness flags (`0x2805`.0x80 / `0x2807`.1/2) on each
accepted frame.

## Decode → snapshot → getters → mapper → arbiter → motor (the full path)

```
ACC_05 0x10D byte7  ──► acc05_epb_decode (7e4c15)  ─ bit4→state.0, bits1-3→state.1-3
                     ──► acc_epb_req_state (0x2806)
                     ──► rte_input_snapshot_task (788ae7)  ─ copies 0x2806 → snapshot 0x1251
RTE getters (port-invoked):
   rte_get_acc_betaetigung_epb (788ead) = snapshot 0x1251 bit0   (the request)
   rte_get_acc_epb_field       (788eb9) = snapshot 0x1251 bits1-3 (the qualifier)
MAPPER:
   epb_map_acc_req_to_cmd (788b1a):  ACC_Betaetigung_EPB == 1  → internal cmd 6 (CLOSE)
                                     else                      → cmd 0x23 (idle)
      (cmd 6 is the SAME close code the ESP path emits: rte_get_esp_anforderung_epb 788efe,
       2→6 close / 1→5 open / else→3 idle — both sources funnel to one apply path.)
ARBITER (epb_arb_apply_ch0 7ed041 / _ch1 7ed292 / _combined 7ed657, page fb):
   · runs ONLY if coding_ext_clamp_enable (0xfe074.0) is set         ← master coding gate
   · low-speed gate: rte_read_vehicle_speed (79058c) < 0x4b1
   · schedules a decision sub-runnable, reads its latched bit (CB array 0x1fc0+id*4 bit0), then:
        decision bit = 1 → epb_cmd_set_applybits(ctx,'d')  APPLY  → epb_apply_cmd_reg 0x240 bit4/5 SET
        decision bit = 0 → epb_cmd_set_applybits(ctx, 0 )  RELEASE → epb_apply_cmd_reg 0x240 bit4/5 CLEAR
   · clamp-force ramp: ctx->0x31 bits 0x7c, +4/cycle  (⇒ empirical Spannkraft 2→17)
APPLY:
   epb_apply_runnable (7e88c1): enable-getter 78cd37 set → apply-value 78cd33 → epb_apply_cmd_write
   (7e81f6, B=2 close / 1 open) → motor H-bridge.
```

## Why it's a held level, not a one-shot (the crux for the use case)

`epb_cmd_set_applybits(ctx, cmd)` writes a **level** into the command register
(`epb_apply_cmd_reg` 0x240): `cmd='d'` sets the channel apply bit, `cmd=0` clears it. The arbiter
re-decides **every cycle** and calls the **release** form (`cmd=0`) as soon as its decision bit is
0. So at the logic level the clamp follows the request: **assert → clamp, deassert → release.**
The caliper itself is mechanically self-locking, but the firmware will drive it open the moment
the request drops — this is not a latch you can set once and forget.

**[bench] one un-traced hop:** the arbiter is provably level-driven *on the decision bit*; the
decision sub-runnable that *produces* that bit from the getters is scheduled (RAM-dispatched) and
its internal hysteresis/latch was not statically traced. Operationally this doesn't change the
recipe — holding the assertion works under either model — but whether *deasserting ACC alone*
immediately releases (vs. needing an explicit open) is a bench check.

## Prerequisites / gates (all must hold)

1. **Coding gate — TWO dealer-coding bits must both be set:** `coding_ext_clamp_enable`
   (RAM `0xfe074`/alias `0x2074`, bit0) **AND** `coding_ext_clamp_enable2` (`0xfe07c`.0), AND'd in
   `epb_ext_clamp_available` (78c87f) and re-tested in the arbiter (7ed681/7ed8c2). This is the
   **master external-clamp enable and it gates BOTH the ACC and ESP routes** — so ACC_05 is *not*
   a way around a cleared coding bit. (A third related flag `0x2078`.0 = `coding_ext_clamp_feature3`
   gates a separate feature in `epb_ext_clamp_feature3_gate` 7e3809.) These are **derived
   dealer-coding feature flags**: the firmware never writes them (read-only in the image); they
   are produced at boot by the coding interpreter (`coding_variant_interpreter` 79ad05) from the
   compact variant block (`coding_variant_block`, RAM `0x1f4a–0x1f8x`, tested against VW variant
   codes 0x5a/0x33/0x3c/0x64/0xaa) via the coding map `coding_flag_addr_table` (0x7f4840). **Which
   long-coding byte/bit maps to these flags is behind the boot-materialized coding dispatch —
   not statically decodable** (the same wall as the live value). **[bench]** resolve it with a
   UDS 0x22 long-coding read + a variant diff (read coding, toggle a candidate bit, see whether the
   clamp becomes available). If these bits are 0, an ACC_05 request does nothing.
2. **Low-speed gate:** `rte_read_vehicle_speed` (79058c) `< 0x4b1` — the arbiter only runs the
   clamp path below a low-speed threshold (satisfied at standstill). **[bench]** exact km/h scale.
3. **Valid, fresh ACC_05:** correct rolling counter + VW MLB XOR checksum every frame, ≥ the COM
   cycle rate; stale/dup frames are rejected and the request decays.
4. **3-bit status field (byte 7 bits 1–3):** `epb_map_acc_req_to_cmd` keys *only* on `bit4`, so
   the minimal verified trigger is `bit4=1`; the 3-bit field "qualifies" the request in the
   downstream decision runnable. **[bench]** confirm the required field encoding (start with the
   value the stock radar uses when it asserts the request).

## Injection topology (openpilot inline panda)

- **ACC_05 is not present on the stock B8 bus** — the factory single-radar ACC has a 30 km/h floor
  and never asserts this; `0x10d` was absent on every capture. **openpilot originates the frame.**
- The inline panda's **bus2 is the EPB side**; TX `ACC_05` (`0x10D`) there with valid E2E so the
  EPB's COM layer accepts it.
- **Why ACC_05 and not an ESP_05 spoof:** `ESP_Anforderung_EPB` is the ABS's *own* broadcast
  signal; rewriting only the bus2 copy leaves the ABS still broadcasting `anf=0` while the EPB
  sees `anf=2` → the ESP↔EPB consistency check fails → the ABS sets `verf=0` (this was the
  original "value-2" failure). `ACC_Betaetigung_EPB` is qualified by the ACC status field, **not**
  by ESP consistency, so injecting ACC_05 to the EPB does not trip that check. See
  `../../esp8/8R0907379BG/docs/verf_guard_and_dtc.md` (architectural note).

## Sequencing recipe for extended standstill

1. **Approach/stop:** ESP hydraulic holds (reactive); its standstill-release timer is ~5.8 s
   (`standstill_release_timer.md`).
2. **Before/at that timeout:** assert `ACC_05` byte 7 `bit4 = 1` (correct counter + checksum),
   with the qualifier field set, and **hold it continuously**.
3. **Confirm the handoff:** watch `EPB_01` (`0x104`): status → closed and Spannkraft ramps 2→17
   over ~0.4 s (the stock handoff template, `../../esp8/.../autohold_and_standstill_handoff.md`).
4. **Hold:** keep `bit4 = 1` for the entire stop. No EPB-side release timeout on this level was
   found in the image.
5. **Resume:** deassert `bit4 = 0` → arbiter releases (motor opens). **Sequence the release with
   drive-away** (release as torque comes up) to avoid roll-back or a release jerk. **[bench]** if
   deassert alone does not open the caliper, an explicit open is needed — on the ACC path that
   means falling back to the ESP open (`ESP_Anforderung_EPB=1`→cmd5), which carries the
   consistency caveat above; test the ACC-deassert release first.

## Open items for the bench (summary)

- `coding_ext_clamp_enable` (0xfe074.0) live value — UDS 0x22 long-coding read.
- Required value of the ACC_05 byte-7 3-bit status/mode field (bits 1–3).
- Whether deasserting `ACC_Betaetigung_EPB` alone releases the caliper, or needs an explicit open.
- `rte_read_vehicle_speed < 0x4b1` gate — km/h scale and whether v=0 always passes.
- Confirm a sustained ACC clamp request holds with no EPB-side timeout.
