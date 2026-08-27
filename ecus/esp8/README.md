# ESP8 / ESP-Premium / ESP9 — Bosch VAG brake-control images

One folder per image: they share a vendor toolchain but **no code and no addressing**
(0.02 % shared 32-byte chunks between the Q5 and the C7 — see `docs/c7_comparison.md` §3),
so nothing may be assumed to transfer between them. Each folder carries its own
`variant.conf` with the firmware-verified facts, its own `firmware/`, `ghidra_proj/` and
`docs/`. Shared across variants: `ghidra_scripts/` (image-agnostic), `docs/`, `analysis/`.

| folder | car | component | Bosch project | ACC stop&go |
|---|---|---|---|---|
| `8R0907379BG/` | **B8 Q5 (ours)** | `ESP8 quattro` | `BEG_VAG.01.004` | no — 15.0 km/h ECD floor |
| `4G0907379H_0361/` | C7 A6/A7 | `EV_ESPPremiAU57X` | `AUDI_B6.01.005` | **yes** — flashes `H` *and* ACC part `J` |
| `4G0907379_0190/` | C7 A6/A7 (earlier) | `EV_ESPPremiAU57X` | `AUDI_B6.01.005` | yes |
| `4G0907379AD_0400/` | C7 facelift | `EV_ESP9BOSCHAU57X` | `BEG_VAG.02.002` | yes — **ESP9, different generation** |

**Why this is the interesting set:** the Q5's ACC cannot brake below 15 km/h because *this ECU*
withdraws `ECD_nicht_verfuegbar` at a hardcoded `cmp #0x78` (`8R0907379BG/docs/ECD_path.md`).
The C7 images are the nearest relatives that do have 0-km/h stop&go. `0361` is the diff target:
a single binary serving both the non-ACC part (`H`) and the ACC part (`J`), so on the C7 the ACC
behaviour is a **coding/variant split inside one image**.

## Getting an image out of a container

```bash
python3 -m frf.decryptfrf --file FL_<part>_<ver>.frf --outdir <variant>/frf   # ~/tools/VW_Flash
python3 ../../core/odx/odx_extract.py <variant>/frf/FL_<part>_<ver>.odx -o <variant>/frf
cp <variant>/frf/DB_1DATA_10.bin <variant>/firmware/<part>_<ver>.bin
```

The FRF layer is the generic VAG recursive-XOR (same key as the Simos containers). The block
inside is **plaintext** — the XOR 0xFF + 0x200 header applies only to a standalone `.sgo`.

## Import into Ghidra

```bash
source ../../.env.sh
"$GHIDRA_HOME/support/analyzeHeadless" <variant>/ghidra_proj <variant> \
  -import <variant>/firmware/<img>.bin -processor ARM:BE:32:v5t \
  -loader BinaryLoader -loader-baseAddr 0x0
```

Then run `ghidra_scripts/EspFix.java` — auto-analysis fabricates functions in the data region on
every one of these images. Do not trust anything above the variant's `CODE_RANGE`.
