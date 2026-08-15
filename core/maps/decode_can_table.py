#!/usr/bin/env python3
"""Decode the generated COM stack's CAN message table into an ID -> signal -> RAM map.

The problem this solves: `core/ghidra/DecodeComBindings.py` finds the 40-byte signal
descriptors by *content* (callback + mask), which recovers each signal's RAM target and
its bit position -- but NOT which CAN message it belongs to. The descriptors are stored
in one flat, unordered pool, so adjacency tells you nothing: the six records around
TSK_01's status descriptor target six unrelated RAM words.

The binding lives in a separate message table:

    message record, stride 0x30
      +0x00  -> pointer to this message's SIGNAL BLOCK  (0 if the message has none)
      +0x04  CAN identifier (11-bit)
      +0x08  common per-message callback (one value across the whole table)

    signal block, stride 0x0c, runs until the next block starts
      +0x00  pointer to (descriptor + 0x18), i.e. straight at the descriptor's
             `target` field -- NOT at the record start. Subtract 0x18 to get the record.
      +0x04  aux pointer (frequently 0)
      +0x08  unused in this image

So: message table gives ID -> block, block gives ID -> descriptors, descriptor gives
target RAM address + start_bit + bit_len. Composing them yields the full map.

Verified on 8R0907115N_0006: ACC_01 (0x109) resolves to 9 signals ending in
target 0xd000a590 start_bit 60 len 3, which is the ACC_Status_ACC binding independently
established in ecus/med17/ecu.conf; and TSK_01 (0x10A) block entry #0 is 0x80039478 =
descriptor 0x80039460 + 0x18, target 0xd0005e34 start_bit 16 len 24.

    python3 core/maps/decode_can_table.py <image.bin> --table 0x800312d0:0x80031bd0
                                          [--base 0x80000000] [--csv out.csv]

Note this table covers ONE controller's messages (48 records here). IDs handled by
another CAN controller -- and IDs the ECU does not handle at all -- are simply absent,
which makes "absent from this table" a cheap, reliable negative test.
"""
import argparse
import csv
import struct
import sys

MSG_STRIDE = 0x30
BLK_STRIDE = 0x0C
DESC_TARGET_OFF = 0x18   # block entries point here, not at the record start


class Image:
    def __init__(self, buf, base):
        self.buf, self.base = buf, base

    def ok(self, addr, n=4):
        return self.base <= addr and addr - self.base + n <= len(self.buf)

    def u32(self, addr):
        return struct.unpack_from('<I', self.buf, addr - self.base)[0]

    def u8(self, addr):
        return self.buf[addr - self.base]


def read_messages(img, lo, hi):
    """Yield (record_addr, can_id, block_ptr) for each message record."""
    for rec in range(lo, hi, MSG_STRIDE):
        if not img.ok(rec, MSG_STRIDE):
            break
        yield rec, img.u32(rec + 4), img.u32(rec)


def block_extents(blocks, hi_guess):
    """A block runs until the next block begins; the last ends at hi_guess."""
    ordered = sorted(b for b in blocks if b)
    return {b: (ordered[i + 1] if i + 1 < len(ordered) else hi_guess)
            for i, b in enumerate(ordered)}


def read_signals(img, blk, end):
    """Yield (desc_addr, target, start_bit, bit_len, type) for one message's block."""
    for ent in range(blk, end, BLK_STRIDE):
        if not img.ok(ent):
            return
        ptr = img.u32(ent)
        if not ptr:
            continue
        desc = ptr - DESC_TARGET_OFF
        if not img.ok(desc, 0x28):
            continue
        yield (desc, img.u32(desc + 0x18), img.u8(desc + 0x1c),
               img.u8(desc + 0x1d), img.u8(desc + 0x1e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0x80000000)
    ap.add_argument('--table', required=True,
                    help='message table as LO:HI vaddrs, e.g. 0x800312d0:0x80031bd0')
    ap.add_argument('--csv', help='write the map here instead of stdout')
    args = ap.parse_args()

    lo, hi = (int(x, 0) for x in args.table.split(':'))
    img = Image(open(args.image, 'rb').read(), args.base)

    msgs = list(read_messages(img, lo, hi))
    bad = [m for m in msgs if m[1] > 0x7FF]
    if bad:
        print('warning: %d records have a non-11-bit identifier -- wrong --table?'
              % len(bad), file=sys.stderr)

    # The signal blocks sit in their own contiguous run; bound the last one by the
    # end of that run rather than by the message table.
    ptrs = [m[2] for m in msgs if m[2]]
    extents = block_extents(ptrs, max(ptrs) + 0x100 if ptrs else 0)

    rows = []
    for _, can_id, blk in sorted(msgs, key=lambda m: m[1]):
        if not blk:
            continue
        for desc, target, sb, ln, ty in read_signals(img, blk, extents[blk]):
            rows.append({'can_id': '0x%03x' % can_id, 'desc': '0x%08x' % desc,
                         'target': '0x%08x' % target, 'start_bit': sb,
                         'bit_len': ln, 'type': ty})

    fields = ['can_id', 'desc', 'target', 'start_bit', 'bit_len', 'type']
    out = open(args.csv, 'w', newline='') if args.csv else sys.stdout
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    if args.csv:
        out.close()
        print('%d messages, %d signals -> %s'
              % (len({r['can_id'] for r in rows}), len(rows), args.csv))


if __name__ == '__main__':
    main()
