# Simos 8.5 — the UDS write (flash) path and the CAN RX / CCP-XCP dispatch, traced

Companion to `uds_dispatch.md` / `obd_read_feasibility.md`. This traces the two
flows requested at the code level and records the labels now in
`symbols_merged.csv` (source `re-trace`). Addresses are the durable evidence;
full labeled C is regenerable locally (`analysis/decompiles_labeled/`,
`annotations_r/*.json` → `ApplySymbols.java`); it is derived work and gitignored.

All addresses are cached-space (`0x8…`) unless a `0xa0…/0xafe…` alias is noted.

---

## A. The write / flash path  (RequestDownload $34 → TransferData $36 → $37)

### Call graph
```
programming_session_reflash_loop 0x801d371c
  └─ flash_driver_init 0x801f13b8 (descriptor = UDS_REFLASH_DESCRIPTOR 0x800826c0)
        · latches flash_descriptor_root, flash_segment_count(=5), flash_staging_ptr=0xc03fd3d0

[per UDS request]
flash_write_dispatch 0x801f1598 ── bounds check + cmd sig ──► flash_write_transfer 0x801f3b5e
                                                                  │ stream bytes → staging 0xc03fd3d0
                                                                  ▼ per full page
                                                       flash_program_page_exec 0x801f39b4
                                                                  ▼
                                                       flash_program_page 0x801f249e  (PMU AA/55/A0)
                                                                  ▼
                                                       verify_flash_data 0x801f1cf0

flash_erase_dispatch 0x801f14e0 ──────────────────────────────► flash_erase_segment_loop 0x801f3fb8
                                                                  │ flash_find_sector_range 0x801f1c74
                                                                  ▼ EVERY sector in segment
                                                       flash_erase_sector 0x801f2224  (PMU 80/../30)
                                                                  ▼
                                                       flash_blank_check 0x801f1704  (==0xFF, MARD)
```

### What each stage enforces (the load-bearing gates)
- **Sub-range bounds** (`flash_write_dispatch`): the only address check is
  `segment_size < offset+length-1 → NRC 0x80`. It permits a sub-range but the
  address is always `segment_base + offset` — **bounded to a declared segment**.
- **Command signature** (`reflash_cmd_signature` @0x800826d4 = bytes `53 65 ca 35`,
  u32 `0x35CA6553`): the transfer command word must match byte-for-byte in
  dispatch/transfer/program/erase, else NRC 0x02. A fixed magic, not a key.
- **Destination** (`flash_write_transfer`): `descriptor[seg].addr + off | 0xa0000000`.
  Data flow is strictly **request → staging(0xc03fd3d0) → flash**. No inverse.
- **Whole-segment erase** (`flash_erase_segment_loop`): loops every physical
  sector of the segment unconditionally — a cal write erases all 256 K to 0xFF,
  so a partial edit must re-supply the whole segment (no sub-sector erase exists).
- **Descriptor scope** (`UDS_REFLASH_DESCRIPTOR` 0x800826c0, count 5): CALIBRATION
  `0xa0040000`/256 K + DFLASH/EEPROM `0xafe00000`,`0xafe10000` only. **ASW code
  banks and the `0x0–0x20000` boot sector are in NO writable descriptor.**

Net: the write surface can flash a signed **calibration + EEPROM** and nothing
else. It cannot write ASW code, so it cannot be turned into an "install a reader
stub" primitive — independent, code-level confirmation of `obd_read_feasibility.md` §3b.

### TC1796 PMU command decode (for auditability)
- program page (`flash_program_page`): load page-assembly buf (`pmu_base+0x55f0`)
  from staging, `0xAA→[+0x5554]`, `0x55→[+0xaaa8]`, `0xA0→[+0x5554]`, `0xAA→page`,
  poll `FLASH_FSR` (0x800 PROER, 0x400 PFOPER, 0x10, 0x80000000 busy).
- erase sector (`flash_erase_sector`): `0xF5`(clear)/`0xAA`/`0x55`/`0x80`/`0xAA`/`0x55`
  then confirm `sector*0x10+0x30`; poll FSR; retry ×3.
- block CRC (`uds_validate_xfer_block` 0x801d1ebe): each 0x1e00 block self-checks
  `word[0]==~word[0x1dfc]` and `crc16(data+4,len,0xABCD)==word[0x1dfa]`.

---

## B. The CAN RX / diagnostic dispatch  (== the "CCP/XCP RX flow")

There is **no CCP/XCP slave** (confirmed in `obd_read_feasibility.md` §6a and
re-confirmed here structurally). The only request/response path on CAN is UDS:

```
CAN RX acceptance filter 0x80082f18  ─┬─ powertrain 0x100–0x17f ─► COM stack (com_process_ipdu 0x800af8bc)
                                      └─ diag 0x70a/0x719/0x71a ─► [ISO-TP transport: NOT yet isolated]
                                                                     │ reassembly + session/timing
                                                                     ▼
                                                          uds_service_dispatch 0x80024f66
                                                                     │ match SID in linked-list registry
                                                                     ▼
                                                          uds_access_gate 0x8002c3c4  (attr vs session mask)
                                                                     │ permitted?
                                                                     ▼
                                                          service handler  (SID table 0x80085e58)
```

**The structural proof (why no CCP/XCP UPLOAD can exist):** `uds_service_dispatch`
dispatches *purely* on the incoming UDS SID matching a registered 12-byte record
`{handler, arg, sid+attr}`. Nothing else reads a raw non-ISO-TP CAN mailbox and
switches on `data[0]` into a `SET_MTA`/`UPLOAD` memcpy. A CCP `0x04`/XCP `0xF5`
byte would have to be a registered UDS SID to be serviced — and it is not
(and CCP/XCP don't use ISO-TP framing anyway). `uds_access_gate` then AND-checks
the record's attr byte (`0x30/0x31/0x70/0x71`) against the active session mask
(`ctx->session & 0xc`), returning NRC 0x11 / upstream 0x33 when too low.

> NOTE: `0x801e7540` was previously mislabeled as the ISO-TP handler on the
> strength of a `0x71a` constant — which is actually a struct offset
> (`ptr + 0x71a`), not a CAN ID. That function is a periodic signal task. The
> real ISO-TP transport routine is **not yet isolated** (it feeds
> `uds_service_dispatch` from the diag COM PDUs); pinning it down is the open
> item for the RX side.

Cross-reference to the recovered SID table (`uds_dispatch.md`): the reachable,
byte-returning services are `0x22` (fixed DIDs) and `0x19` (DTCs); `0x23` has a
NULL handler; `0x35`/`0x3d`/`0x2c` are absent. So the dispatcher above can route
to nothing that returns arbitrary memory → **VR, not RD; SBOOT unreachable over CAN.**

---

## C. Variable / symbol glossary (added to symbols_merged.csv, source re-trace)

### Flash-driver state block (`0xc03fd380…`)
| addr | name | meaning |
|---|---|---|
| 0xc03fd380 | flash_descriptor_root | active reflash op-descriptor root (=0x800826c0) |
| 0xc03fd384 | flash_seg_status_array | per-segment status (idx*0x10; +0xc = FSR error accum) |
| 0xc03fd388 | flash_scratch_ptr | scratch buffer cleared after each op |
| 0xc03fd38c | flash_error_flags | global FSR error accumulator (out-of-range seg) |
| 0xc03fd390 | flash_op_program | vtable[0]: program/erase primitive fn ptr |
| 0xc03fd398 | flash_op_service | vtable[2]: WDT/comm service fn (STM_TIM3 paced) |
| 0xc03fd3a0 | flash_op_issue | vtable[4]: PMU command issue/resume fn |
| 0xc03fd3a8 | flash_service_interval | STM_TIM3 ticks between service calls |
| 0xc03fd3ac | flash_last_service_tim3 | last service timestamp |
| 0xc03fd3b8 | flash_sector_first | first sector idx of segment (erase) |
| 0xc03fd3ba | flash_sector_last | last sector idx of segment (erase) |
| 0xc03fd3be | flash_segment_count | # descriptor segments (=5); index bound |
| 0xc03fd3c0 | flash_error_latch | set 1 on any FLASH_FSR error |
| 0xc03fd3c4 | flash_staging_ptr | staging buffer ptr (=0xc03fd3d0) |
| 0xc03fd3c8 | flash_cur_write_addr | current page target (…|0xa0000000) |
| 0xc03fd3cc | flash_last_write_addr | previous page target (boundary detect) |
| 0xc03fd3d0 | FLASH_PAGE_STAGING_BUFFER | TransferData payload assembled here |
| 0xc03fd4d4 | flash_erase_pending | erase-in-progress flag (erase→program seq) |

### Descriptor / command
| addr | name | meaning |
|---|---|---|
| 0x800826c0 | UDS_REFLASH_DESCRIPTOR | reflash op-descriptor: CAL + DFLASH only |
| 0x800826d4 | reflash_cmd_signature | 4-byte magic {53 65 ca 35} gating flash ops |

### Functions
| addr | name |
|---|---|
| 0x801d371c | programming_session_reflash_loop |
| 0x801f13b8 | flash_driver_init |
| 0x801f1598 | flash_write_dispatch |
| 0x801f14e0 | flash_erase_dispatch |
| 0x801f3b5e | flash_write_transfer |
| 0x801f39b4 | flash_program_page_exec |
| 0x801f249e | flash_program_page |
| 0x801f2224 | flash_erase_sector |
| 0x801f3fb8 | flash_erase_segment_loop |
| 0x801f1704 | flash_blank_check |
| 0x801f1c74 | flash_find_sector_range |
| 0x801d1ebe | uds_validate_xfer_block |
| 0x80024f66 | uds_service_dispatch |
| 0x8002c3c4 | uds_access_gate |

## Reproduce
Decompiles: `source .env.sh && ecus/simos85/reproduce.sh` (regenerates
`analysis/decompiles_r/`). Apply these labels: the pipeline reads
`symbols_merged.csv` + `annotations_r/*.json` via `core/ghidra/ApplySymbols.java`.
The SID table and descriptor decode with the pure-Python scanners in `uds_dispatch.md`.

---

## D. The full readable-DID map (RDBI $22) and what flash each touches

Enumerated from the `$22` handler `801229b4` → shared reader `801dbd84`, whose DID
branches are selected by the constant-accessors `FUN_801b91xx` (each just
`return 0x<DID>`). **Every branch builds a small fixed-shape payload from a named
source — none takes an address+length, so none returns a flash *region*.**

| DID | bytes | data source | flash touched? |
|---|---|---|---|
| 0x2E0 | 4 | `crc32_integrity_check_8b` over a RAM comm word (`Ramd000e558`) | no — computed CRC |
| 0x2ED | 8 | `0x63`, `DAT_d000e5f8` (RAM), **one cal byte `DAT_a0040500`** | 1 byte of CAL id area |
| 0x2EE | 10 | status bitfield from RAM flags `DAT_d000e60b/c/d` + `check_and_return_value` | no — RAM status |
| 0x2EF | 6 | `process_calibration_data_801dc1c8/e8` (derived cal status) | no — computed |
| 0x2F9 | 5 | CRC32 (`crc32_reflected`) over a 0x28-byte RAM adaptation block `DAT_d000adaf..adc2` | no — computed CRC of RAM |
| 0x2FF | 0xF | `0x41`, `DAT_d000e551..556` (RAM), + **cal id words `WORD_ARRAY_80043f8b`** | few bytes of CAL id area |

Plus the DIDs routed by the top handler `801229b4` (read and/or write-whitelisted):
`0x2E1, 0x2E2, 0x310, 0x319, 0x444B, 0x600, 0x927, 0x937` (VW adaptation/coding
channels, RAM/EEPROM-backed) and the ASAM/ODX standard idents `0xF198`
(repair-shop/workshop code), `0xF19E` (ODX file id), `0xF1A2` (ODX version),
`0xF1F0/0xF1F1` (programming pre-conditions). The `0xF1xx`/box-code idents read the
**SW_ID_BLOCK at `0x80040000`** (part number `8R0907551F`, `S8500L2000000`, `CTUC…`).

### What "part of flash" the readable DIDs correspond to
Three source classes, none of them a code region:
1. **CAL identification header** — `0x80040000` (`SW_ID_BLOCK`) and a few scattered
   cal-id cells (`0xa0040500`, `0x80043f8b`): part numbers, box code, SW/HW versions,
   ODX ids. A few hundred bytes of **identity metadata that is already public in the
   FRF**. This is the entire flash surface the read DIDs expose.
2. **RAM state / adaptation** (`DAT_d000e5xx`, `DAT_d000adxx`): live status, coding,
   adaptation — not flash.
3. **Computed CRC/integrity words** (`crc32_reflected`, `crc32_integrity_check_8b`):
   checksums over RAM/identity blocks — and crucially, **none is a CRC over a
   caller-supplied range**, so there is no CRC-leak vector like the bench SBOOT
   password-region CRC trick.

⇒ The read DIDs collectively reveal **no ASW code and no boot sector** — you cannot
reconstruct any code region from them. They are exactly the "identify the box for a
virtual read" surface, and the identity they return is the same you already have
from the FRF.

## E. Is the ISO-TP transport a path to a full read? (assessed, not a native door)

Short answer: **not a native read path, and not a promising exploit lead relative
to the bench route.** Evidence:

- **Read length is handler-controlled, not requester-controlled.** Every DID handler
  sets the response length itself (`*param_3 = 4/6/8/10/0xF/5`) and fills a
  handler-owned buffer (`param_2`) field-by-field. The transport transmits exactly
  that many bytes. The requester supplies a DID, **never an address or a length**, so
  a legitimate request cannot be coerced into returning adjacent memory.
- **No address is ever computed from the request** in the read path — unlike a
  `ReadMemoryByAddress` handler, which is precisely why `0x23` being a NULL stub
  matters.
- **So ISO-TP only becomes a read via a memory-corruption bug** in the *request*
  reassembly (e.g. a FirstFrame length overflowing a fixed reassembly buffer → write
  overflow → code execution → then read flash). That is an RCE hunt, not a read
  service. It is worth noting but is **low-value here** because: (a) it is speculative
  — no such bug is known; (b) developing it reliably would itself need the ASW/boot
  code you're trying to read; and (c) if it worked it would yield the same image the
  bench SBOOT/BSL dump gives directly and deterministically.
- **Caveat / open item:** the actual ISO-TP transport routine is **not yet isolated**
  in this corpus (see §B note). A rigorous
  "is the reassembly buffer bounded?" answer needs that function pinned down first. If
  we ever want to close the RCE angle for real, that is the prerequisite — but it
  ranks below the bench dump on the priority list.
