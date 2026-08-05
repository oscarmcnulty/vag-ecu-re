# Legislated OBD-II Mode 09 (CALID / CVN) — the smog-inspection read path

How a generic OBD-II / smog scan tool reads the **calibration identity** from this ECU, and —
the tamper-relevant part — how the **CVN** is produced. This is the SAE J1979 / ISO 15031
"Mode 09 Vehicle Information" path, entirely separate from VW's manufacturer UDS DIDs. All
addresses read from the committed `firmware/8R0907551F_Original.bin`.

## The request
A California BAR / OBD-II inspection uses the **generic** protocol, not VAG diagnostics:
- CAN ISO-15765-4, functional **`0x7DF`** (broadcast) or physical **`0x7E0`** → response **`0x7E8`**
  (config blocks `0x80082a70` and `0x8002fe24`; VW manufacturer PDUs `0x70a/0x719/0x71a` are a
  *different* path).
- Service **`0x09`**, InfoType **`0x02`** VIN, **`0x04`** CALID, **`0x06`** CVN.

## The dispatch chain (confirmed)
CAN → ISO-TP → UDS service table `0x80085e58` → service dispatcher `80123a28` → **mode**
dispatcher `FUN_801ba9c8` → **Mode 09 handler `FUN_801ba514`** → InfoType table `0x8008DEF0` →
leaf handler.

- SID table `0x80085e58`, record `@0x80085ee4` = `{attr 0x70, SID 0x09, handler 0x80123a28}` —
  Mode 09 is a legislated, unauthenticated service.
- `FUN_801ba9c8` branches on the OBD **mode** byte (`0x01→801bb17c … 0x09→801ba514 … 0x0a`),
  each gated by the supported-mode bitmap `DAT_d000728c` (mode 9 = bit `0x100`).
- `FUN_801ba514` writes the response SID `0x09 + 0x40 = **0x49**` (the J1979 positive-response
  tell), then for each requested InfoType searches the **8-byte-record table at `0x8008DEF0`**
  (`{InfoType, fn_ptr@+4}`, 6 entries) and calls the leaf `(*fn)(out, &len)`:

| InfoType | meaning | leaf |
|---|---|---|
| `0x00` | supported-InfoType bitmap | `FUN_801ba658` |
| `0x02` | VIN | `FUN_801ba6a4` |
| **`0x04`** | **CALID** | **`FUN_801ba6b4`** |
| **`0x06`** | **CVN** | **`FUN_801ba764`** |
| `0x08` | in-use performance tracking | `FUN_801ba7f8` |
| `0x0a` | ECU name | `FUN_801ba830` |

> Correction to an easy mislead: `FUN_801ba9c8` is the **mode** dispatcher, not an InfoType
> dispatcher, and the `*pcVar4 == 0x04` branch in `80123a28` is **Mode 04 (ClearDTC)**, not
> CALID InfoType 04. The CALID/CVN selection is the separate `0x8008DEF0` table above.

## CALID (InfoType 0x04) — `FUN_801ba6b4`
Emits `count` + N×16-byte CALID blocks, one per set bit of the SW-component mask
`bRam8008ded4` (a **read-only flash constant `0x2d`** @`0x8008ded4`). With `0x2d`, `count = 1`
and the single 16-byte block is built by **`FUN_801bd36c`** from **SWID flash fields**: bytes
0–7 from the part-number region `0x80040060…`, bytes 8–11 from `0x80040080…`, bytes 12–15 from
four state getters (`FUN_801b60d8/611c/60fc/6158`, ASCII flag bytes).

- **The Mode 09 CALID is this *synthesized* string, not the clean `"S8500L2000000"`.** The
  `"111S8500L2000000"` array (3×16 @`0x80040020/30/40`) is the internal **calibration self-ID
  label**, read by `FUN_801b4a18`/`801b49d0` for software matching at init — never reached by the
  Mode 09 leaf. (Two other block builders, `FUN_801bd238`=`" TEST CBOOT NAME"` /
  `FUN_801bd330`=`"  TEST SPEC NAME"`, are placeholders whose mask bits are off.)

## CVN (InfoType 0x06) — a background CRC32-over-segments, latched to RAM
Handler **`FUN_801ba764`** emits `count` + 4-byte CVN(s) **big-endian**, read from RAM cells
`DAT_d00069c8…dc` (one per set component bit; `0x2d` → the single combined word `DAT_d00069c8`).
Those cells are **not** computed at request time — `FUN_801ba2e4` → `get_checksum_value`
@`0x80022e50` copies a **precomputed** word out of the diagnostic checksum RAM array
`0xC03FC1F8[idx]`.

The value there is produced by a **background/scheduled checksum task `FUN_800297ea`**, which
walks per-component segment descriptors and runs **`crc32_reflected` @`0x801dc544`** — the
standard **zlib CRC32** (poly `0xEDB88320`, table `0x8009083c`). So **the CVN is a CRC32 over
the calibration (and ASW/CBOOT) segments.** Covered ranges + the stored **reference CRC32** live
in flash per component at `region+0x304` (`{ref_crc, seg_count, {start,end}…}`):

| component | reference CRC32 | @ | coverage |
|---|---|---|---|
| **CAL** | **`0xA92A60BC`** | `0x80040304` | `[0x40000–0x402FF] + [0x40400–0x7E6FF]` (self-excludes its `0x300` descriptor) |
| ASW | `0xEFB64C0F` | `0x80080304` | ASW banks |
| INIT/CBOOT | `0xCDAACEB6` | `0x80020304` | init/vector |
| BOOT | `0` | `0x80000304` | SBOOT blank in OBD image → not checksummed |

Tamper comparison **`FUN_801ba49c`**: computed-in-RAM vs the stored reference; a mismatch sets
`UNK_d000b46d` and **withholds the CVN** (pending).

## Smog / tamper implication
- A **calibration change alters the CAL CRC32.** A tune flashed through the normal signed-reflash
  path re-establishes a matching computed value *and* reference (`0x80040304`), so the reported
  CVN is self-consistent; an out-of-band patch that changes cal bytes without updating the
  latched/reference words is **detectable** (computed ≠ reference → CVN withheld / repro-status
  clears). This is the mechanism BAR relies on: reported `CALID + CVN` vs the certified value.
- Because CAL and its reference are **both in the writable cal region** (`0x80040304` is inside
  `0x40000–0x80000`), the reference is not tamper-proof against a full reflash — it is a
  *consistency* check, not a signature. (The cryptographic integrity is the RSA boot signature,
  separate; see `obd_read_feasibility.md`.)

## Refines `RE_findings_checksum.md §4`
§4 lists `crc32_reflected`'s only caller as `FUN_801dce30` (an 8-byte runtime check) and reads the
table-driven CRC32 as "runtime, not the programming checksum." That stands for the *programming*
path, but there **is** a second consumer: the **Mode 09 CVN engine `FUN_800297ea`** runs the same
CRC32 over the SW/cal segments and compares to the flash references at `region+0x304`. So a
CRC32-over-cal *does* exist at runtime as the CVN — just not as a field inside the cal payload
(§4's "no static cal checksum in the image" is still correct: the reference sits in a `+0x304`
descriptor, not interleaved in the maps, and no per-request recompute gates a write).

## Key addresses
Mode 09 `FUN_801ba514`; InfoType table `0x8008DEF0`; CALID `FUN_801ba6b4`→`FUN_801bd36c`
(SWID `0x80040060/80`), mask `bRam8008ded4=0x2d`; CVN `FUN_801ba764`→`FUN_801ba2e4`→
`get_checksum_value 0x80022e50`→RAM `0xC03FC1F8[idx]`; compute `FUN_800297ea`→
`crc32_reflected 0x801dc544` (table `0x8009083c`); references `0x80040304` (CAL `0xA92A60BC`),
`0x80080304`, `0x80020304`; compare `FUN_801ba49c`; CAN `0x7DF/0x7E0/0x7E8`
(`0x80082a70`,`0x8002fe24`).
