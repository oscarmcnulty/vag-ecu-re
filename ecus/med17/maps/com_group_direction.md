# COM message-group DIRECTION (RX/TX), by writer analysis — MED17.1.1 `8R0907115N_0006`

Every COM signal-descriptor **group** classified RX or TX from **who writes its RAM targets**,
not from signal geometry. Geometry-based guessing produced two wrong answers before this
(see "What this corrects"); the writer test is objective and validates against three
independent anchors.

## Method

1. **Descriptor table.** 40-byte records, signature = callback `0x800286c6` at `+0x0c` AND
   mask `0x0000ffff` at `+0x14`; `+0x18` = RAM target, `+0x1c` = `[start_bit, bit_len, type, 0]`.
   That signature finds **560** records spanning `0x80035c48 .. 0x8003b8c8`.
   **The table is a contiguous 0x28-stride array of 593 slots**: the 33 slots the signature
   skips are real descriptors with an *alternate conversion callback* (`0x80028954`,
   `0x80028a5c`, `0x800289da`, …) or a non-`0xffff` mask (`0x1000`, `0xefff`). Decoding the
   full extent instead of only signature hits is what makes the segmentation correct —
   a pure signature scan leaves 33 holes that **over-split the groups** (141 instead of 132)
   and, critically, drops the descriptor that carries TSK_01's status field.
   Self-check `start_bit + bit_len <= 64`: **590/593 = 99.5 %**.
2. **Segmentation.** New group where the record address is not contiguous at `0x28`
   **or** the start_bit does not decrease. Yields **132 groups**.
3. **Writer map.** ONE headless Ghidra pass, `core/ghidra/DumpAllWrites.java`, linear
   constant-propagation of the address registers (seeded `a0/a1/a8/a9` from `ecu.conf`),
   full RAM window `0xd0000000..0xd0020000`, stores only → 27 555 resolved writes over
   5 918 functions, dumped to CSV. Group targets are then joined against it offline.
   (Read-only w.r.t. the Ghidra project.)
4. **Rule.**
   - target written by `FUN_8008b17c` (`COM_rx_default_substitution`, the RX
     timeout/default substitution setter) → **RX**
   - target written by application / marshalling code → **TX**
   - no resolvable writer at all → **RX?** (inference: RX unpackers store through a pointer
     read from the descriptor, so their EA is not statically resolvable; TX sources are
     written by ordinary code and almost always are)

## Why the rule is trustworthy

The write map turns out to be **cleanly bipartite**. `COM_rx_default_substitution` writes
148 RAM addresses. Of the ~5 900 other functions, **only one** (`FUN_80089b00`, one address)
ever writes any of those 148. Every other writer — including the high-volume marshallers
`FUN_80316b2a` (217 addresses), `FUN_80313d20`, `FUN_803151fc`, `FUN_80316310`,
`FUN_80312f70` — has **zero** overlap with the RX set. RX buffers and TX staging buffers do
not mix, so a single writer is enough to decide a target.

## Validation

| anchor | expected | result |
|---|---|---|
| group `0x80039208` (`d000ab01` 62\|2, `d00082fc` 27\|10, `d00082b6` 18\|9, `d00082ce` 12\|6, `d000a4d8` 0\|8) | **TX** (TSK_04 0x10E; `d00082b6` produced by `FUN_8014469a`) | **TX** — writers `TSK_status_coordinator`(=`8014469a`), `TSK02_producer`, `FUN_8014322e`, `FUN_801455ae`, `FUN_80316b2a`; DBC TSK_04 0x10E, 4/4 discriminating, unique |
| group `0x80038ad8` (ACC_01 0x109) | **RX** | **RX** — every payload target written *only* by `COM_rx_default_substitution`; DBC ACC_01 0x109, 7/7 discriminating, unique |
| `0xd00084e2`, `0xd00085e4` (known RX-only) | **RX** | both fall in group `0x80039d20`, classified **RX**; DBC Getriebe_02 0x83 — a message the engine receives |

**Independent cross-check.** For the 35 groups whose DBC geometry match is unique, the
writer-derived direction agrees with the DBC transmitter node in **33/35** cases (all
`Motor_*`/`TSK_*` groups classify TX; all `Gateway_*`/`ESP_*`/`Getriebe_*`/`LWS` groups
classify RX). The two disagreements are `0x80038588` (geometry → ESP_05 0x106) and
`0x80038f10` (geometry → Klima_02 0x664): both are written by the TX marshaller
`FUN_80316b2a`, so the **direction is TX and the DBC *label* is the suspect part** —
`vw_mlb.dbc` mixes B8/D4/C7 platform variants and its transmitter fields are not
authoritative for this image.

## Result: which RAM variable is TSK_01 (0x10A) frame bit 23

**Group `0x800393e8` is TSK_01 (0x10A), and it is TX.**

Identification is unambiguous: the group's discriminating geometry is `57|2`, `48|9`,
`40|8`, `16|24`. **`16|24` occurs in exactly one message in the whole of `vw_mlb.dbc` —
TSK_01 (`TSK_Status_AB`)** — and TSK_01 is the only message containing both `16|24` and
`48|9` (`TSK_amax_moeglich`). (The competing 2/4 matches, Gateway_05 and Getriebe_02, hit
only the generic `40|8`/`57|2`/`48|9` slots.) The message's `8|4` COUNTER descriptor sits in
the preceding singleton slot `0x800393c0` (`d000a543`) — on this ECU the counter descriptor
*precedes* the descending body run, which is why it segments as its own group.

| TSK_01 descriptor | bits | RAM target | writer |
|---|---|---|---|
| `0x800393c0` | 8\|4 (COUNTER) | `d000a543` | (COM stack) |
| `0x800393e8` | 57\|2 | `d000a759` | (none resolvable) |
| `0x80039410` | 48\|9 (`TSK_amax_moeglich`) | `d0008ec0` | `FUN_80313d20`, `FUN_803151fc`, `FUN_80316310` |
| `0x80039438` | 40\|8 | `d00082fa` | `FUN_8014106e` |
| `0x80039460` | **16\|24** (`TSK_Status_AB`) | **`d0005e34`** | **`FUN_8014469a` (`TSK_status_coordinator`) @ `0x801454b6`, sole writer** |

So **frame bit 23 is bit 7 of `DAT_d0005e34`** (start_bit 16 → frame bit 23 = value bit 7).

### The chain behind bit 7 of `d0005e34`

All inside `FUN_8014469a`; `FUN_80143a68` is the 8-bool→byte packer (`param_N` → bit `N-1`).

```
d0005e34  =  d0005e38                         (st.w @0x801454b6; pure mirror)
d0005e38  =  d0004938                         (st.w @0x801453ee / 0x801454b0)
d0004938  =  uVar19 | d00049bc | d00049c4     <- 2-frame HOLD of (uVar19 & cal *(u32*)(PTR_801040a4+4))
uVar19    =  pack_hi<<16 | pack_mid<<8 | pack_lo
pack_lo   =  FUN_80143a68(..., param_7 = ACC_abort_request>>4 & 1,
                               param_8 = ACC_abort_request>>2 & 1)   <- param_8 -> bit 7
```

`pack_lo` occupies value bits 0..7 = **frame bits 16..23**, so:

> **TSK_01 frame bit 23 = bit 2 of `ACC_abort_request` @ `0xd00049c9`** (mirrored at
> `0xd000f829`), gated by calibration byte `PTR_DAT_8010384c[0x37]` bit 2, and then
> **held for two further frames** if bit 7 of the 32-bit calibration mask
> `*(u32*)(PTR_DAT_801040a4 + 4)` is set.

**Confirmed at instruction level** (not just from the decompiler's argument ordering — the
TriCore ABI puts args 5..8 on the stack at `[a10]+0/4/8/0xc`, so `[a10]0xc` *is* `param_8`):

```
80144f94  lea    a13,[a0]-0x7b08          ; = 0xd0004918, so base+0xb1 = 0xd00049c9
80144f9a  ld.bu  d15,[a15]0xb1            ; ACC_abort_request
80144f9e  extr.u d0,d15,#0x4,#0x1         ; bit 4 -> [a10]0x8  = param_7 -> packed bit 6 -> frame bit 22
80144fa4  extr.u d15,d15,#0x2,#0x1        ; bit 2 -> [a10]0xc  = param_8 -> packed bit 7 -> FRAME BIT 23
80144fac  st.w   [a10]#0xc,d15
80144fb4  call   0x80143a68
80144fb8  mov    d13,d2                   ; d13 = the low byte
...
80145070  or     d9,d13,d2                ; low | mid<<8
801450b6  or     d2,d9                    ; | hi<<16          -> uVar19
801450d0  ld.w   d15,[a2]#0x4             ; a2 = *(a9+0xc40) = cal object -> the hold mask
801450d2  and    d15,d2
801450e6  st.w   [a0]-0x7ae8,d0           ; -> 0xd0004938
801453e6  ld.w   d15,[a0]-0x7ae8
801453ee  st.w   [a0]-0x65e8,d15          ; -> 0xd0005e38
801454b6  st.w   [a0]-0x65ec,d15          ; -> 0xd0005e34  = the TSK_01 16|24 COM target
```

Upstream of that (same function, `FUN_80143a68` call that builds `ACC_abort_request`):

```
ACC_abort_request(d00049c9) bit 2  =  param_3  =  DAT_d0004930 >> 5 & 1
d0004930                           =  DAT_d000a346                (frame-start snapshot copy)
d000a346  bit 5                    =  set in FUN_80140922 (TSK02_producer) @ line ~235:
                                      bVar29 |= cVar23 << 5, where
                                      cVar23 = 1 if FUN_800981cc(DAT_80028bc6) == 0
                                               or (cal PTR_DAT_80104094[0xd] & bVar19) != 0
```

`FUN_800981cc(id)` is the established message presence/validity accessor (`0` = fresh).

**Inference, not verified on-car:** the two-frame calibration hold on `d0004938` is a
plausible mechanism for the observed "bit 23 leads the ACC disengage by one frame" —
the abort reason is *published* on TSK_01 in the cycle it is raised, while the engage state
machine (`FUN_80143b8a`, reading `d00049c9` via `FUN_80143b26`) acts on it on the next pass.
The 0…15.28 km/h correlation is consistent with `d000a346.5` being a min-speed/validity
inhibit, but the exact speed threshold has not been traced to a calibration cell here.

## What this corrects

`maps/acc_flow.md` (row "TSK_Status_AB (16|24 = 3 bytes)") and
`analysis/symbols_merged.csv:67` both state that TSK_01's `TSK_Status_AB` is carried by
`d000f828/f829/f82a` (= `a34b/a34c/a34d`). **The COM descriptor's actual RAM target for
`16|24` is the single 32-bit word `d0005e34`.** `d000f829` (= `d00049c9`,
`ACC_abort_request`) is not the status byte — it supplies only **two** of that byte's eight
bits (frame bits 22 and 23, from abort bits 4 and 2). Those files should be corrected;
they are left untouched here so the change is reviewable on its own.

## Reproduce

```bash
source .env.sh
analyzeHeadless ecus/med17/ghidra_proj MED1711 -process 8R0907115N_0006.bin -noanalysis \
  -scriptPath core/ghidra -postScript DumpAllWrites.java 0xd0000000 0xd0020000 allwrites.csv true
# then decode the 0x28-stride descriptor extent from the image and join on the RAM targets
```

Runtime ≈ 40 s. The scan is read-only; it does not mutate the Ghidra project.

## Full classification

`class` legend — **TX**: at least one target written by application/marshalling code.
**RX**: targets written only by `COM_rx_default_substitution`. **AMBIG**: both (2 groups;
both match messages the engine receives, so read them as RX with a stray app-side write).
**RX?**: no statically resolvable writer — inferred RX.
DBC column: discriminating geometry hits only (the universal `0|8` CHECKSUM and `8|4`
COUNTER slots are excluded), ranked by rarity weight; "unique" = exactly one message
attains the top score and it matches every discriminating slot.

Three of the 593 slots fail the self-check and are carried through as-is: `0x8003b8c8`
(`112|105`, the last slot — probably the array terminator or a neighbouring structure, and
the reason group #132 is a spurious singleton) and `0x80037bd8`/`0x80037c00` inside group
`0x80037b88`, whose "RAM" targets `0x8002793c`/`0x800278fc` are in flash — signals bound to
ROM constants rather than to RAM.

| # | group base | recs | class | DBC geometry match (discriminating hits) | writers of the group's RAM targets |
|---|---|---|---|---|---|
| 1 | `0x80035c48` | 5 | **TX** | NMH_EPB 0x6d9, NMH_Gateway 0x6c0, NMH_Getriebe 0x6c2 … — 2/5 (6-way tie) | FUN_800813ee, FUN_800815b4 |
| 2 | `0x80035d10` | 2 | **TX** | DEV_Airbag_01 0x9bfcaa00, SCR_04 0x5e5 — 1/2 (2-way tie) | FUN_800545e0 |
| 3 | `0x80035d60` | 2 | **TX** | DEV_Airbag_01 0x9bfcaa00, SCR_04 0x5e5 — 1/2 (2-way tie) | FUN_800545e0 |
| 4 | `0x80035db0` | 2 | **TX** | DEV_Airbag_01 0x9bfcaa00, SCR_04 0x5e5 — 1/2 (2-way tie) | FUN_800545e0 |
| 5 | `0x80035e00` | 1 | **RX?** | WIV_01 0x642 — 1/1 **unique** | (none resolvable) |
| 6 | `0x80035e28` | 8 | **RX** | OBD_Tankgeber_01 0x65e — 7/7 **unique** | **COM_rx_default_substitution** |
| 7 | `0x80035f68` | 3 | **RX** | ACC_01 0x109 — 2/3 | **COM_rx_default_substitution** |
| 8 | `0x80035fe0` | 2 | **RX?** | Kessy_02 0x590 — 2/2 **unique** | (none resolvable) |
| 9 | `0x80036030` | 1 | **RX?** | Anhaenger_01 0x661, Kessy_02 0x590, Licht_hinten_01 0x471 … — 1/1 (4-way tie) | (none resolvable) |
| 10 | `0x80036058` | 2 | **RX** | ACC_01 0x109, STH_01 0x521 — 2/2 (2-way tie) | **COM_rx_default_substitution** |
| 11 | `0x800360a8` | 7 | **RX** | Diagnose_01 0x6b2 — 7/7 **unique** | **COM_rx_default_substitution** |
| 12 | `0x800361c0` | 3 | **TX** | Motor_07 0x640, OBD_01 0x391, SCR_CAL_ID1 0x5e6 … — 2/2 (4-way tie) | FUN_80316b2a |
| 13 | `0x80036238` | 6 | **TX** | Airbag_02 0x520 — 1/4 | FUN_80316b2a |
| 14 | `0x80036328` | 7 | **TX** | Klima_02 0x664 — 2/5 | FUN_80316b2a |
| 15 | `0x80036440` | 2 | **RX?** | - | (none resolvable) |
| 16 | `0x80036490` | 1 | **TX** | BEM_03 0x3b2, Getriebe_04 0x441 — 1/1 (2-way tie) | FUN_80316b2a |
| 17 | `0x800364b8` | 7 | **TX** | BEM_03 0x3b2 — 1/5 | FUN_80316b2a |
| 18 | `0x800365d0` | 7 | **RX?** | ESP_01 0x100 — 1/5 | (none resolvable) |
| 19 | `0x800366e8` | 7 | **TX** | ESP_01 0x100, Motor_01 0x80, Motor_02 0x81 — 2/5 (3-way tie) | FUN_80316b2a |
| 20 | `0x80036800` | 8 | **TX** | Motor_01 0x80 — 4/6 | FUN_80316b2a |
| 21 | `0x80036940` | 7 | **RX** | ESP_07_FR 0x392 — 3/7 | **COM_rx_default_substitution** |
| 22 | `0x80036a58` | 1 | **RX** | ACC_01 0x109, Gateway_05 0x39c, Getriebe_02 0x83 … — 1/1 (14-way tie) | **COM_rx_default_substitution** |
| 23 | `0x80036a80` | 1 | **RX?** | Airbag_02 0x520 — 1/1 **unique** | (none resolvable) |
| 24 | `0x80036aa8` | 9 | **TX** | Diagnose_01 0x6b2, WIV_01 0x642 — 1/9 (2-way tie) | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 25 | `0x80036c10` | 13 | **TX** | Einheiten_01 0x643 — 4/13 | FUN_8019889a, FUN_80198dfc, FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 26 | `0x80036e18` | 5 | **TX** | Kombi_03 0x6b8 — 1/5 | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 27 | `0x80036ee0` | 8 | **TX** | - | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 28 | `0x80037020` | 6 | **TX** | LDW_02 0x397, SCU_01 0x85 — 1/6 (2-way tie) | FUN_80093a46, FUN_80093bce, FUN_80093c14, FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 29 | `0x80037110` | 7 | **TX** | SCR_02 0x5e3, SCR_CAL_ID1 0x5e6, SCR_CAL_ID2 0x5e8 — 4/7 (3-way tie) | FUN_800af78c, FUN_80312f70, FUN_803147dc, FUN_80315a54, FUN_80316b2a |
| 30 | `0x80037228` | 1 | **RX?** | - | (none resolvable) |
| 31 | `0x80037250` | 12 | **TX** | Airbag_01 0x40 — 4/10 | FUN_8008bf24, FUN_8018e656, FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 32 | `0x80037430` | 5 | **TX** | Motor_01 0x80 — 4/4 **unique** | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 33 | `0x800374f8` | 4 | **TX** | - | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 34 | `0x80037598` | 1 | **RX?** | - | (none resolvable) |
| 35 | `0x800375c0` | 8 | **TX** | BEM_03 0x3b2, ESP_08 0x11e — 1/6 (2-way tie) | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 36 | `0x80037700` | 1 | **RX?** | - | (none resolvable) |
| 37 | `0x80037728` | 2 | **TX** | Getriebe_03 0x102, SCR_02 0x5e3 — 1/2 (2-way tie) | FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 38 | `0x80037778` | 6 | **TX** | WIV_01 0x642 — 6/6 **unique** | FUN_8008c00a, FUN_8008c16e |
| 39 | `0x80037868` | 5 | **TX** | OBD_01 0x391 — 4/4 **unique** | FUN_8008da12 |
| 40 | `0x80037930` | 1 | **RX?** | - | (none resolvable) |
| 41 | `0x80037958` | 1 | **RX?** | - | (none resolvable) |
| 42 | `0x80037980` | 8 | **TX** | Motor_Code_01 0x641 — 8/8 **unique** | FUN_800898b8, FUN_8008da12 |
| 43 | `0x80037ac0` | 5 | **TX** | Motor_07 0x640, SCR_CAL_ID1 0x5e6, SCR_CAL_ID2 0x5e8 — 3/4 (3-way tie) | FUN_8019889a, FUN_80198dfc, FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 44 | `0x80037b88` | 5 | **TX** | Motor_09 0x647 — 2/4 | FUN_8008da12 |
| 45 | `0x80037c50` | 9 | **TX** | Motor_07 0x640 — 9/9 **unique** | FUN_8008da12, FUN_800a092c, FUN_8018e656, FUN_80193a1e, FUN_80312f70, FUN_80313d20, FUN_803147dc, FUN_803151fc, FUN_80315a54, FUN_80316310, FUN_80316b2a, FUN_8031ad86 |
| 46 | `0x80037db8` | 7 | **TX** | Motor_06 0x440 — 6/7 | FUN_8008da12, FUN_80189d88, FUN_80193a1e, FUN_80312f70, FUN_803147dc, FUN_80315a54 |
| 47 | `0x80037ed0` | 2 | **RX** | Kessy_02 0x590 — 2/2 **unique** | **COM_rx_default_substitution** |
| 48 | `0x80037f20` | 12 | **RX** | PSD_01 0x3a1 — 12/12 **unique** | **COM_rx_default_substitution** |
| 49 | `0x80038100` | 2 | **RX?** | - | (none resolvable) |
| 50 | `0x80038150` | 6 | **AMBIG** | EPB_01 0x104 — 4/4 **unique** | **COM_rx_default_substitution**, FUN_80316b2a |
| 51 | `0x80038240` | 1 | **RX** | Kombi_03 0x6b8 — 1/1 **unique** | **COM_rx_default_substitution** |
| 52 | `0x80038268` | 3 | **RX** | Kombi_02 0x6b7 — 3/3 **unique** | **COM_rx_default_substitution** |
| 53 | `0x800382e0` | 1 | **RX** | - | **COM_rx_default_substitution** |
| 54 | `0x80038308` | 10 | **RX** | SCR_05 0x5f6 — 4/8 | **COM_rx_default_substitution** |
| 55 | `0x80038498` | 6 | **RX?** | ESP_07_FR 0x392, SCR_03 0x5e4 — 4/4 (2-way tie) | (none resolvable) |
| 56 | `0x80038588` | 6 | **TX** | ESP_05 0x106 — 4/4 **unique** | FUN_80316b2a |
| 57 | `0x80038678` | 4 | **RX** | ESP_02 0x101 — 2/2 **unique** | **COM_rx_default_substitution** |
| 58 | `0x80038718` | 7 | **TX** | Motor_01 0x80 — 4/5 | FUN_80316b2a |
| 59 | `0x80038830` | 2 | **RX?** | - | (none resolvable) |
| 60 | `0x80038880` | 6 | **RX** | Klima_01 0x3bf — 6/6 **unique** | **COM_rx_default_substitution** |
| 61 | `0x80038970` | 4 | **RX** | ACC_10 0x117, Airbag_01 0x40, Klima_03 0x66e … — 1/2 (4-way tie) | **COM_rx_default_substitution** |
| 62 | `0x80038a10` | 1 | **RX?** | - | (none resolvable) |
| 63 | `0x80038a38` | 1 | **RX?** | - | (none resolvable) |
| 64 | `0x80038a60` | 3 | **RX** | ACC_05 0x10d — 3/3 **unique** | **COM_rx_default_substitution** |
| 65 | `0x80038ad8` | 9 | **RX** | ACC_01 0x109 — 7/7 **unique** | **COM_rx_default_substitution** |
| 66 | `0x80038c40` | 3 | **TX** | ESP_06 0x84 — 1/3 | FUN_80313d20, FUN_803151fc, FUN_80316310 |
| 67 | `0x80038cb8` | 7 | **TX** | LH_EPS_03 0x9f — 2/7 | FUN_80313d20, FUN_803151fc, FUN_80316310 |
| 68 | `0x80038dd0` | 4 | **TX** | ESP_03 0x103, OBD_Tankgeber_01 0x65e — 2/4 (2-way tie) | FUN_8019889a, FUN_80198de2, FUN_80198dfc |
| 69 | `0x80038e70` | 4 | **TX** | Motor_18 0x670 — 2/3 | FUN_80313d20, FUN_803151fc, FUN_80316310 |
| 70 | `0x80038f10` | 3 | **TX** | Klima_02 0x664 — 2/2 **unique** | FUN_80312f70, FUN_80313d20, FUN_803151fc, FUN_80315a54, FUN_80316310 |
| 71 | `0x80038f88` | 3 | **TX** | Motor_10 0x114 — 3/3 **unique** | FUN_8008de2c, FUN_802ecda8, FUN_802ed05c, FUN_80313d20, FUN_803151fc, FUN_80316310 |
| 72 | `0x80039000` | 1 | **TX** | BEM_01 0x309, Einheiten_01 0x643, EPB_01 0x104 … — 1/1 (14-way tie) | FUN_8008dd74 |
| 73 | `0x80039028` | 3 | **TX** | Motor_04 0x107 — 2/2 **unique** | FUN_8008ceb6, FUN_80203434 |
| 74 | `0x800390a0` | 1 | **RX?** | - | (none resolvable) |
| 75 | `0x800390c8` | 7 | **TX** | TSK_05 0x111 — 6/6 **unique** | FUN_8014106e, FUN_801455ae, FUN_80316b2a, TSK02_decel_gate |
| 76 | `0x800391e0` | 1 | **RX?** | - | (none resolvable) |
| 77 | `0x80039208` | 5 | **TX** | TSK_04 0x10e — 4/4 **unique** | FUN_8014322e, FUN_801455ae, FUN_80316b2a, TSK02_producer, TSK_status_coordinator |
| 78 | `0x800392d0` | 1 | **RX?** | - | (none resolvable) |
| 79 | `0x800392f8` | 5 | **TX** | TSK_05 0x111 — 3/4 | FUN_80050eea, FUN_8014106e, FUN_801455ae, FUN_80316b2a, TSK02_decel_gate |
| 80 | `0x800393c0` | 1 | **RX?** | - | (none resolvable) |
| 81 | `0x800393e8` | 4 | **TX** | TSK_01 0x10a — 2/4 | FUN_8014106e, FUN_80313d20, FUN_803151fc, FUN_80316310, TSK_status_coordinator |
| 82 | `0x80039488` | 4 | **RX** | LWI_01 0x86 — 2/2 **unique** | **COM_rx_default_substitution** |
| 83 | `0x80039528` | 3 | **RX?** | ESP_03 0x103, LH_EPS_03 0x9f, OBD_Tankgeber_01 0x65e … — 1/1 (4-way tie) | (none resolvable) |
| 84 | `0x800395a0` | 4 | **RX** | Charisma_01 0x385, SCU_02 0x310 — 2/2 (2-way tie) | **COM_rx_default_substitution** |
| 85 | `0x80039640` | 6 | **RX** | Gateway_05 0x39c — 6/6 **unique** | **COM_rx_default_substitution** |
| 86 | `0x80039730` | 3 | **RX?** | BEM_01 0x309, LS_01 0x10b — 1/1 (2-way tie) | (none resolvable) |
| 87 | `0x800397a8` | 6 | **RX?** | ESP_03 0x103, LH_EPS_03 0x9f, OBD_Tankgeber_01 0x65e — 2/4 (3-way tie) | (none resolvable) |
| 88 | `0x80039898` | 8 | **RX?** | SCR_03 0x5e4 — 4/6 | (none resolvable) |
| 89 | `0x800399d8` | 7 | **RX** | SCR_03 0x5e4, WIV_01 0x642 — 1/5 (2-way tie) | **COM_rx_default_substitution** |
| 90 | `0x80039af0` | 6 | **RX** | Getriebe_04 0x441 — 5/5 **unique** | **COM_rx_default_substitution** |
| 91 | `0x80039be0` | 8 | **RX** | Getriebe_03 0x102 — 6/6 **unique** | **COM_rx_default_substitution** |
| 92 | `0x80039d20` | 9 | **RX** | Getriebe_02 0x83 — 7/7 **unique** | **COM_rx_default_substitution** |
| 93 | `0x80039e88` | 6 | **RX** | Getriebe_01 0x82 — 4/4 **unique** | **COM_rx_default_substitution** |
| 94 | `0x80039f78` | 7 | **RX** | SCR_01 0x3f3 — 3/5 | **COM_rx_default_substitution** |
| 95 | `0x8003a090` | 6 | **RX** | Motor_04 0x107 — 1/4 | **COM_rx_default_substitution** |
| 96 | `0x8003a180` | 6 | **RX** | Motor_04 0x107 — 1/4 | **COM_rx_default_substitution** |
| 97 | `0x8003a270` | 6 | **RX** | BEM_01 0x309 — 4/4 **unique** | **COM_rx_default_substitution** |
| 98 | `0x8003a360` | 3 | **RX** | Getriebe_01 0x82, Getriebe_02 0x83, Klima_02 0x664 … — 1/3 (4-way tie) | **COM_rx_default_substitution** |
| 99 | `0x8003a3d8` | 5 | **RX** | ACC_02 0x30c — 2/3 | **COM_rx_default_substitution** |
| 100 | `0x8003a4a0` | 7 | **RX** | Motor_05 0x30e — 2/5 | **COM_rx_default_substitution** |
| 101 | `0x8003a5b8` | 5 | **RX** | ACC_02 0x30c, ESP_01 0x100, Motor_01 0x80 … — 1/3 (5-way tie) | **COM_rx_default_substitution** |
| 102 | `0x8003a680` | 6 | **RX** | ESP_03 0x103, OBD_Tankgeber_01 0x65e — 4/4 (2-way tie) | **COM_rx_default_substitution** |
| 103 | `0x8003a770` | 5 | **AMBIG** | ESP_01 0x100 — 3/3 **unique** | **COM_rx_default_substitution**, FUN_80089b00 |
| 104 | `0x8003a838` | 6 | **RX** | Charisma_01 0x385, Motor_04 0x107 — 1/4 (2-way tie) | **COM_rx_default_substitution** |
| 105 | `0x8003a928` | 4 | **RX** | LDW_02 0x397 — 1/3 | **COM_rx_default_substitution** |
| 106 | `0x8003a9c8` | 4 | **TX** | Dimmung_01 0x5f0, Getriebe_03 0x102, Kombi_02 0x6b7 … — 1/3 (6-way tie) | FUN_8008c8f2, FUN_80217666, FUN_802c50a2 |
| 107 | `0x8003aa68` | 8 | **TX** | SCR_03 0x5e4 — 4/7 | FUN_80216a7c, FUN_80217666, FUN_80217eb8, FUN_8021853c |
| 108 | `0x8003aba8` | 6 | **TX** | STH_01 0x521 — 1/4 | FUN_80079e58 |
| 109 | `0x8003ac98` | 7 | **TX** | ESP_06 0x84, Motor_05 0x30e, SCR_02 0x5e3 … — 2/5 (5-way tie) | FUN_80217666 |
| 110 | `0x8003adb0` | 9 | **TX** | SCR_CAL_ID1 0x5e6, SCR_CAL_ID2 0x5e8 — 6/7 (2-way tie) | FUN_80216a7c, FUN_80217666 |
| 111 | `0x8003af18` | 3 | **TX** | Charisma_01 0x385, Klima_02 0x664 — 2/2 (2-way tie) | FUN_80217666, FUN_80217eb8 |
| 112 | `0x8003af90` | 3 | **TX** | Motor_03 0x105, WIV_01 0x642 — 1/2 (2-way tie) | FUN_8008c8f2 |
| 113 | `0x8003b008` | 1 | **RX?** | - | (none resolvable) |
| 114 | `0x8003b030` | 8 | **TX** | Getriebe_01 0x82 — 2/7 | FUN_80079e58, FUN_8008c8f2, FUN_800b91d6, FUN_80216a7c, FUN_80217060 |
| 115 | `0x8003b170` | 1 | **RX?** | - | (none resolvable) |
| 116 | `0x8003b198` | 4 | **TX** | Kombi_02 0x6b7, Motor_Code_01 0x641 — 1/3 (2-way tie) | FUN_80218862, FUN_802c50a2, FUN_80317ea8, FUN_8031896c, FUN_80319250 |
| 117 | `0x8003b238` | 1 | **RX?** | - | (none resolvable) |
| 118 | `0x8003b260` | 3 | **TX** | Motor_03 0x105, WIV_01 0x642 — 1/2 (2-way tie) | FUN_8014a498, FUN_8014a67e, FUN_80218862 |
| 119 | `0x8003b2d8` | 5 | **TX** | Motor_05 0x30e — 4/4 **unique** | FUN_8008d318, FUN_80178266 |
| 120 | `0x8003b3a0` | 4 | **TX** | Motor_05 0x30e — 4/4 **unique** | FUN_8008d318, FUN_8031788a, FUN_80317ea8, FUN_8031851a, FUN_8031896c, FUN_80318f46, FUN_80319250 |
| 121 | `0x8003b440` | 2 | **TX** | ESP_05 0x106, ESP_07_FR 0x392, Motor_05 0x30e … — 1/1 (6-way tie) | FUN_8031788a, FUN_8031851a |
| 122 | `0x8003b490` | 1 | **RX?** | - | (none resolvable) |
| 123 | `0x8003b4b8` | 5 | **TX** | Motor_03 0x105 — 4/4 **unique** | FUN_8014a498, FUN_8014a67e, FUN_80218862, FUN_802c47c2, FUN_8031788a, FUN_80317ea8, FUN_8031851a, FUN_80318f46 |
| 124 | `0x8003b580` | 3 | **TX** | Motor_02 0x81 — 2/2 **unique** | FUN_8008d278, FUN_80198b18, FUN_80198dfc |
| 125 | `0x8003b5f8` | 1 | **TX** | ACC_02 0x30c, ACC_05 0x10d, Airbag_02 0x520 … — 1/1 (4-way tie) | FUN_802c51c2 |
| 126 | `0x8003b620` | 5 | **TX** | Motor_02 0x81 — 4/4 **unique** | FUN_8008d318, FUN_80317ea8, FUN_8031896c, FUN_80319250 |
| 127 | `0x8003b6e8` | 1 | **RX?** | - | (none resolvable) |
| 128 | `0x8003b710` | 6 | **TX** | Motor_01 0x80 — 5/5 **unique** | FUN_8008d318 |
| 129 | `0x8003b800` | 1 | **RX?** | - | (none resolvable) |
| 130 | `0x8003b828` | 3 | **TX** | ACC_02 0x30c, TSK_03 0x312 — 3/3 (2-way tie) | FUN_80317ea8, FUN_8031896c |
| 131 | `0x8003b8a0` | 1 | **TX** | ACC_02 0x30c, TSK_03 0x312 — 1/1 (2-way tie) | FUN_80317ea8, FUN_8031896c |
| 132 | `0x8003b8c8` | 1 | **RX?** | - | (none resolvable) |
