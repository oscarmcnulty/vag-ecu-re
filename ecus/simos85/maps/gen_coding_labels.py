#!/usr/bin/env python3
"""Generate the long-coding cell map + a VCDS-style .LBL from the Simos 8.5 image.

Everything structural here is read out of the firmware, not typed in by hand:

  * the cell -> (byte, bit, width) layout comes from the unpacker `coding_unpack_cells`
    @0x801b4d64 (transcribed once, below, as CELL_LAYOUT -- the one hand-carried table);
  * the factory default coding, the per-cell rule byte and the per-cell allowed-value
    lists are read live from the calibration region of the image.

Semantic labels live in labels.py-style LABELS below and are graded by confidence;
see analysis/coding_storage.md for how each was arrived at.

Usage: gen_coding_labels.py <image.bin> <out_dir>
"""
import sys, os, csv

CAL_RULES   = 0xa0062088   # 49 rule bytes, one per cell
CAL_DEFAULT = 0xa00620bc   # 10-byte factory default coding
CAL_ALLOWED = 0xa005ac6c   # 8 bytes per cell, 0xff-terminated allowed-value list

# cell -> (byte index, low bit, width). Transcribed from coding_unpack_cells @0x801b4d64.
CELL_LAYOUT = [
    (0x00,0,0,3),(0x01,0,3,3),(0x02,0,6,2),
    (0x03,1,0,3),(0x04,1,3,3),(0x05,1,6,1),(0x06,1,7,1),
    (0x07,2,0,2),(0x08,2,2,2),(0x09,2,4,1),(0x0a,2,5,1),(0x0b,2,6,1),(0x0c,2,7,1),
    (0x0d,3,0,1),(0x0e,3,1,2),(0x0f,3,3,1),(0x10,3,4,1),(0x2f,3,5,1),(0x11,3,6,2),
    (0x12,4,0,3),(0x13,4,3,2),(0x14,4,5,2),(0x15,4,7,1),
    (0x16,5,0,1),(0x17,5,1,1),(0x18,5,2,1),(0x19,5,3,1),(0x1a,5,4,1),(0x1b,5,5,2),(0x1c,5,7,1),
    (0x1d,6,0,1),(0x1e,6,1,1),(0x1f,6,2,1),(0x20,6,3,2),(0x21,6,5,2),(0x22,6,7,1),
    (0x23,7,0,3),(0x24,7,3,2),(0x25,7,5,2),(0x26,7,7,1),
    (0x27,8,0,3),(0x28,8,3,1),(0x30,8,4,1),(0x29,8,5,1),(0x2a,8,7,1),
    (0x2b,9,0,3),(0x2c,9,3,2),(0x2d,9,5,2),(0x2e,9,7,1),
]
# byte 8 bit 6 is the one bit of the 80 that the unpacker never reads.

RULE_TEXT = {
    0x02: "codeable (value must be in the allowed list)",
    0x06: "codeable once (allowed list + refuses later changes)",
    0x10: "LOCKED - rejected unless equal to the factory value",
    0x00: "unused",
}

# cell -> (label, confidence, decoded-to RAM globals, note)
#   CONFIRMED = read out of the firmware / already verified in this repo
#   PROBABLE  = consistent with the consumers but not proven
#   UNKNOWN   = structure known, meaning not established
LABELS = {
    0x1b: ("Cruise control system type", "CONFIRMED", "d000a756/757/758",
           "0=none 1=GRA basic cruise 2=ACC 3=F2S(not implemented). "
           "Decoded by coding_decode_cruise_type@0x801b5900; a757=LV_DCC_ENA. "
           "This image is coded 1 (GRA); the validator also accepts 2."),
    0x18: ("ESP/chassis CAN interface present", "PROBABLE", "d000a751/752/753",
           "d000a753 gates the ESP_05 (0x106) RX decoder and a 14-bit block of TX enables "
           "in can_tx_scheduler@0x80106ed8."),
    0x03: ("Drivetrain/vehicle variant class", "PROBABLE", "d000a735..73b",
           "5 exclusive classes; 122 consumers - the widest-reaching cell. Contributes the "
           "last letter (D/A/G/M/J, +1 if cell 23) of the identifier built by 0x801bd36c."),
    0x17: ("Variant sub-class (variant letter second half)", "PROBABLE", "d000a74f/750",
           "Shifts the cell-3 letter by one (D->E, A->B, G->H, M->N, J->K)."),
    0x1d: ("Vehicle bus/equipment class A|B", "PROBABLE", "d000a75a",
           "Contributes letter A or B at 0x801b60d8; gates several TX enables."),
    0x12: ("Variant parameter set index", "PROBABLE", "d000b3ba + d000a743..746",
           "Indexes six 8-entry calibration tables (0x8005b2d4/2dc/2e4/2ec/2f4, 0x80042c98) "
           "into d000b3c0..d000b3c5."),
    0x23: ("Model/market code", "PROBABLE", "d000b3bd",
           "Mapped through the 24-entry table at 0x8005afc8 to a letter at 0x801b611c."),
    0x0f: ("CAN TX group enable", "PROBABLE", "d000a740", "Gates TX bit 0x80000000."),
    0x10: ("CAN TX group enable", "PROBABLE", "d000a741", "Gates TX bits 0x2 and 0x4000000."),
    0x2f: ("CAN TX group enable", "PROBABLE", "d000a742", "Gates TX bit 0x200."),
    0x19: ("CAN TX group enable", "PROBABLE", "d000a754", "Gates TX bit 0x800000."),
    0x1a: ("CAN TX group enable", "PROBABLE", "d000a755", "Gates TX bit 0x1000000."),
    0x1c: ("CAN TX group enable", "PROBABLE", "d000a759", "Gates TX bits 0x400/0x800."),
    0x28: ("CAN TX group enable", "PROBABLE", "d000a75d", "Gates TX bit 0x10000."),
    0x29: ("CAN TX group enable", "PROBABLE", "d000a75e", "Gates TX bit 0x200000."),
    0x0e: ("Equipment flag group", "PROBABLE", "d000b3b8",
           "0..3 selects the d000a786..789 / d000b3da flag block in 0x801b6558."),
}

LBL_NAME = '8R0-907-551.LBL'

LBL_HEADER = """;
; VCDS Label File - Engine Electronics (01) - Simos 8.5
;
; Audi Q5 (8R) 3.0 TFSI / CTUC
;
; P/N: 8R0-907-551-F   (SW S8500L2000000, dataset CAS85L20)
;
; Long Coding only (10 bytes). Measuring blocks / adaptation are NOT in this file.
;
; SOURCE: reverse-engineered from the ECU flash image, not from a Ross-Tech file.
;   layout    -> coding_unpack_cells    @0x801b4d64  (10 bytes -> 49 cells)
;   semantics -> coding_decode_cruise_type @0x801b5900 (cells -> RAM flags)
;   rules     -> coding_validate_and_apply @0x801b5520 + cal tables
;   See ecus/simos85/analysis/coding_storage.md for the full derivation.
;
; READ THIS BEFORE TRUSTING A LINE:
;   The BIT LAYOUT, the FACTORY VALUE, the ALLOWED VALUES and the LOCKED/CODEABLE
;   state below are read straight out of the firmware and are reliable.
;   The English NAMES are mostly *hypotheses* - each is tagged CONFIRMED / PROBABLE /
;   UNKNOWN. Only the CONFIRMED ones have been traced end to end. Cells tagged
;   UNKNOWN are real coding cells whose meaning is not established; they are listed
;   so the layout is complete, not because the name is known.
;
; A cell marked LOCKED is refused by the ECU unless you send back the factory value,
; so changing it in the Long Coding Helper will fail with a rejected coding write.
;
; HOW THIS ECU IS CODED (from the firmware):
;   read  : UDS $22 DID 0x0600 -> 10 bytes   (0x0601 returns the length, = 10)
;   write : UDS $2E DID 0x0600 + 10 bytes    (request length must be exactly 0x0D)
;   The ECU REJECTS the coding write with NRC 0x24 unless a non-zero repair-shop /
;   tester code has been written first via DID 0xF198. Tools that do a normal
;   "Long Coding" transaction already do this.
;
; 19 of the 49 cells are hard-LOCKED by the dataset and 9 more accept only a single
; value, so only 21 cells are genuinely changeable (cell 29 only once). Anything else
; comes back as a rejected coding write no matter what you send.
;
; Record format: LC,<byte>,<bit>,<description>
;
"""


def write_lbl(path, rows, default, factory):
    out = [LBL_HEADER]
    out.append(f";  Factory coding of this image: {factory}\n;\n")
    out.append(";---------------------------------------------------\n")
    out.append(";\n; Long Coding\n;\n")
    out.append(";---------------------------------------------------\n;\n")
    by_byte = {}
    for r in rows:
        by_byte.setdefault(r['byte'], []).append(r)
    for b in sorted(by_byte):
        out.append(f";=== Byte {b}  (factory 0x{default[b]:02X}) ===\n;\n")
        for r in sorted(by_byte[b], key=lambda x: x['low_bit']):
            locked = r['rule'] == '0x10'
            n_allowed = len(r['allowed'].split()) if r['allowed'] else 0
            fixed = (not locked) and n_allowed == 1
            name = r['label'] if r['label'] != '(unknown)' else f"Coding cell {r['cell']}"
            tag = 'LOCKED' if locked else ('FIXED' if fixed else r['confidence'])
            allowed = r['allowed'] or '(none - factory value only)'
            out.append(f"; cell {r['cell']}  bit(s) {r['bit_span']}  width {r['width']}  "
                       f"[{tag}]\n")
            if fixed:
                out.append(";   single allowed value - the ECU rejects anything else\n")
            out.append(f";   factory={r['factory_value']}  allowed={allowed}  "
                       f"{r['rule_meaning']}\n")
            if r['decodes_to']:
                out.append(f";   decodes to {r['decodes_to']}\n")
            if r['note']:
                out.append(f";   {r['note']}\n")
            for i in range(r['width']):
                bit = r['low_bit'] + i
                if r['width'] == 1:
                    desc = f"{name}"
                else:
                    desc = f"{name} - value bit {i} (weight {1 << i})"
                if locked:
                    desc += " [LOCKED - must stay at factory]"
                elif fixed:
                    desc += f" [only value {r['allowed']} accepted]"
                elif r['confidence'] == 'UNKNOWN':
                    desc += " [meaning not established]"
                elif r['confidence'] == 'PROBABLE':
                    desc += " [probable]"
                out.append(f"LC,{b:02d},{bit},{desc}\n")
            out.append(";\n")
    out.append("; byte 8 bit 6 is never read by the unpacker - no cell maps to it.\n;\n")
    open(path, 'w').write(''.join(out))


def load(img, addr, n):
    return img[(addr & 0x0fffffff):(addr & 0x0fffffff) + n]

def unpack(default):
    out = {}
    for cell, by, lb, w in CELL_LAYOUT:
        out[cell] = (default[by] >> lb) & ((1 << w) - 1)
    return out

def main():
    img_path, out_dir = sys.argv[1], sys.argv[2]
    img = open(img_path, 'rb').read()
    rules   = load(img, CAL_RULES, 49)
    default = load(img, CAL_DEFAULT, 10)
    vals    = unpack(default)

    rows = []
    for cell, by, lb, w in sorted(CELL_LAYOUT):
        raw = load(img, CAL_ALLOWED + cell * 8, 8)
        allowed = []
        for v in raw:
            if v == 0xff:
                break
            allowed.append(v)
        label, conf, dest, note = LABELS.get(cell, ("(unknown)", "UNKNOWN", "", ""))
        rows.append(dict(
            cell=cell, byte=by, low_bit=lb, width=w,
            bit_span=f"{lb}" if w == 1 else f"{lb}-{lb+w-1}",
            factory_value=vals[cell], rule=f"0x{rules[cell]:02x}",
            rule_meaning=RULE_TEXT.get(rules[cell], "?"),
            allowed=' '.join(str(a) for a in allowed),
            label=label, confidence=conf, decodes_to=dest, note=note))

    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, 'coding_cells.csv')
    with open(csv_path, 'w', newline='') as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    print(f"{len(rows)} cells -> {csv_path}")
    factory = ''.join(f"{b:02X}" for b in default)
    print("factory coding =", factory)
    lbl_path = os.path.join(out_dir, LBL_NAME)
    write_lbl(lbl_path, rows, default, factory)
    print(f"label file -> {lbl_path}")
    return rows, default

if __name__ == '__main__':
    main()
