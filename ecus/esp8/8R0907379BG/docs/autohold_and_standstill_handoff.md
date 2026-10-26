# Stock Auto-Hold / standstill brake-hold + EPB handoff — firmware + empirical

B8 Q5, ESP8 8R0907379BG. Combines (a) static firmware RE of the Auto-Hold / standstill path
and (b) empirical decode of the real stock handoff from on-car CAN captures. Companion:
`verf_guard_and_dtc.md`, `epb_dynamic_braking.md`, `route_anb_analysis.md`, `ECD_path.md`.

## Headline

The car's Auto-Hold feature is **real** but is implemented **entirely in the app/COM layer behind
the runtime object-table wall** (`com_obj_table` 0x40a1a8, base ptr `*0x4069b4`). **No part of the
hydraulic standstill-hold or EPB-handoff sequence is commandable from an injectable CAN signal.**
The hydraulic hold is done by the **base ESC hold-valve bank** (`esc_valve_apply_wheel` 0x8fcb8 →
MMIO 0xfff7d400/d500/d600); its pressure demand is set by app code we cannot reach statically.

**For openpilot this is fine** — we do not need to drive the ESP's internal hold. The empirical
stock sequence below is a complete template, and the architecturally correct standstill hold is the
**EPB static clamp** (`Anforderung_EPB=2`, legitimately sequenced so `verf` stays 1).

## Firmware verdict (static, PROVEN)

- No hydraulic path can *sustain* a standstill hold:
  - **ANB / mode-4** (`anb_decel_request_build` 0x4bf3c): reactive, releases when wheel-decel <
    ~1.12 m/s² (arm `0x4066e0` ≥ `0x461`) — lets go at v=0.
  - **comfort / mode-2 ECD** (`ecd_decel_pressure_calc` 0x6de38, phase `ecd_press_stage_state`
    0x6a35c): hard-gated OFF below 15 km/h (`ecd_speed_gate` 0x844fc, cmp #0x78). No v=0 latch.
  - **type-3 "hold"** (`decel_hold_escalation_mgr` 0x42a5c): steady phase of the winning arbitrated
    source (escalates to state 3 when the winner's status byte has bit 0x4 set), a reactive shaper —
    not a v=0 latch.
- `ESP_Autohold_aktiv` (ESP_05 bit56) is a **status mirror** of an app-computed state, routed from
  the object table; it is not a controllable register and no reachable received CAN signal drives it.
- **CORRECTED (see `standstill_release_timer.md`):** the ~5.8 s openpilot-inject release timer **IS
  an ABS/ESP timer** — a standstill-anchored hold-duration limiter on the EPB-Verzoeg (Notbremsfunktion)
  path, proven from the ECU's own CAN outputs (ESP drops its own `ESP_Verz_EPB_aktiv`+`Status_Bremsdruck`
  while the injected request is held constant). The earlier "no ABS timer / likely EPB-module or
  ACC-interlock" conclusion (narrow 0x244/0x488/0x580/0x1160 code-literal scan) is **overturned**. The
  exact RAM counter/threshold stays behind the runtime COM/dispatch wall, but ownership is now proven.

## ESP_05 TX producer chain — resolved to one hop from the wall (PROVEN addresses)

`esp_msg_pack_525c` (0x525c) packer literal pool fully resolved. Chain:

```
app → [object-table DEST_PTR buffer] → router esp05_status_route_a6c8 (0xa6c8, RAM-dispatched,
      no static caller) → fixed source bytes 0x405e68–0x405e96 → packer 0x525c (scale/pack) →
      ESP_05 TX staging → CAN 0x106
```

- **verf value source** = `0x405e70` (==1 → verf bool), `0x405e71/72/73` (bools), **`0x405e74`**
  (raw decel byte; packer scales `(b·0xe1e − 0x92774) >> 8` → TX staging `0x408a7a`). Bools land in
  TX staging `0x408a7c/8d`, `0x407271`.
- **Autohold / Status_Bremsdruck / Anforderung_EPB block source** = `0x405e89/8a/8b/8c/8e/90/92/94/96`.
  `ESP_Anforderung_EPB` (an enum value, not a bool) is one of `0x405e8b`→staging `0x408a8f` or
  `0x405e8c`→staging `0x407300` (INFERRED — could not disambiguate without the ESP_05 DBC bit map).
  TX staging cells `0x408a8a/8c/8e/90` appear in the descriptor stream at `0xb7364–0xb7388`.
- **Those source bytes have NO static writer** — only the RAM-dispatched router `0xa6c8` writes them,
  from an object-table DEST_PTR. The runtime table is **stride-0x18** records
  `{+0 value,+4 ready-mask,+8 DEST_PTR,+0x10 status-word ptr,+0x16 type∈{2,4,5,6}}`, deposited by
  `com_signal_commit_record` (0x50090), indexed off a RAM pointer built at boot from the flash
  descriptor stream `0xb6a44`. The **+8 DEST_PTR slots are zero in the static image** — the wall.

### Static angle EXHAUSTED (honest)

The `0xa7e14` config TLV has **zero BE32 literal references** in the 1.2 MB image; it is read only
by the boot-installed, RAM-wired iterator `FUN_0008e4f4`. The walker's sizer-config pointers
(`0xbd6c4/d0/dc/e8`) point into SEG2 **Thumb code**, not a flash size table. So the dest buffers are
not in flash and cannot be recovered statically. Prior emulation stalled 3× on the same boot-installed
dispatch. **The only remaining unlock is a bench RAM read** — but see below: we don't need it for the
integration. If ever done, the precise target is `0x405e68–0x405ea0` (+ the stride-0x18 table that
`com_sig_group_table_ptr` points at) while toggling EPB/standstill state.

## Empirical stock handoff — the template (on-car CAN)

Decoded from `captures/canlog_20261017_170755.csv` (real manual drive), the one capture containing a
stock autonomous approach→EPB-handoff. Decode: ESP_05 0x106 byte7 (AH=bit0, VzEPB=bit2, verf=bit4,
StBrkP=bit5, AnfEPB=bits6-7); EPB_01 0x104 byte7 (status=bits5-6, Spannkraft=bits0-4); speed from
ESP_01 0x100 bytes[4:6] LE ×0.01 km/h.

```
VzEPB 0→1        @ ~8 km/h    EPB-assist decel flag asserts while still rolling
StBrkP present                hydraulic brake pressure
EPB status 0→2   @ ~6 km/h    EPB motor starts clamping, BEFORE full stop
→ standstill (v<0.5 km/h)
Spann ramps 2→17 over ~0.40 s clamp force builds
EPB status 2→1                latched closed at Spann=17
StBrkP 1→0       ~1.05 s later HYDRAULIC PRESSURE RELEASED — handoff complete
... hold on EPB (status=1, Spann=17) ...
drive-away: Spann 17→0 over ~0.5 s, status→0 (open)
```

Measured constants:
- Resting clamp force **Spann = 17 (0x11)** of 31 max in rlogs (21 in one CSV park).
- Clamp-force ramp **~0.40 s**; moving→closed latency after Spann hits 17 **~40 ms**.
- **EPB-closed → hydraulic-release overlap = ~1.05 s** (NOT the 5.8 s previously assumed — that was
  the openpilot-injected scenario / ABS release timeout, a different context).
- Release ramp on drive-away **~0.48–0.60 s** (consistent across 3 captures).

### Scan of ALL captures (both rlog routes + 5 CSVs, all buses)

- `Autohold_aktiv=1`: **zero frames anywhere** — no hydraulic AVH is ever used.
- `Anforderung_EPB=2`: **zero stock frames** → this field is for an **external requester**
  (ACC/openpilot). The stock car engages its EPB via the internal **`Verz_EPB_aktiv`** path instead.
- `Anforderung_EPB=1` (release): 3 transient frames only. `VzEPB=1`: only in the manual drive.
- `ACC_05` (0x10d): **absent on every bus** → ACC never engaged (stock ACC 30 km/h floor).
- `verf=1` throughout every healthy stop; only `verf=0` was one bench fault frame (EPB status=3).
- openpilot routes: mid-drive stops held **purely hydraulically** (continuous brake pressure, incl. a
  51 s stop); EPB clamps only at **end-of-drive park**, releases at **start-of-drive**. openpilot
  never triggers the stock auto-EPB-at-standstill path.

## Integration recipe for openpilot (what we now have, bench not required)

To reproduce the stock standstill hold (no hydraulic AVH exists to lean on):

1. Keep brake pressure through the approach (decel request, within the `verf` safe envelope).
2. Assert the EPB engage while still rolling slow (stock did it at **~6 km/h**).
3. Ramp clamp to **Spann ≈ 17** over **~0.4 s**; confirm EPB_01 status → closed.
4. Release hydraulic **~1 s** after EPB latches closed.
5. Command field = **`Anforderung_EPB=2`** (external-requester clamp; matches the CLAMP_CMD→2 fix).
6. Sequence it legitimately (v≈0, consistent EPB_01, perfect E2E) so the ESP↔EPB consistency check
   passes and `verf` stays 1 — see `verf_guard_and_dtc.md` safe envelope. Spoofing only the bus2
   ESP_05 copy trips the consistency DTC → verf=0 (the original value-2 failure).

The correct clamp request path is **`ACC_Betaetigung_EPB` on ACC_05** (qualified by `ACC_Status_ACC`,
not ESP consistency) rather than an ESP_05 spoof — see `ecus/epb` RE §11.
