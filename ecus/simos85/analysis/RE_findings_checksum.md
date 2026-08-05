# Simos8.5 (8R0907551F) — Reverse Engineering Findings: Checksum / Flashing Logic

ECU: Audi Q5 3.0 TFSI, Continental/Siemens **SIMOS 8.5**, project **S859300C**
MCU: Infineon **TC1796** (TriCore v1.3), little-endian
Analyzed image: `8R0907551F_Original.bin` (2 MB), load base **0x80000000**
Tooling: Ghidra 12.1.2 (`tricore:LE:32:tc176x`) + pyghidra. The corpus has grown well past
what bare auto-analysis finds; `analysis/function_entries.txt` is the current entry set.

---

## 1. Memory layout (of the 2 MB OBD image)

| File offset        | Vaddr                 | Content                                              |
|--------------------|-----------------------|------------------------------------------------------|
| 0x00000 – 0x20000  | 0x80000000–0x80020000 | **Bootloader (SBOOT/CBOOT) — BLANK in OBD read**     |
| 0x20000 – 0x30000  | 0x80020000–0x80030000 | Init/vector pointers (entry ptrs at 0x20000)         |
| 0x40000 – 0x70000  | 0x80040000–0x80070000 | **Calibration / maps** (where Stage1/2 differ)       |
| 0x90000 – 0x1F0000 | 0x80090000–0x801F0000 | **Main ECU-SW code**                                 |

Software-ID block at vaddr 0x80040000: `8R0907551F`, `S8500L2000000`, `CTUC`.

> Note: `0x0–0x20000` is the protected boot sector. OBD/Pcmflash reads do **not**
> include it, so the flash-programming verification code that lives in SBOOT/CBOOT
> is **not present** in this dump (see §4).

---

## 2. CRC32 primitive (FOUND, verified)

- **CRC32 lookup table** at vaddr **0x8009083c** (file 0x9083c), 256 entries / 1 KB.
  Verified byte-for-byte against the standard reflected polynomial **0xEDB88320**
  (zlib / PKZIP CRC32).
- **CRC32 routine** `FUN_801dc544` (vaddr 0x801dc544):

```c
uint crc32(byte *data, uint len) {          // standard zlib CRC32
    uint crc = 0xFFFFFFFF;
    for (uint i = 0; i < len; i++)
        crc = table_0x8009083c[(*data++ ^ (crc & 0xff))] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFF;                 // init=FFFFFFFF, reflected, xorout=FFFFFFFF
}
```

- Callers in the ASW: `FUN_801dce30` (an 8-byte runtime integrity check) **and** the Mode 09
  **CVN engine `FUN_800297ea`**, which runs this CRC32 over the SW/cal component segments and
  compares to the stored references at `region+0x304` (CAL ref `0xA92A60BC` @`0x80040304`).
  → In this image the table-driven CRC32 is used at **runtime** (integrity check + the OBD-II
  CVN surfaced to smog tools — see `mode09_calid_cvn.md`), not as the flash programming
  checksum (that path is in the bootloader, absent here). The CVN reference lives in a `+0x304`
  descriptor, **not** interleaved in the cal payload, so "no static cal checksum in the maps"
  (below) still holds.

The lone inline `0x04C11DB7` constant at file 0x311b4 is **unrelated** (it falls in a
small bit-field helper) — a red herring.

---

## 3. Reprogramming / checksum architecture (from Funktionsrahmen, Ch.18)

Source: `Simos8.5.pdf` (Continental Funktionsrahmen, project S859300C), pages 2677–2690.

- **SW components** (p.2682): `SBOOT`, `CBOOT`, `ECU-SW`, `Calibration`.
  Each may carry a *reference*, *RSA security keys*, and a *CRC*.
- **Repro status bitfield** (p.2685):
  - bit **#15** = "Checksum of **Calibration** data is correct"
  - bit **#11** = "Checksum of **ECU-SW** is correct"
  - bit **#31** = "Checksum of every SW part is correct"
  → Calibration and ECU-SW each have an independent **CRC** to satisfy.
- **Block content format** for verification (p.2688): each block is
  `[8-byte BIG-ENDIAN header: start_addr(u32), size(u32)] + data`. Areas may consist
  of several non-contiguous ranges.
- **Security (RSA)** (p.2686–2689): RSA-1024 signatures, public exponent 0x10001.
  - Key ID **0x73** = Revival/SW-component signature check (reprogramming).
  - Key ID 0x6E = supplier reprogramming auth; 0x74 = switchover.
  - Fingerprint copied to label `_lc_u_FINGERPR_START` (p.2690).
- Flash unprotect during repro via `ICS_TUNP_ManageFLS_FlashAccess` (p.2680/2683).

**Implication for tuning:** modifying calibration requires recomputing the
**Calibration CRC** (standard CRC32) and writing it to its stored location so repro
status bit #15 stays set. RSA signatures (key 0x73) are a separate boot-level
protection; OBD cal flashing tools (Pcmflash module named in the WinOLS project)
handle the accepted path.

---

## 4. RESOLVED: there is NO embedded static calibration checksum in this image

Verified by (a) decompiling all three checksum primitives and tracing their callers, and
(b) exhaustive 3-file matching. Conclusion: **the running application does not store or
recompute a static CRC over the calibration.** Calibration integrity is enforced at
**flash-write time** by the resident flash driver, which CRC-checks the *streamed* bytes
during the UDS reflash — not a field persisted in the image.

### The three checksum routines (exact parameters, tables re-derived from the bin)

| routine            | addr        | table       | poly                | reflect | init       | xorout     |
|--------------------|-------------|-------------|---------------------|---------|------------|------------|
| `crc32_reflected`  | 0x801dc544  | 0x8009083c  | 0x04C11DB7          | in+out  | 0xFFFFFFFF | 0xFFFFFFFF | (= standard zlib CRC32, check "123456789" → 0xCBF43926)
| `crc16_table`      | 0x800a59f0  | 0x800808ec  | 0x8005 (refl 0xA001)| in+out  | **0xABCD** | none       | (ARC-family with non-standard init)
| `checksum8_table`  | 0x800a5a18  | 0x80080aec  | 0x2F                | no      | 0xFF       | 0xFF       | (CRC-8/AUTOSAR; **0 callers — unused here**)

### What the callers actually checksum
- **`crc16_table`** — 4 callers (`FUN_801d22a0/801d1ebe/801d2002/801d283c`), all pass
  init **0xABCD** over **RAM download buffers** during UDS RequestDownload/TransferData.
  e.g. `FUN_801d1ebe` validates 0x1e00-byte transfer blocks:
  `word[0]==~word[0x1dfc]` and `crc16(data+4, len, 0xABCD)==word[0x1dfa]`.
  Pointer/length come from the streamed bytes → **not constant cal addresses.**
- **`crc32_reflected`** — 1 caller (`FUN_801dce30`), CRC32 over an 8-byte RAM comm word.
- **`checksum8_table`** — no callers.

### Searches that returned NEGATIVE (high confidence)
- Scenario A (per-version-corrected): CRC16(0xABCD/0/0xFFFF), CRC32, sum16/sum32/xor32/
  bytesum over ranges 0x40000→0x80000 (step 0x100/0x400), LE/BE 1/2/4-byte at every
  differing offset, 3-file simultaneous → **no match**.
- Scenario B (self-referential, field zeroed): only isolated all-three-differ words are
  inside changed maps → **no match**.
- Scenario C (uncorrected/identical): CRC32/CRC16 over ~9000 cal ranges in Original
  searched anywhere in the image → only random-rate coincidences. Cal is **not** stored
  as CRC-trailered 0x1e00 blocks (0/34).

### Practical meaning for tuning
- The three WinOLS tunes differ **only in map data, with no corrected checksum field** —
  exactly what you'd expect, because nothing in the *application* needs a corrected cal CRC.
- The integrity gate is the **flash loader's per-block CRC-16 (poly 0xA001, init 0xABCD)**
  computed over the transferred stream, plus whole-image checks in the **FBL/bootloader**
  (file 0x0–0x20000, **blank in this dump**) and RSA signatures (§3).
- So a modified cal flashed through the normal tool path (Pcmflash module named in the
  `.ols`) is accepted via that streamed CRC — there is no static cal-CRC word to patch in
  the file itself.

---

## 5. Where this now lives

The scratch `track_*` CSVs and `proj_named/Simos85` this section used to list were
one-off outputs under `/tmp` and are gone. Their content was folded into the committed
store, which is what to read instead:

- Labeled Ghidra project — rebuild with `ecus/simos85/reproduce.sh` (nothing is committed
  pre-built; the project is regenerated from the metadata below).
- Function names/comments — `analysis/symbols_merged.csv` (check the `source` column).
- Function entry points — `analysis/function_entries.txt`.
- Calibration objects — `maps/simos85.a2l`, the canonical store, with per-object evidence
  and confidence in each `<description>`.

## 6. Calibration map engine (for map work)

- 1D curve reader: `kl_interp_u16` @0x800a5f40 (linear), `kl_search_u8/u16`
- 2D map reader (Kennfeld): `kf_interp_u16` @0x800a5fc0 (bilinear), `kf_interp_u8`
- Maps are reached via a **descriptor-table framework**: central accessor
  `FUN_800a8ff0` (16-byte descriptors, `id*0x10` → data pointer), dispatch via
  `FUN_801d977c`. Map dimensions live in descriptor metadata, not at the data pointer.
- All 26 tuner-modified maps are cataloged with dims/cell-width in `track_b_known_maps.csv`.
