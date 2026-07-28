# Agent task: locate the Simos8.5 cruise minimum-speed constant (C_VS_MIN_CRU_MON)

You are reverse-engineering a Continental **Simos 8.5** ECU (Audi Q5 3.0 TFSI, Infineon
TC1796 TriCore, little-endian). GOAL: find the **exact address of the calibration
constant `C_VS_MIN_CRU_MON`** (and ideally its sibling `C_VS_MIN_CRU`) — the minimum
vehicle speed below which cruise control is inhibited. The real car throws a cruise
fault at **15 km/h**, so the value is **~15 (0x0F), a u8 in km/h**. Deliver the file
offset + vaddr with evidence.

## Environment (already set up — use it, don't rebuild from scratch)
- Repo: the repo root, ECU pack `ecus/simos85`. `source `.env.sh`
  for `GHIDRA_HOME` (Ghidra 12.1.2) and `JAVA_HOME` (JDK 21).
- Binary: `ecus/simos85/firmware/8R0907551F_Original.bin` (2 MB). **file offset = vaddr − 0x80000000.**
  Load base 0x80000000. Also Stage1/Stage2 bins in the same dir (tuner-modified copies).
- Ghidra project: `ecus/simos85/ghidra_proj` (program name `Simos85`), 2171 functions named.
  **Base registers ALREADY set** (critical for TriCore cal access): a0=0xd0008000,
  **a1=0x80048000 = calibration base**, a8=0x80088800. Because of this the decompiler folds
  cal reads to `DAT_8004xxxx` in ~277 functions.
- Resolved decompiles (post base-reg): `ecus/simos85/analysis/decompiles_r/<vaddr>.c`
  (filename = function entry vaddr). Symbols: `analysis/symbols_merged.csv`.
- Funktionsrahmen (Continental spec, 13k pages) indexed at `analysis/fr/`; search with
  `python3 core/pdf/fr_search.py analysis/fr --term "..."` or `--grep-labels REGEX`.
- Calibration region: **vaddr 0x80040000–0x80070000**. Constants are u8/u16 little-endian.
- Headless run pattern:
  `"$GHIDRA_HOME/support/analyzeHeadless" "$PWD/ghidra_proj" Simos85 -process 8R0907551F_Original.bin -noanalysis -scriptPath core/ghidra -postScript YourScript.java <args>`
  Existing Java scripts in `core/ghidra/`: FindCalXrefs, TraceMapCalls, DecompileAll, ApplySymbols.

## What the spec says (the gate to find)
FR ch.14.16 "Monitoring of cruise control conditions" (pages ~2193–2203). The gate is:
`if (VS_MON < C_VS_MIN_CRU_MON) -> cruise inhibited (LV_CRU_INH / LV_CRU_MON_ACT_MON)`.
`VS_MON` = monitored vehicle speed. `C_VS_MIN_CRU_MON` = u8, km/h, resolution 1, range 0..255.
Sibling functional constant `C_VS_MIN_CRU` (also u8 km/h) gates the non-monitor path.

## The CAN anchors (your most promising entry points)
CAN signal layouts are in this DBC (fetch it for full bit detail):
`https://raw.githubusercontent.com/oscarmcnulty/opendbc/39119a5f77797b20c2d61a6779f48eee133e4911/opendbc/dbc/vw_mlb.dbc`

**(a) Cruise stalk switches — message 0x10B (267 dec, "LS_01")**, confirmed receiver
Motor_MED17_SIMOS8. Bit layout (Intel/LE bit numbering = `bit/8` is byte, `bit%8` is the
bit within that byte):
- bit 12 `LS_Hauptschalter` (cruise main on/off)  -> FR STATE_CAN_CRUS_MAIN
- bit 13 `LS_Abbrechen` (cancel)                  -> STATE_CAN_CRUS_OFF
- bit 16 `LS_Tip_Setzen` (SET)                    -> STATE_CAN_CRUS_SET
- bit 17 `LS_Tip_Hoch` (up), bit 18 `LS_Tip_Runter` (down)
- bit 19 `LS_Tip_Wiederaufnahme` (RESUME)         -> STATE_CAN_CRUS_RESU

HINT for the decode function: bits 12–13 are byte[1] bits 4–5; bits 16–19 are byte[2]
bits 0–3. So look in `decompiles_r` for code that loads a CAN buffer byte and does
`>> 4 & 1` / `>> 5 & 1` (byte 1) or `& 1`,`>> 1 & 1`,`>> 3 & 1` (byte 2), assigning the
results to boolean RAM globals — that's the cruise-switch acquisition (FR ch.70.3,
"Acquisition of cruise control inputs", p.12219). Follow those globals to the speed gate.

**(b) Radar/ACC command — message 0x109 (265 dec, "ACC_01")**, the MAIN input from the
radar module to the engine ECU (receiver Motor_MLB_B8_Q5_Otto). It commands the desired
longitudinal accel/decel that the ECU's ACC/cruise torque path acts on:
- bit 0  `CHECKSUM` (u8), bit 8 `COUNTER` (u4) — the ECU validates these (a distinctive
  checksum+rolling-counter check = a good landmark for the ACC_01 handler).
- bit 24 `ACC_Sollbeschleunigung` (11-bit) = **desired acceleration**, scale 0.005, offset
  -7.22 m/s² (range -7.22..+3.01).
- bits 40/48 `ACC_neg/pos_Sollbeschl_Grad` (accel gradient limits), bit 60 `ACC_Status_ACC`.
- Related: `ACC_Momentenanforderung` (ACC torque request, 10-bit) is received by
  Motor_MED17_SIMOS8 in another message and feeds FR `TQ_REQ_ENG_CRU_CTL`.
The ACC_01 handler / the desired-accel→torque conversion lives in the same ACC/cruise
control cluster as the `VS_MON < C_VS_MIN_CRU_MON` speed gate — finding either gets you
into the neighborhood.

A CAN RX **acceptance-filter table** exists at **vaddr 0x80082e10** (12-byte entries
`{u32 id, u32 mask=0x7ff, u32 0}`; 0x38A/GRA_NEU is one entry) — but dispatch is by mailbox
index, so the handler is NOT inline at the ID. Use the bit-decode signature above instead.

## Trace strategy (suggested; adapt freely)
1. **Forward from CAN:** find where message 0x10B / its mailbox buffer is decoded — look for
   code extracting bits 12/13/16/19 of a CAN payload (shifts/masks by those bits). That is the
   cruise-switch acquisition (FR ch.70.3 "Acquisition of cruise control inputs", p12219). Follow
   the resulting state variables (STATE_CAN_CRUS_*) to the function containing the speed compare.
2. **Backward from the compare:** search `decompiles_r` for functions that compare a vehicle-speed
   variable against a u8 cal constant whose value is ~15, in a context with the cruise switch
   states. The constant will appear as `DAT_8004xxxx` (folded) or `*(byte*)(a1 + 0xNNN)`.
3. **Speed signal:** identify the vehicle-speed RAM global (compared against ~15) and find its
   other comparisons (e.g. a max ~250) to confirm it's km/h vehicle speed.
4. Build new Ghidra scripts as needed (e.g. dump all u8 cal constants compared in `<` / `>=`
   ops via the decompiler PcodeAST, with their values and containing function).

## Verification criteria for a candidate address
- Value is ~15 (0x0F) — within a few of 15 (hysteresis may make a pair, e.g. 15/13).
- It lives in the cal region (0x80040000–0x70000) and is read by a function whose logic
  matches `vehicle_speed < CONST -> inhibit cruise` and that touches the cruise switch states.
- It is **NOT** in the Stage1/2 tuner diff (negative control — run
  `python3 core/diff/diff3.py firmware/8R0907551F_Original.bin firmware/8R0907551F_Stage1.bin firmware/8R0907551F_Stage2.bin --region 0x40000:0x80000`;
  tuners don't change cruise min speed).

## Already tried — DO NOT repeat
- Plain value scan for 15 across cal: too common (thousands of hits).
- Grepping decompiles for literal 0x38a/0x10b: CAN dispatch is index-based, not a literal compare.
- FR has no memory addresses (only an alphabetical label index) and no default values.
- km/h+mph cluster fingerprint: too noisy.
NEW leverage you have that those lacked: the **0x10B bit-decode entry point** and the
**base-registers-resolved decompiles** (cal reads visible as DAT_8004xxxx).

## Deliverable
The file offset + vaddr of `C_VS_MIN_CRU_MON` (and `C_VS_MIN_CRU` if found), the current
byte value, the consuming function (vaddr + name), and a short evidence trail. If you can only
narrow to a small candidate set, rank them and explain. Append findings to
`ecus/simos85/maps/RESULTS.md`.
