# Recovered dispatch/config tables (from `uds_dispatch_recovery.md`)

Results of executing the recovery plan. Each section is tagged with the technique that
produced it (A = static flash-descriptor decode, B = init-trace, C = `SymbolicPropogator`
edge-resolution, D = emulation) and CONFIRMED (read from the bin) vs **inference**.

| Target | Technique | Status |
|---|---|---|
| 3. Writable flash window | **A** | **DONE** (below) |
| 1. SID → handler + level | B→A→C | pending |
| 2. `$27` seed/key | C | pending |

---

## Target 3 — the writable flash window (Technique A, CONFIRMED from the bin)

Two flash-descriptor structures decode directly out of `8R0907551F_Original.bin`. Both are
lists of **20-byte segment records** `{flags, addr, size_mask, 0, back_ptr}` where the
programmable segment is `[addr & 0x0fffffff | 0x80000000, +size_mask+1)`. Addresses use the
TC1796 non-cached aliases (`0xa00xxxxx` PFLASH, `0xafexxxxx` DFLASH); mask them to the cached
`0x80…` image space. The nodes are walked by the step-dispatch trampoline
`task_dispatch_loop`@`0x800aa018` (`(*node[0])(node[1])`), i.e. these are flash **operation
step-lists** (erase/program/verify), with the concrete flash ops at `0x801d1926/1930/1980`.

### 3a. Master flash-geometry map `@0x80030268` (the full programmable layout)
The complete PFLASH+DFLASH sector geometry the flash driver knows about:

| segment (0x80… image) | size | region |
|---|---|---|
| `0x80020000` | `0x20000` (128K) | init / vector block |
| `0x80040000` | `0x40000` (256K) | **calibration** (`CAL_LO/HI`) |
| `0x80080000` | `0x80000` (512K) | ASW bank 0 (`0x80000–0x100000`) |
| `0x80100000` | `0x80000` (512K) | ASW bank 1 |
| `0x80180000` | `0x80000` (512K) | ASW bank 2 (…`0x200000`) |
| `0xafe00000` + `0xafe10000` | 64K each | DFLASH (EEPROM emulation) |

**This tiles `0x20000 → 0x200000` exactly — the boot sector `0x0–0x20000` (SBOOT/CBOOT) is in
NO programmable descriptor.** That is the geometric confirmation, independent of the RSA/CRC
story, that the boot sector is not writable through the normal flash driver — consistent with
it being blank in every OBD read and only reachable via the bench SBOOT/BSL path
(`obd_read_feasibility.md` §1, §3).

### 3b. The UDS-reflash op-descriptor `@0x800826c0` (what the diagnostic reflash path writes)
The programming-session executor `801d371c` hands the flash driver `801f13b8` the descriptor
root at **`0x800826c0`**, whose header is `count = 5` followed by segment records. Decoded, its
five segments are:

| segment | size | region |
|---|---|---|
| `0xa0040000` → `0x80040000` | `0x40000` (256K) | **calibration** |
| `0xafe00000` / `0xafe10000` (×2 each — erase + program passes) | 64K | DFLASH / EEPROM |

**So the OBD/UDS reflash path wired at `0x800826c0` programs calibration + EEPROM only — the
ASW code banks (`0x80080000/0x80100000/0x80180000`) are present in the master geometry map
(3a) but are NOT in this reflash descriptor's window.**

### What this establishes (refines `obd_read_feasibility.md` §3b/§6)
- The write path is **not** an arbitrary-address writer: it is scoped to a fixed descriptor
  of predetermined segments (as §6 inferred from the write-only transfer module), and that
  descriptor is **cal + EEPROM**. This is exactly the Pcmflash tuning surface — you can flash
  a modified *calibration* and adapt EEPROM, and nothing more, through this path.
- It **cannot write ASW code**, so it cannot be turned into the "install a reader stub"
  primitive that Door-2 patch-and-read needs (§2) — an independent, code-level confirmation of
  §3b, now not resting on the RSA-signature argument alone.
- **inference:** ASW reprogramming, where supported at all, must use a different (programming-
  session, signature-gated) descriptor built over the 3a geometry map; locating that descriptor
  and its auth is future work, but it does not widen the *read* surface either way.

### Reproduce
Pure Python over the image (no Ghidra) — scan for `{addr∈flash-alias, size_mask=2^n−1}` 20-byte
records, or dump `0x80030258…` and `0x800825c0…0x800826c0`. Regenerable from
`firmware/8R0907551F_Original.bin`.

---

## Targets 1 & 2 — pending (Techniques B/C/D)
The SID→handler+level table (`DAT_d00005c8` 2-level `0x44`/`0x1c` records via `801d8590`) and
the `$27` seed/key still need the `ResolveDispatchTables` edge-resolution pass and/or
emulation, per `uds_dispatch_recovery.md`. Nothing here changes the read conclusion: the write
window is cal+EEPROM, and there is still no `$23`/`$35`/CCP/XCP read path.
