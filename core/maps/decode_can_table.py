#!/usr/bin/env python3
"""Decode the generated COM stack's CAN message table into an ID -> signal -> RAM map.

The problem this solves: `core/ghidra/DecodeComBindings.java` finds the 40-byte signal descriptors by
*content* (callback + mask), which recovers each signal's RAM target and its bit position -- but NOT
which CAN message it belongs to. The descriptors live in one flat pool, so adjacency tells you nothing.

    message record, base 0x80030c38, stride 0x30, 113 records
      +0x01  n_bool   number of 20-byte boolean descriptors owned by THIS record
      +0x02  n_sig    number of signal-block entries owned by THIS record
      +0x04  -> first 20-byte BOOLEAN descriptor record   (stride 0x14)
      +0x08  -> signal block                              (stride 0x0c)
      +0x0c  CAN identifier (11-bit)
      +0x20  pre-TX callback

    signal block entry: +0x00 points at (40-byte descriptor + 0x18), i.e. straight at the descriptor's
    `target` field -- NOT at the record start. Subtract 0x18 to get the record.

    40-byte descriptor: +0x18 RAM target, +0x1c start_bit, +0x1d bit_len, +0x1e type
    20-byte boolean:    +0x00 RAM target, +0x04 = 0xffff | (destBit << 8) | srcBit

Bit numbering is LSB-first / Intel throughout, proved from the TX assembler FUN_8008a3f8
(0x8008a6be-0x8008a706: `frame64 |= (v & ((1<<len)-1)) << start_bit`, stored with st.d on a
little-endian core) and the RX extractor FUN_80089dac (0x80089dc6-0x80089dec: byte = sb>>3,
bit = sb&7). So frame bit n = payload byte n>>3, bit n&7, and a signal of length L at start_bit S
occupies frame bits S..S+L-1 with value bit k at frame bit S+k. There is no MSB-first path.

TWO CORRECTIONS THIS FILE ONCE GOT WRONG, both worth stating because each produced a confident
false conclusion:

  1. The base was recorded as 0x800312d0 with a 48-record extent. That is a SUB-WINDOW (records
     47..94) of a 113-record table, and it silently hid 65 messages including 0x100 (ESP_01, which
     carries ESP_v_Signal) and 0x102. "Absent from the table" was therefore an unreliable negative.
  2. Worse, the boolean pointer was read at +0x2c relative to that wrong base, which is
     `true_record + 0x34` -- i.e. the NEXT message's boolean pointer. Every boolean binding in the
     repo was attributed to the wrong message, off by one. That is what made ESP_05's
     ECD_nicht_verfuegbar (0x106 frame bit 33 -> 0xd000ab42 bit 5) look like it belonged to 0x101,
     and led to a months-long search for an internal 15 km/h threshold that does not exist.

The corrected binding is self-checking: n_bool/n_sig are explicit fields, so the decoded runs must
match the declared counts exactly (they do, for all 113 records), and with the fix ZERO boolean
descriptors collide with a multi-bit field across the ACC/TSK messages -- the old binding collided
systematically.

    python3 core/maps/decode_can_table.py <image.bin> [--table 0x80030c38:0x80032168]
                                          [--base 0x80000000] [--csv out.csv] [--id 0x106]
"""
import argparse
import csv
import struct
import sys

MSG_STRIDE = 0x30
SIG_STRIDE = 0x0C
BOOL_STRIDE = 0x14
DESC_TARGET_OFF = 0x18   # signal-block entries point here, not at the record start


class Image:
    def __init__(self, buf, base):
        self.buf, self.base = buf, base

    def ok(self, addr, n=4):
        return self.base <= addr and addr - self.base + n <= len(self.buf)

    def u32(self, addr):
        return struct.unpack_from('<I', self.buf, addr - self.base)[0]

    def u8(self, addr):
        return self.buf[addr - self.base]


def messages(img, lo, hi):
    """Yield one dict per message record."""
    for rec in range(lo, hi, MSG_STRIDE):
        if not img.ok(rec, MSG_STRIDE):
            break
        yield {'rec': rec, 'n_bool': img.u8(rec + 1), 'n_sig': img.u8(rec + 2),
               'bool_ptr': img.u32(rec + 4), 'sig_blk': img.u32(rec + 8),
               'can_id': img.u32(rec + 0x0c)}


def signals(img, m):
    """40-byte descriptors: exactly n_sig of them, from the signal block."""
    for i in range(m['n_sig']):
        ent = m['sig_blk'] + i * SIG_STRIDE
        if not img.ok(ent):
            return
        ptr = img.u32(ent)
        if not ptr:
            continue
        desc = ptr - DESC_TARGET_OFF
        if not img.ok(desc, 0x28):
            continue
        yield {'kind': 'signal', 'desc': desc, 'target': img.u32(desc + 0x18),
               'start_bit': img.u8(desc + 0x1c), 'bit_len': img.u8(desc + 0x1d),
               'type': img.u8(desc + 0x1e)}


def booleans(img, m):
    """20-byte boolean descriptors: exactly n_bool of them, contiguous from bool_ptr."""
    for i in range(m['n_bool']):
        rec = m['bool_ptr'] + i * BOOL_STRIDE
        if not img.ok(rec, BOOL_STRIDE):
            return
        f1 = img.u32(rec + 4)
        yield {'kind': 'bool', 'desc': rec, 'target': img.u32(rec),
               'start_bit': f1 & 0xff, 'bit_len': 1, 'type': (f1 >> 8) & 0xff}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x80000000)
    ap.add_argument('--table', default='0x80030c38:0x80032168',
                    help='message table as LO:HI vaddrs')
    ap.add_argument('--csv', help='write the map here instead of stdout')
    ap.add_argument('--id', type=lambda s: int(s, 0), help='only this CAN id')
    args = ap.parse_args()

    lo, hi = (int(x, 0) for x in args.table.split(':'))
    img = Image(open(args.image, 'rb').read(), args.base)

    rows, bad = [], 0
    for m in messages(img, lo, hi):
        if m['can_id'] > 0x7FF:
            bad += 1
            continue
        if args.id is not None and m['can_id'] != args.id:
            continue
        for s in list(signals(img, m)) + list(booleans(img, m)):
            rows.append({'can_id': '0x%03x' % m['can_id'], 'kind': s['kind'],
                         'desc': '0x%08x' % s['desc'], 'target': '0x%08x' % s['target'],
                         'start_bit': s['start_bit'], 'bit_len': s['bit_len'],
                         'type': s['type']})
    if bad:
        print('note: %d records have a non-11-bit identifier (variant-disabled records carry '
              '0xffffffff)' % bad, file=sys.stderr)

    fields = ['can_id', 'kind', 'desc', 'target', 'start_bit', 'bit_len', 'type']
    out = open(args.csv, 'w', newline='') if args.csv else sys.stdout
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    if args.csv:
        out.close()
        print('%d messages, %d bindings -> %s'
              % (len({r['can_id'] for r in rows}), len(rows), args.csv))


if __name__ == '__main__':
    main()
