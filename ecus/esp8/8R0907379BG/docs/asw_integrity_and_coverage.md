# ASW integrity: self-test hunt (a) + decompilation-coverage map (b)

Done in response to a fair challenge: the "no inline checksum" claim was over-stated. This records
exactly what was searched, what was found, and — importantly — what these searches **cannot** rule
out. Nothing here is a guarantee that a patched ASW needs no checksum repair; see "Limits".

## (b) Where undecoded code could hide (authoritative, from the reproduced project)

`EspCoverage.java` over CODE region `[0,0xa2800)` (665,600 B):
- instructions in functions: 86.2% (209,516 insns, 3,311 functions)
- defined data (literal pools / tables): 7.2%
- **UNDEFINED: 6.6% (43,701 B)** — of which `EspUndefRanges.java` classifies only **~7.8 KB as
  "code-like"** (ARM top-nibble heuristic); ~33 KB is data-like.

The notable code-like-undefined ranges (a routine *could* live here):

| range | size | note |
|---|---|---|
| 0x1a3c4 | 0x53e | large straight-line ARM (ANB control math; reads 0x4066e0). **Not a sweep** (0 loops, 0 post-index). |
| 0x74b08 / 0x66c28 / 0x69c20 | 0x478 / 0x3b8 / 0x3a0 | do not decode as coherent ARM (Thumb/data); no sweep structure |
| 0x850c0 | 0x1ec | garbage as ARM (Thumb/data) |
| 0x24354 | 0xd8 | small ARM w/ 2 local loops, bounds are local code addrs (not a flash span) |
| ~20 more | <0x100 each | too small for a full CRC routine; could hold a helper |

Separately, the Thumb **jump-table islands** (~0x11960–0x1258f and similar) are *defined
instructions not grouped into functions* — real code the decompiler couldn't functionize. A check
could in principle hide there; by structure they are BX veneers / dispatch tables.

## (a) Self-test / checksum-sweep hunt — all negative in the decoded image

Searched the raw image + the 4886-function corpus:
- **No CRC32 polynomial** (0x04C11DB7 / 0xEDB88320 / CRC32C), either endianness: 0 hits.
- **No CRC16/CRC8 table or poly used for integrity.** The only CRC in the firmware is
  `e2e_crc8_dataid(buf,8,<dataID>)` — the AUTOSAR **CAN E2E CRC8** over 8-byte frames (data IDs
  0xd2/0xd4/…), never over flash. (0x1021/0x8005 byte-hits are Thumb-opcode noise, not tables.)
- **No software accumulate-sweep** (`acc ^=/+= *ptr++` over a large range) anywhere in the corpus.
- **No function walks low flash with a large bound** (image-wide sum/CRC): 0 hits for flash-span
  loop limits (0x134000/0xbd424/0xd20c1 as bounds).
- **No hardware-CRC peripheral fed sequential flash.** The 0xfff7xxxx MMIO functions are the two
  CAN controllers and the base-ESC valve/pump drivers only; no CRC-unit feed loop.
- `_start` (0x8f440) early init just calls a CPU-mode/stack helper (0x8f4dc) repeatedly; no memory
  self-test visible in early init.
- The large code-like-undefined blobs (table above) were disassembled and are **not sweeps**.

## Verdict (calibrated)
Within the ASW image I can decode, there is **no evidence of any flash/ROM integrity self-check** —
no CRC machinery of any kind over program memory, no additive sweep, no HW-CRC feed. Combined with
the signature analysis (ASW integrity = external RSA-1024, verified by the bootloader, which is not
in this image and never read by ASW code at runtime), the **most likely** situation is that a
patched ASW would *execute* without an inline-checksum repair — but this is a **probabilistic
conclusion, not a proof.**

## Limits (what this does NOT prove)
1. **~7.8 KB of code-like-undefined bytes + the Thumb jump-table islands are not decompiled.** A
   check could hide there (the big ARM blobs examined are not sweeps, but coverage is not 100%).
2. A check using an **unusual primitive** (incremental/rolling, signature-recompute, or a custom
   non-CRC algorithm) would evade the poly/sweep heuristics.
3. The full **ERCOSEK periodic-task set** was not executed/traced end-to-end; a background self-test
   task is not exhaustively excluded (though no sweep/CRC primitive exists for one to call).
4. The **bootloader (SBOOT/CBOOT) is not in this image.** Any checksum it computes/fills/verifies —
   including a programming-dependent checksum and the flash-container (.sgo/ODX) checksum — is
   entirely outside what was analyzed. This is the most likely place a "checksum repair" would
   actually be required, and it cannot be answered without an SBOOT/CBOOT dump.

**The only way to *know* is empirical:** dump SBOOT/CBOOT and read the verify/boot path, or attempt
a trivially-modified ASW flash on the bench spare and observe the rejection/fault mode. Both are
gated by the unsolved flash-level SecurityAccess (`SECURITY_ACCESS.md`).

Reproduce: `EspCoverage.java` + `EspUndefRanges.java` (analysis/_logs/undef_ranges.log);
poly/sweep scans in scratchpad; corpus greps for `e2e_crc8_dataid`, flash-span bounds, 0xfff7 MMIO.
