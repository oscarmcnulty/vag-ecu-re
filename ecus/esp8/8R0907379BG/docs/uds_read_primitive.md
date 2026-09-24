# ESP8 8R0907379BG — UDS memory-read primitive (SBOOT-leak recon)

Goal: can we leak SBOOT/CBOOT over CAN via a UDS memory-read/upload service, avoiding a die-level
dump? Status: **0x23/0x35/0x3D are declared in the ECU's diagnostic service configuration, but no
statically-reachable executor for them exists in the ASW image; whether they answer at runtime (and
whether their address check permits the boot region) is empirically open and must be probed on the
bench.**

## Service configuration tables (byte-verified)

Two 0x00-terminated Dcm service tables, 12-byte records. These are genuine service configuration
(not the dense UDS-SID-constant reuse elsewhere in this firmware): SIDs are strictly ascending and
form two coherent protocol sets, the mask bytes cluster by service class, the handler pointers are
Thumb-odd code addresses, and the transfer trio's sub-config pointers are sequential
(0x34→0xbd948, 0x36→0xbd94c, 0x37→0xbd950, 4 bytes apart) — a generated layout.

**Table A @0xb4be4 (KWP2000 set)** — record `{SID, mask1, mask2, 00, handler_ptr, subcfg_ptr}`,
terminates @0xb4cb0. SIDs: `10 12 14 18 21 22 27 2E 31 33 32 34 35 36 37 3B 82`
(includes **0x35 RequestUpload**). Mask example: read-group 0x12–0x21 all `a0 39`; write/security
group 0x22/0x27/0x2E all `b0 3d`.

**Table B @0xb4d80 (UDS set)** — record `{SID, mask, 00, 00, handler_ptr, subcfg_ptr}`, terminates
@0xb4e1c. SIDs: `10 1A 23 30 31 34 36 37 3D 3E 81 82 83`
(includes **0x23 ReadMemoryByAddress** and **0x3D WriteMemoryByAddress** + the `34/36/37` transfer
trio). 0x23/0x3D carry mask `0xa0` (high bit = security-gated).

DID-based services (0x22 read / 0x2E write) use a separate table `diag_did_table @0xb44e4`
(identity/coding DIDs only: 0x0405–0x0408, 0xF1xx; Table2 @0xb4598 adds 0x0601 + F181/F187/F189/
F197/F1AA).

## Dispatch and handlers are boot-installed / seg2

Nothing in the image references 0xb4be4 or 0xb4d80 as a 32-bit literal, and several handler
pointers land mid-function (e.g. the 0x23 row's handler_ptr 0x987f4 is inside a status-packer).
This is the firmware's standard **boot-installed-pointer** pattern — the same one seen in the
RxIndication table, the COM object table, and the region table — where the operative dispatch and
handler entrypoints are patched in at boot or live in the seg2 Dcm stack (file >0xbb045,
VMA=fileoff+3) that is not cleanly disassembled. So the service *config* is in the image but the
service *code* cannot be statically followed.

## Statically-reachable diag handlers read only fixed/indexed data

Anchoring on the verified diag response buffer `diag_resp_buf 0x401854` (confirmed by its
part-number DIDs) and enumerating every handler that writes it gives the full set of
statically-reachable diagnostic handlers:

- DTC list build + status sort `FUN_000c71ac`; DTC-info-by-index (0x19) `FUN_000dcdb4`
  (16-byte records)
- status/measurement responses `FUN_000dd004` / `FUN_000ddf5c` / `FUN_000d2090`
- checksum `FUN_000dcd3c` — sums a **fixed** base (`*0x40195C`, initialised to flash 0x61B28 by
  `FUN_000dd004`), length ≤0x400; the caller cannot supply the base, so this is **not** a
  memory-dump oracle
- split-response + request parse `FUN_000d5ab8` / `FUN_000dd378`; response TX `FUN_000dbe90` /
  `FUN_000dde68` / `FUN_000ddf0c`
- DID reads (0x22) via `diag_did_table` — fixed identity/coding sources

None parse an addressAndLengthFormatIdentifier or read a request-supplied address. So there is
**no statically-reachable arbitrary-address read executor or oracle** in the image; the real 0x23
executor, if wired at runtime, is behind the boot-installed dispatch.

## Security

Programming-level security (SA2) is bootloader-side: the SA2 seed/key constants 0x974C58AB /
0x98765432 are present only in the `.sgo` container header, **absent from the `.bin` body**
([[abs-sa2-key]]). The app-level 0x27 seed/key algorithm is not statically resolved in this image.
Since 0x23/0x3D are security-masked (0xa0), an app-mode read likely needs SecurityAccess whose key
we do not yet have.

## Feasibility and bench test

SBOOT/CBOOT are not in this image (ASW+CAL only) and sit at a flash address the image does not
cover. A 0x23 leak needs (1) the service to actually answer, (2) its address check to permit the
boot region, and (3) knowledge of the boot region's mapped address (a permissive 0x23 finds it by
scanning). All three are decidable directly on the bench:

1. Comms on FlexCAN module B (0x6b4 req / 0x6b8 resp — [[esp8-bench-pinout]]).
2. `0x10 0x03` (and `0x10 0x02`); SecurityAccess.
3. `0x23` at a known-good address (a mapped RAM/flash address) to confirm it answers and learn the
   accepted addr/len format; then walk toward candidate boot addresses (low flash below the app).
4. Try `0x35` RequestUpload (Table A) the same way.

Ties: [[esp8-flash-signature]] (why we want SBOOT — RSA-1024, can't re-sign), [[abs-sa2-key]]
(prog unlock), [[esp8-bench-pinout]] (how we talk to it), [[esp8-abs-firmware]] (bare-die COB, no
JTAG breakout — why the wire path matters).
