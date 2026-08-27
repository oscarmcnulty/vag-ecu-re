# C7 (A6/A7) ESP vs B8 Q5 ESP8 — extraction + first comparison

**2026-08-20.** Three ODIS flash containers for the Audi C7 (4G) ABS/ESP were decrypted and
their main flash blocks extracted, then compared against the Q5's `8R0907379BG_0030`.
Goal: find how a car with factory 0-km/h ACC stop&go handles the low-speed **ECD** gate that
in our image is the hardcoded `cmp #0x78` (= 15.0 km/h) of `docs/ECD_path.md`.

## 1. Extraction (VERIFIED, reproducible)

```
python3 -m frf.decryptfrf --file FL_<part>_<ver>.frf --outdir <dir>   # bri3d/VW_Flash, ~/tools
python3 core/odx/odx_extract.py <dir>/FL_<part>_<ver>.odx -o <dir>    # new, this repo
```

`core/odx/odx_extract.py` (added here) walks the ODX-F `<FLASHDATA>` / `<DATABLOCK>` pairs and
writes one file per block plus the identity blocks. Notes:

- The FRF layer is the usual VAG recursive-XOR (same key material as the Simos containers) —
  **not ECU-specific**, so the ABS containers decrypt with the Simos tooling unchanged.
- **`DATAFORMAT=BINARY`, `ENCRYPT-COMPRESS-METHOD=00` — the payload is plaintext.** Unlike the
  standalone `.sgo` (which is whole-image XOR 0xFF with a 0x200 header), the block inside the
  FRF is the raw image: it starts directly with the ARM BE32 vector table (`ea xx xx xx` ×8).
- Main image is always `DB_1DATA`, UDS block id **0x10**, **1 998 848 B (0x1E8000)** in all three.
  `DB_0DRIVE` (block id 0xFF, ~8 KB) is the flash driver. `DB_2..n` are the small identity /
  coding writes.

## 2. Identity (VERIFIED — from the ODX EXPECTED-IDENTs and the images' own ID blocks)

| container | spare part numbers | component ID | Bosch project string | size |
|---|---|---|---|---|
| `FL_4G0907379___0190` | `4G0907379`, `4G0907379B` | `EV_ESPPremiAU57X` | `BOSCH.CSDE.AUDI_B6.01.005` | 0x1E8000 |
| `FL_4G0907379H__0361` | `4G0907379H`, **`4G0907379J`** | `EV_ESPPremiAU57X` | `BOSCH.CSDE.AUDI_B6.01.005` | 0x1E8000 |
| `FL_4G0907379AD_0400` | `4G0907379AD` | `EV_ESP9BOSCHAU57X` | `Bosch.CSDE.BEG_VAG.02.002` | 0x1E8000 |
| *(ours)* `8R0907379BG_0030` | `8R0907379BG` | `ESP8 quattro` | `Bosch.CSDE.BEG_VAG.01.004` | 0x134011 |

Three conclusions:

1. **`0361` is the ACC-relevant one.** It flashes both `4G0907379H` *and* **`4G0907379J`** — and
   `J` is the part that pairs with hydraulic unit `4G0614517S`, the block listed as the "ACC"
   variant. One binary serves both, i.e. **ACC vs non-ACC is a coding/variant split inside one
   image, not a separate part** on the C7 — exactly the case that makes a coding-only fix possible.
2. **`AD_0400` is a different ECU generation** — `ESP9`, and the `BEG_VAG.**02**.002` project line
   (ours is `BEG_VAG.01.004`, i.e. its predecessor). It is also almost entirely Thumb (zero ARM
   `LDRSH;CMP;B<c>` sites), so it is the *architectural* successor, not a diff partner.
3. `0190` / `0361` are the `AUDI_B6` project — an ESP-Premium line **distinct** from our
   `BEG_VAG` one. Same Bosch house style (identical trailer/signature block layout, same `b6`
   filler, ARM BE32) but a separate build lineage.

## 3. Structural comparison (VERIFIED)

| | Q5 `BG` | C7 `0190` | C7 `0361` | C7 `AD` |
|---|---|---|---|---|
| size | 1 261 585 | 1 998 848 | 1 998 848 | 1 998 848 |
| ARM `B` in first 8 vectors | 4 | 8 | 8 | 8 |
| ARM `cmp Rn,#0x78` sites | 10 | 15 | 20 | **0** |
| Thumb `cmp Rn,#0x78` sites | 49 | 14 | 14 | 90 |

**Byte-level diffing is useless here.** Shared 32-byte aligned chunks:

| pair | shared |
|---|---|
| Q5 ↔ 0190 | **0.02 %** |
| Q5 ↔ 0361 | **0.02 %** |
| Q5 ↔ AD | 0.01 % |
| 0190 ↔ 0361 (same part family!) | 1.72 % |
| 0361 ↔ AD | 0.25 % |

Even two revisions of the *same* C7 part share under 2 %: these are independently linked builds
with different layout. All comparison must therefore be **semantic** (function/idiom level), not
byte-level. Consequence for `core/diff/`: don't bother running an image differ on these.

## 4. The ECD floor — first probe (PARTIAL)

> ⚠ **Address correction (2026-08-20).** Every C7 address in this section is a **file offset**.
> All three C7 images load at **`0x18000`** (proven in `e2e_family.md` §1), so the load address is
> the offset plus `0x18000` — e.g. the `0361` site called `0x8415c` below is address `0x9c15c`.
> The Q5 image is base 0, so its addresses are unaffected.

Our Q5's floor, re-verified by direct disassembly of `8R0907379BG_0030.bin` @ `0xd170`:

```asm
d174  ldrsh r0,[ip,#0xa]      ; ip = ptr @0xdbbc
d178  cmp   r0,#0x1e
d17c  blt   0xd234
d184  ldrsh r2,[r1]           ; r1 = ptr @0xdbc0   speed source A
d18c  cmp   r2,#0xc8          ; 25.0 km/h
d190  bgt   0xd1ac
d194  ldrsh r3,[r0]           ; r0 = ptr @0xdbc4   speed source B
d198  cmp   r3,#0xc8
d19c  bgt   0xd1ac
d1a0  ldrsh r3,[ip]
d1a4  cmp   r3,#0xd2          ; 26.25 km/h
d1a8  ble   0xd1bc
d1ac  ldrb  r2,[r7] ; orr r2,#4 ; strb r2,[r7]     <- sets a status bit
d1b8  ldrsh r2,[r1]
d1bc  cmp   r2,#0x78          ; 15.0 km/h  <<< THE FLOOR (source A)
d1c0  bge   0xd220
d1c4  ldrsh r0,[r0]
d1c8  cmp   r0,#0x78          ; 15.0 km/h  <<< THE FLOOR (source B)
d1cc  bge   0xd220
d1d0  ldrb  r0,[r4,#0x55] ; ... decrement debounce counter ...
```

So the floor is a **two-source** compare (both speed sources must be < 15 km/h) feeding a
debounce counter — consistent with the on-car 15.21/15.14 km/h hysteresis in `ECD_path.md`.

Scanning all four images for that idiom — `LDRSH; CMP Rn,#imm; B<cond>` at a 4-byte boundary,
then clustering sites within 32 bytes:

- **Q5:** the cluster is unmistakable — `0xc8, 0xd2, 0x78, 0x78` at `0xd194…0xd1c8`.
- **`0190` / `0361`: no `0x78` pair exists anywhere.** Their clustered pairs are
  `0x9a,0x9a` (19.25), `0xce,0xce` (25.75), `0xa,0xa` (1.25) and, in `0361`, `0x80,0x80` (16.0).
- **`AD`:** not scannable this way — it is Thumb.

The closest structural analogue found is `0361` @ `0x8415c`:

```asm
84140  cmp   r0,#0x780        ; 240 km/h (upper bound)
8414c  cmpgt r0,#0x780
84150  bgt   0x84190
8415c  ldrsh r0,[r0]          ; source A (via ptr table @0x83390 +0x20)
84160  cmp   r0,#0x80         ; 16.0 km/h if the unit is 0.125
84164  ble   0x84190          ; <-- note INVERTED polarity vs the Q5
84170  ldrsh r0,[r0]          ; source B (same table +0x2c)
84174  cmp   r0,#0x80
84178  ble   0x84190
```

Same two-source shape, but it **skips** when speed ≤ 16 km/h where the Q5 **skips** when
speed ≥ 15 km/h — so it is not the same function, or not the same sense. **Not yet identified;
do not report this as the C7 ECD gate.**

⚠ Two things are unverified and must be nailed before any conclusion:
1. **The speed unit in the C7 images.** 0.125 km/h is proven for *our* image (DBC `ESP_v_ref`
   scale + the ±0x7ff clamp). The `#0x780` bound above is consistent with 240 km/h at 0.125, but
   that is suggestive, not proof.
2. **Absence of a `0x78` pair is not absence of a floor.** The gate may use a different constant,
   a calibration value, a Thumb encoding, or may not exist at all (which is the hypothesis worth
   testing). Only tracing the ESP_05 (0x106) packer back to its ECD source settles it.

## 5. State + next steps

- Images staged (gitignored) as `ecus/esp8/<variant>/firmware/` (see §6).
- Per-variant Ghidra projects under `ecus/esp8/<variant>/ghidra_proj/`, `ARM:BE:32:v5t`, base 0x0
  (the `AD` ESP9 image has none yet — its processor variant is undecided, see its `variant.conf`).
  Same caveat as the Q5 project: auto-analysis fabricates functions in the data region, so
  `ghidra_scripts/EspFix.java` must be run before trusting anything at high addresses.
- **Next (the actual answer):** in `0361`, anchor the CAN TX path the way `RE_findings.md` did for
  the Q5 — message-id array → message→descriptor table → the 0x106 pack handler → the RAM status
  struct → the application bit that sets `ECD_nicht_verfuegbar`. Then read what gates it. The
  mechanical `{u16 id, u16 ptr}` record search that worked on the Q5 (`0xb33dc`) is too noisy on
  this image (Thumb-dense, ~80 false hits), so anchor from the TX scheduler function instead.
- If the gate turns out to be **variant/coding-conditional** in `0361` (plausible: one binary
  serves ACC part `J` and non-ACC part `H`), then re-examine our own `8R0907379BG` for the same
  conditional — that would make the Q5's floor a coding problem, not a flashing problem.

## 6. Layout: one folder per variant

The four images share nothing at byte level (§3), so each gets its own subfolder under
`ecus/esp8/` with its own firmware, Ghidra project, docs and a `variant.conf` recording the
firmware-verified facts (identity, load/RAM base, code/data ranges, signature blocks):

```
ecus/esp8/
  ghidra_scripts/            shared Esp*.java (image-agnostic)
  docs/                      cross-variant: this file
  analysis/                  cross-variant: shared_cal_anchors.csv
  8R0907379BG/               Q5 B8 -- ours (firmware/, ghidra_proj/, docs/, symbols.csv, variant.conf)
  4G0907379H_0361/           C7, flashes H + J(ACC)  <- the diff target
  4G0907379_0190/            C7, earlier revision
  4G0907379AD_0400/          C7 facelift, ESP9 -- different generation
```

`.gitignore` gained `ecus/*/*/firmware/*`, `ecus/*/*/ghidra_proj/`, `ecus/*/*/frf/` and
`*.odx`/`*.sgo`/`*.sgm` so the hard rule still holds one level deeper. (The `*.odx` rule also
closes a pre-existing gap: `ecus/simos85/frf_extract/*.odx` and the root `tcu*.odx` were
firmware containers sitting un-ignored.)

## 7. Do they share a calibration layout?  **Content: partly. Layout: no.**

### What IS shared — the container/house style (VERIFIED)

Every image ends with the identical Bosch trailer structure: `0xb6` padding, a `u32` declared
length, a `u32` magic, an 8-byte hash, then the 12-byte marker
`00 00 00 01 01 01 00 00 00 03 04 00` and the ASCII project string. Unused flash is `0xb6`-filled
in all of them (the ESP9 image excepted — it is dense). So they are unmistakably the same
vendor toolchain.

But the **signing segmentation differs**, and this is the sharpest structural difference:

| image | signature blocks | magic |
|---|---|---|
| `8R0907379BG` (Q5) | **two** — `0xb7f2c` (len `0xbd424`) and `0x133bf5` (len `0x61b28`) | `0x81820154` |
| `4G0907379_0190` | one — `0x1e7ef0` (len `0x1a5da8`) | `0x84000060` |
| `4G0907379H_0361` | one — `0x1e7ef0` (len `0x175b38`) | `0x84000060` |
| `4G0907379AD_0400` | one — `0x1e7ef0` (len `0x137410`) | `0x84000060` |

Our Q5 image carries **two independently signed segments** — an application block and a second
block ending at `0x133bf5`, i.e. the dataset is its own signing unit. The C7 images are
**monolithic**: one signed unit covering the whole `0x1E8000`. Practical consequence: on the Q5
there is a cal segment you could in principle re-sign on its own; on the C7 there is not.

### Region layout — different shape (VERIFIED, 16 KB-granular)

- **Q5:** code and data **interleaved** across `0x0–0xa2000`, then data to the end.
- **C7 `0190`/`0361`:** one **contiguous ARM code block** (`~0x8000` to `~0xd0000` / `~0xe4000`),
  then one contiguous data region, then ~350 KB of `0xb6` slack.
- **C7 `AD`:** unclassifiable by this method — it is Thumb, **and its load base is `0x18000`,
  not 0** (see `../4G0907379AD_0400/docs/can_e2e.md` §0). ~756 KB of it (`0x147000–0x200000`) is
  encrypted/compressed at entropy 7.99–8.00 and cannot be analysed at all.

### Content — a real, measurable overlap (VERIFIED)

Comparing **data regions only**, by unique 16-byte sequences:

| pair | shared 16B seqs | contiguous identical blocks ≥24 B | total identical bytes |
|---|---|---|---|
| Q5 ↔ `0361` | 6 819 (~1.4 %) | **169** (largest 275 B) | 8 835 |
| Q5 ↔ `0190` | 3 285 (~0.9 %) | 110 | 4 403 |
| `0190` ↔ `0361` | 110 575 (**~27 %**) | 2 898 | 148 202 |
| *(code regions, Q5 ↔ `0361`, for contrast)* | 159 (**0.02 %**) | — | — |

So: **the code shares nothing, but a few kilobytes of table data are byte-identical between our
Q5 and the C7.** ⚠ **Corrected 2026-08-20:** not all of it is *calibration*. The single largest
identical block (275 B at Q5 `0x0b47fc` ↔ `0361` `0x15a8a4`) is the **CRC8H2F lookup table**
(AUTOSAR poly 0x2F, the MLB E2E checksum table) — shared *library* data, not a dataset value.
The Q5 also carries a poly-0x1D CRC8 table at `0xb408c`. The rest of the identical blocks do look
like monotonic `u16` breakpoint arrays and lookup tables, i.e. Bosch-standard dataset content
carried across projects unchanged, but each anchor must be checked before being called a
calibration.

**The layout, however, does not carry across.** The offset deltas are not constant, so the tables
are relocated and reordered, not shifted. There is one partial correspondence worth noting: a
*group* of tables at Q5 `0x104df1–0x105b21` maps to `0361` `0x15a6a0–0x15b7dc` (deltas clustering
`0x54d87–0x569eb`), i.e. both builds keep that family of tables together.

### What this is good for

Not a cal transplant — that is off the table. But the 169 identical blocks are **cross-image
anchors**: a function in the C7 image that reads one of them is the counterpart of the Q5
function that reads the same table. That is a way into an image where we have no symbols.
Offsets are tabulated in `analysis/shared_cal_anchors.csv` (offsets and lengths only — no
firmware bytes). Within the C7 pair the same technique is far richer (2 898 anchor blocks),
which makes `0190` ↔ `0361` the natural place to spot what changed between revisions.

## 8. CAN architecture: Q5 (ESP8) vs the latest C7 (ESP9)

Traced in full for the ESP9 in `../4G0907379AD_0400/docs/can_e2e.md`; the Q5 side is from
`../8R0907379BG/docs/RE_findings.md`. They are **different architectures, not two builds of one**:

| | Q5 `8R0907379BG` (ESP8) | C7 `4G0907379AD` (ESP9) |
|---|---|---|
| core | ARMv5-class, mostly ARM | ARMv7, mostly Thumb-2 |
| load base | `0x0` | **`0x18000`** |
| RAM | `0x00400000` | `0x08000000` |
| analysable | whole image | 62 % (rest encrypted) |
| OS | none evident | **AUTOSAR/OSEK** (every ISR wrapped in enter/exit hooks) |
| interrupts | — | vectored controller @`0xFFFFFE04`, table @`0x133ff8` |
| CAN dispatch | message-id array `0xafae0` + `{id,ptr}` descriptors `0xb33cc`, TX scheduler `0x5bfc` → per-message pack handler via trampoline `0xa2428` | per-frame composer functions calling a shared E2E wrapper; message-object config not yet located |
| signal bit-work | `com_signal_compose 0x6b00` | generic `sig_pack 0x10129c` / `sig_unpack 0x10138a` |
| E2E | CRC8H2F table present (`0xb4800`) | explicit 5-function E2E library `0x118038–0x1180b2` |
| checksums | XOR (verified on-car seeds) | **both**: XOR *and* CRC8H2F, chosen per frame |

The practical upshot for openpilot: the newer ESP still uses the **same MLB XOR checksum**
(`chk = seed ^ bytes[1..7]`, counter in byte1's low nibble) for most frames, so the seed rule
`seed = (addr>>8) ^ (addr&0xFF)` we verified on the Q5 carries forward — but the ESP9 additionally
protects some frames with **CRC8H2F plus a per-frame data ID** (`0xD4`, `0xAC`, `0xF5` observed),
which the XOR rule cannot produce. Any tooling that assumes "MLB = XOR everywhere" will fail on
those frames.


## 9. Follow-ups completed

- Load bases corrected for all three C7 images (`0x18000`) — `docs/e2e_family.md` §1.
- The oldest C7 image was decompiled and **does follow the same CAN/E2E path** as the ESP9:
  identical five-function E2E library, identical TX wrapper shape, identical seeds — §2/§3 there.
- Handled CAN ids cross-referenced against `vw_mlb.dbc` — §5 there and
  `analysis/can_id_vs_dbc.csv`.
