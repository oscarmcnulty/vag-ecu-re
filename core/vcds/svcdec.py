#!/usr/bin/env python3
"""svcdec.py - decoder/encoder for VCDS (VAG-COM) .clb label files.

Behaviour-for-behaviour port of SVCdec.php 0.1.0 by isublimity
(https://github.com/isublimity/SVCdec), including its quirks - see the
NOTE: comments where the original does something surprising.

A .clb is the shipped, obfuscated form of a VCDS .lbl label file. Records are
separated by "\\x00\\n"; each record is folded byte-by-byte against a fixed
1597-byte keystream that is baked into the program. The only per-line secret is
*where in the keystream the line starts*, and that offset is a plain linear
function of the line number:

    offset(n) = ((n % 16) * P + Z) % 256

so a whole file falls out once P and Z are known. Known presets are
-method:1 -> P=3 Z=250, -method:2 -> P=2 Z=250, -method:3 -> P=3 Z=233; the
`brt` command recovers P and Z from the file itself when none of them fit.
"""

import os
import re
import sys
from collections import Counter

MAINMSG = (";\n;\tSVCdec vers.0.1.0 (25ag2/10)\n;\n"
           ";\tsublimity - vcds - clb - file - decoder-encoder\n;\n;\n")

HELP = r"""
use: "FileName" [command] [params]
COMMAND:
    brt - brute force all lines and find vars : Z & P
    enc - encode file and save to filename.clb
PARAMS:
    -lang:[en|de|ru] , def=de
    -method:[1|2|3] , def=1 , preset of p & z
    -keymet:NUM [1....8]
    -showlinenum - show line numbers , def=0
    -showallchar:[0|1] - show all chars (0..255) , def=1
    -findshowall:[0|1] - def=0
    -findline:NUM
    -findtxt:'TEXT'
    -finddecode:NUM (0..255)
    -maxlines:NUM (def = 0)
    -showonlyerror
    -save  - save decoded file to basename(FileName).lbl , to current path
    -saveto:'pathname' - save decoded file to basename(FileName).lbl
    -metvarz:NUM (0..255) - var method key pos Z or -z:22
    -metvarp:NUM (0..255) - var method key pos P or -p:3
    -fastbrt  - brt only use key pos = (0..20) & (240..255)
simplzz:
    svcdec.py '7L6-9.clb' -save
    svcdec.py '7L6-9.clb' brt -saveto:'results/' -maxlines:50 -fastbrt
    svcdec.py '7L6-9.clb' -method:1
    svcdec.py '7L6-9.clb' -metvarp:3 -metvarz:250 -save
    svcdec.py '7L6-9.clb' brt -findline:65 -finddecode:33
    svcdec.py '7L6-9.clb' brt
    svcdec.py '7L6-9.lbl' enc -z:33 -p:3

Note:
    -method:3 =>  p=3 & z=233
    -method:2 =>  p=2 & z=250
    -method:1 =>  p=3 & z=250
def use :
     >svcdec.py "7L6-9.clb" -maxlines:5
     check result => good => add `-save` :)
     if error  => add command `brt` :
     >svcdec.py "7L6-9.clb" brt -maxlines:50 -fastbrt -lang:en
     check result => if bad => remove `-fastbrt` and edit `-lang:de`
"""

METHODS = {1: (3, 250), 2: (2, 250), 3: (3, 233)}

# --------------------------------------------------------------------------
# The keystream, stored the way the original stores it: every byte b at index f
# is kept as  b * (f&3 + 2) * (f&5 + 1), which scatters the values enough that
# the array does not look like text. Undoing that division recovers the plain
# 1597-byte key - which turns out to be VCDS' own "How to Copy and Paste" help
# page, reused verbatim as a keystream.
_KEY_RAW = (
    144, 666, 476, 320, 1160, 1998, 640, 2010, 222, 672, 484, 320, 970, 1980,
    2000, 960, 160, 582, 460, 1160, 1010, 180, 200, 2580, 130, 426, 180, 670,
    790, 1386, 640, 3150, 230, 192, 388, 320, 1120, 2052, 2220, 3090, 228,
    582, 436, 320, 1160, 1872, 1940, 3480, 64, 684, 468, 1100, 1150, 576,
    2220, 3300, 64, 462, 420, 990, 1140, 1998, 2300, 3330, 204, 696, 128, 870,
    1050, 1980, 2000, 3330, 238, 690, 184, 100, 730, 1980, 640, 3330, 228,
    600, 404, 1140, 320, 2088, 2220, 960, 224, 606, 456, 1020, 1110, 2052,
    2180, 960, 198, 606, 456, 1160, 970, 1890, 2200, 960, 204, 702, 440, 990,
    1160, 1890, 2220, 3300, 230, 264, 128, 1210, 1110, 2106, 640, 3270, 194,
    726, 128, 1100, 1010, 1818, 2000, 960, 232, 666, 128, 1170, 1150, 1818,
    200, 3480, 208, 606, 128, 670, 1110, 2016, 2420, 960, 194, 660, 400, 320,
    800, 1746, 2300, 3480, 202, 192, 408, 1170, 1100, 1782, 2320, 3150, 222,
    660, 460, 460, 100, 180, 1780, 3330, 234, 684, 128, 1090, 1110, 2106,
    2300, 3030, 64, 666, 456, 320, 1120, 1998, 2100, 3300, 232, 630, 440,
    1030, 320, 1800, 2020, 3540, 210, 594, 404, 320, 1090, 1746, 2420, 960,
    220, 666, 464, 320, 1080, 1998, 2220, 3210, 64, 606, 480, 970, 990, 2088,
    2160, 3630, 64, 648, 420, 1070, 1010, 576, 2320, 3120, 202, 192, 444,
    1100, 1010, 576, 1960, 3030, 216, 666, 476, 460, 100, 1314, 2040, 960,
    210, 696, 128, 1000, 1110, 1818, 2300, 960, 220, 666, 464, 440, 320, 2016,
    2160, 3030, 194, 690, 404, 320, 1150, 1818, 2020, 960, 232, 624, 404, 320,
    1110, 2142, 2200, 3030, 228, 234, 460, 320, 1090, 1746, 2200, 3510, 194,
    648, 128, 1020, 1110, 2052, 640, 3630, 222, 702, 456, 320, 1090, 1998,
    2340, 3450, 202, 192, 444, 1140, 320, 1782, 2220, 3270, 224, 702, 464,
    1010, 1140, 576, 2320, 3330, 64, 612, 420, 1100, 1000, 576, 2220, 3510,
    232, 60, 416, 1110, 1190, 576, 2320, 3330, 64, 654, 444, 1180, 1010, 576,
    2320, 3120, 202, 192, 396, 1170, 1140, 2070, 2220, 3420, 64, 582, 440,
    1000, 320, 2142, 2080, 3030, 228, 606, 128, 1160, 1040, 1818, 640, 3240,
    202, 612, 464, 320, 970, 1980, 2000, 960, 228, 630, 412, 1040, 1160, 576,
    2180, 3330, 234, 690, 404, 320, 980, 2106, 2320, 3480, 222, 660, 460, 320,
    970, 2052, 2020, 960, 216, 666, 396, 970, 1160, 1818, 2000, 1380, 20, 60,
    128, 320, 320, 576, 840, 300, 20, 192, 128, 320, 320, 576, 640, 2550, 230,
    630, 440, 1030, 320, 2178, 2220, 3510, 228, 192, 436, 1110, 1170, 2070,
    2020, 1320, 64, 672, 432, 970, 990, 1818, 640, 3630, 222, 702, 456, 320,
    990, 2106, 2280, 3450, 222, 684, 128, 970, 1160, 576, 2320, 3120, 202,
    192, 392, 1010, 1030, 1890, 2200, 3300, 210, 660, 412, 320, 1110, 1836,
    640, 3480, 208, 606, 128, 1160, 1010, 2160, 2320, 960, 210, 660, 128,
    1160, 1040, 1818, 640, 3060, 210, 684, 460, 1160, 320, 1764, 2220, 3600,
    64, 588, 404, 1080, 1110, 2142, 920, 300, 64, 192, 128, 320, 420, 180,
    200, 960, 64, 192, 128, 320, 320, 1296, 2220, 3240, 200, 192, 400, 1110,
    1190, 1980, 640, 3480, 208, 606, 128, 1080, 1010, 1836, 2320, 960, 218,
    666, 468, 1150, 1010, 576, 1960, 3510, 232, 696, 444, 1100, 440, 576,
    2380, 3120, 210, 648, 404, 320, 1000, 2052, 1940, 3090, 206, 630, 440,
    1030, 320, 2178, 2220, 3510, 228, 192, 396, 1170, 1140, 2070, 2220, 3420,
    64, 666, 472, 1010, 1140, 576, 2320, 3120, 202, 192, 464, 1010, 1200,
    2088, 640, 2940, 242, 192, 436, 1110, 1180, 1890, 2200, 3090, 64, 696,
    416, 1010, 320, 1962, 2220, 3510, 230, 606, 128, 1160, 1110, 576, 2320,
    3120, 202, 192, 456, 1050, 1030, 1872, 2320, 960, 234, 660, 464, 1050,
    1080, 576, 2420, 3330, 234, 192, 456, 1010, 970, 1782, 2080, 960, 232,
    624, 404, 320, 1010, 1980, 2000, 960, 222, 612, 128, 1160, 1040, 1818,
    640, 3480, 202, 720, 464, 460, 100, 576, 640, 960, 64, 252, 40, 100, 320,
    576, 640, 960, 64, 192, 336, 1040, 1050, 2070, 640, 3450, 208, 666, 468,
    1080, 1000, 576, 2080, 3150, 206, 624, 432, 1050, 1030, 1872, 2320, 960,
    232, 624, 404, 320, 1160, 1818, 2400, 3480, 92, 192, 312, 1110, 1190, 576,
    2280, 3030, 216, 606, 388, 1150, 1010, 576, 2320, 3120, 202, 192, 432,
    1010, 1020, 2088, 640, 3270, 222, 702, 460, 1010, 320, 1764, 2340, 3480,
    232, 666, 440, 460, 100, 576, 640, 960, 64, 252, 40, 100, 320, 576, 640,
    960, 64, 192, 312, 1010, 1200, 2088, 640, 3510, 230, 630, 440, 1030, 320,
    2178, 2220, 3510, 228, 192, 436, 1110, 1170, 2070, 2020, 1320, 64, 672,
    432, 970, 990, 1818, 640, 3630, 222, 702, 456, 320, 990, 2106, 2280, 3450,
    222, 684, 128, 1110, 1180, 1818, 2280, 960, 232, 624, 404, 320, 1040,
    1890, 2060, 3120, 216, 630, 412, 1040, 1160, 1818, 2000, 960, 232, 606,
    480, 1160, 460, 180, 640, 960, 64, 192, 168, 100, 100, 576, 640, 960, 64,
    192, 128, 800, 1140, 1818, 2300, 3450, 64, 582, 440, 1000, 320, 2052,
    2020, 3240, 202, 582, 460, 1010, 320, 2088, 2080, 3030, 64, 684, 420,
    1030, 1040, 2088, 640, 3270, 222, 702, 460, 1010, 320, 1764, 2340, 3480,
    232, 666, 440, 320, 970, 1980, 2000, 960, 194, 192, 432, 1050, 1150, 2088,
    640, 3330, 204, 192, 444, 1120, 1160, 1890, 2220, 3300, 230, 192, 476,
    1050, 1080, 1944, 640, 2910, 224, 672, 404, 970, 1140, 828, 200, 960, 64,
    192, 128, 420, 100, 180, 640, 960, 64, 192, 128, 320, 850, 2070, 2100,
    3300, 206, 192, 484, 1110, 1170, 2052, 640, 3270, 222, 702, 460, 1010,
    440, 576, 2180, 3330, 236, 606, 128, 1160, 1040, 1818, 640, 2970, 234,
    684, 460, 1110, 1140, 576, 2340, 3360, 64, 666, 456, 320, 1000, 1998,
    2380, 3300, 64, 696, 416, 1010, 320, 1944, 2100, 3450, 232, 192, 468,
    1100, 1160, 1890, 2160, 960, 210, 696, 128, 1040, 1050, 1854, 2080, 3240,
    210, 618, 416, 1160, 1150, 576, 780, 2010, 222, 672, 484, 390, 460, 180,
    640, 960, 64, 192, 168, 100, 100, 576, 640, 960, 64, 192, 128, 800, 1140,
    1818, 2300, 3450, 64, 582, 440, 1000, 320, 2052, 2020, 3240, 202, 582,
    460, 1010, 320, 2088, 2080, 3030, 64, 648, 404, 1020, 1160, 576, 2180,
    3330, 234, 690, 404, 320, 980, 2106, 2320, 3480, 222, 660, 184, 100, 320,
    576, 640, 960, 84, 60, 40, 320, 320, 576, 640, 960, 64, 534, 444, 1170,
    320, 1872, 1940, 3540, 202, 192, 424, 1170, 1150, 2088, 640, 2970, 222,
    672, 420, 1010, 1000, 576, 2320, 3120, 202, 192, 464, 1010, 1200, 2088,
    660, 960, 146, 696, 128, 1040, 970, 2070, 640, 2940, 202, 606, 440, 320,
    990, 1998, 2240, 3150, 202, 600, 128, 1160, 1110, 576, 1940, 3300, 64,
    630, 440, 1180, 1050, 2070, 2100, 2940, 216, 606, 128, 990, 1080, 1890,
    2240, 2940, 222, 582, 456, 1000, 460, 180, 640, 960, 64, 192, 168, 100,
    100, 576, 640, 960, 64, 192, 128, 320, 780, 1998, 2380, 960, 234, 690,
    420, 1100, 1030, 576, 2420, 3330, 234, 684, 128, 1090, 1110, 2106, 2300,
    3030, 88, 192, 448, 1080, 970, 1782, 2020, 960, 242, 666, 468, 1140, 320,
    1782, 2340, 3420, 230, 666, 456, 320, 1110, 2124, 2020, 3420, 64, 696,
    416, 1010, 320, 2070, 2020, 2970, 222, 660, 400, 320, 980, 1998, 2400,
    960, 196, 606, 432, 1110, 1190, 576, 800, 3480, 208, 606, 128, 1010, 1090,
    2016, 2320, 3630, 64, 666, 440, 1010, 410, 828, 200, 960, 64, 192, 128,
    420, 100, 180, 640, 960, 64, 192, 128, 320, 320, 1440, 2280, 3030, 230,
    690, 128, 970, 1100, 1800, 640, 3420, 202, 648, 404, 970, 1150, 1818, 640,
    3480, 208, 606, 128, 1140, 1050, 1854, 2080, 3480, 64, 654, 444, 1170,
    1150, 1818, 640, 2940, 234, 696, 464, 1110, 1100, 576, 1940, 3300, 200,
    192, 388, 320, 1080, 1890, 2300, 3480, 64, 666, 408, 320, 1110, 2016,
    2320, 3150, 222, 660, 460, 320, 1190, 1890, 2160, 3240, 64, 582, 448,
    1120, 1010, 1746, 2280, 1380, 20, 192, 128, 320, 320, 756, 200, 300, 64,
    192, 128, 320, 320, 576, 640, 2550, 230, 630, 440, 1030, 320, 2178, 2220,
    3510, 228, 192, 436, 1110, 1170, 2070, 2020, 1320, 64, 654, 444, 1180,
    1010, 576, 2320, 3120, 202, 192, 396, 1170, 1140, 2070, 2220, 3420, 64,
    702, 448, 320, 1110, 2052, 640, 3000, 222, 714, 440, 320, 1160, 1872,
    2020, 960, 216, 630, 460, 1160, 320, 2106, 2200, 3480, 210, 648, 128,
    1050, 1160, 576, 2080, 3150, 206, 624, 432, 1050, 1030, 1872, 2320, 3450,
    64, 234, 320, 970, 1150, 2088, 2020, 1170, 92, 60, 128, 320, 320, 576,
    840, 300, 20, 192, 128, 320, 320, 576, 640, 960, 160, 684, 404, 1150,
    1150, 576, 1940, 3300, 200, 192, 456, 1010, 1080, 1818, 1940, 3450, 202,
    192, 464, 1040, 1010, 576, 2160, 3030, 204, 696, 128, 1090, 1110, 2106,
    2300, 3030, 64, 588, 468, 1160, 1160, 1998, 2200, 1380, 20, 192, 128, 320,
    320, 756, 200, 300, 64, 192, 128, 320, 320, 576, 640, 2670, 222, 702, 128,
    1040, 970, 2124, 2020, 960, 212, 702, 460, 1160, 320, 2016, 1940, 3450,
    232, 606, 400, 320, 1160, 1872, 2020, 960, 232, 606, 480, 1160, 330, 576,
    640, 2670, 222, 702, 128, 990, 970, 1980, 640, 3300, 222, 714, 128, 990,
    1110, 2016, 2420, 960, 194, 660, 400, 320, 1120, 1746, 2300, 3480, 202,
    264, 128, 1010, 1180, 1818, 2200, 960, 196, 606, 464, 1190, 1010, 1818,
    2200, 960, 200, 630, 408, 1020, 1010, 2052, 2020, 3300, 232, 192, 448,
    1140, 1110, 1854, 2280, 2910, 218, 690, 132, 0, 0
)


def _build_keystream(raw):
    out = bytearray()
    for f, v in enumerate(raw):
        out.append((v // (((f & 3) + 2) * ((f & 5) + 1))) & 0xFF)
    return bytes(out)


KEY = _build_keystream(_KEY_RAW)


# --------------------------------------------------------------------------
# PHP semantics helpers
def php_truthy(v):
    """PHP's notion of truth: '', '0', 0, None and False are false."""
    return not (v is None or v is False or v == '' or v == '0' or v == 0)


def php_int(v):
    """PHP intval(): leading integer prefix of a string, else 0."""
    if v is True:
        return 1
    if v is False or v is None:
        return 0
    m = re.match(r'\s*[+-]?\d+', str(v))
    return int(m.group()) if m else 0


class KeyExhausted(Exception):
    """The original `die("end key :$pos:")`."""


def key_bytes(start, length):
    """Keystream bytes for `length` characters starting at keystream offset
    `start`, reproducing the original's wrap-around exactly.

    Every byte is OR'ed with 128 before use - that is part of the cipher, not
    of the addressing.
    """
    d = 0
    for f in range(length):
        pos = start + f
        # NOTE: the original tests `empty($key[$pos])` on the *unwrapped*
        # index, which is true past the end of the key and (a genuine bug)
        # also for a literal ASCII '0' byte inside the key.
        if pos >= len(KEY) or KEY[pos] == 0x30:
            raise KeyExhausted(pos)
        if pos > 255:
            # NOTE: past offset 255 the key pointer does not continue through
            # the keystream, it restarts at 0 and walks forward from there.
            if d > 255:
                d = 0
            pos = d
            d += 1
        yield KEY[pos] | 128


# --------------------------------------------------------------------------
def get_key_pos(line_num, p, z):
    """Where in the keystream line `line_num` starts."""
    return ((line_num % 16) * p + z) % 256


def decode_line(key_pos, clb):
    """clb bytes -> text. Bytes that cannot be plausible label text are shown
    as ;[NNN] rather than dropped."""
    out = []
    for cch, char in zip(key_bytes(key_pos, len(clb)), clb):
        result = cch ^ ((char - cch) & 255)
        if result < 9 or 14 <= result < 23:
            out.append(';[%d]' % result)
        else:
            out.append(chr(result))
    return ''.join(out)


def encode_line(text, key_pos):
    """Exact inverse of decode_line's arithmetic."""
    out = bytearray()
    for cch, char in zip(key_bytes(key_pos, len(text)), text):
        out.append(((cch ^ (char & 255)) + cch) & 255)
    return bytes(out)


def find_decode_line(crline, only_clean, lang='de', showall=False, fast=False):
    """Decode one line at all 256 possible offsets.

    With only_clean=True, offsets that produce any implausible character are
    dropped; a line that survives at exactly one offset has effectively
    revealed its own key position.
    """
    maxresult = 245 if lang in ('de', 'ru') else 170
    if len(crline) < 2:
        return {'x': ';'}
    lines = {}
    w = 0
    while w < 256:
        if fast and 20 < w < 90:
            w = 240  # only scan the offsets real files actually use
        bad = False
        ln = []
        for cch, char in zip(key_bytes(w, len(crline)), crline):
            result = cch ^ ((char - cch) & 255)
            if (result < 11 or 12 <= result < 23
                    or 175 < result < 224
                    or maxresult < result < 245):
                bad = True
                ln.append(chr(result) if showall else ' ')
            else:
                ln.append(chr(result))
        if not (only_clean and bad):
            lines[w] = ''.join(ln)
        w += 1
    return lines


def find_key_pos_values(trusted):
    """Fit offset(n) = ((n%16)*P + Z) % 256 to the line->offset pairs that the
    brute force pinned down, and return the (P, Z) that explains the most."""
    print(";\n;\n;\tFIND METHOD VARS by brt lines")
    print(";\tInput counts array :%d" % len(trusted))
    pairs = [(num, need) for num, need in trusted.items() if num > 0]
    best = {}
    for p in range(256):
        # For a fixed P each line votes for exactly one Z, so tally the votes
        # instead of testing all 65536 (P, Z) pairs one line at a time.
        votes = Counter((need - (num % 16) * p) % 256 for num, need in pairs)
        for z in sorted(votes):
            count = votes[z]
            if count > len(trusted) / 2:
                print(";\tFind varianz:\t\tZ: %d ,\t\tP: %d \t count : %d; "
                      % (z, p, count))
                best[count] = (z, p)  # last writer for a given count wins
    if best:
        mx = max(best)
        z, p = best[mx]
        print(";\tUse count := %d\n;\tP = %d\n;\tZ = %d\n;\n;\n" % (mx, p, z))
        return p, z
    print("; \t !!! ERROR : not find key vars \n;\n;\n")
    return -1, -1


def clb_to_array(fn, is_norm=False):
    with open(fn, 'rb') as fp:
        data = fp.read()
    print(";Read from file %d bytes..." % len(data))
    return data.split(b'\n' if is_norm else b'\x00\n')


def chk_line(msg):
    """1 if the line contains a control character (i.e. decoded badly)."""
    return 1 if any(ord(c) < 12 for c in msg[:-1]) else 0


def trim_line(msg):
    out = ''.join('_' if ord(c) < 16 else c for c in msg)
    return ('!!!' + out) if out != msg else out


def tvar(val, pos=5):
    s = str(val)
    return s + ' ' * max(0, pos - len(s))


def dump_line(line_num, pos, ln_text, flag='', true_txt=''):
    s = ";\t" + tvar(line_num) + tvar(pos) + tvar(flag)
    if true_txt.strip() == ln_text.strip():
        s += "<+>"
    print(s + ":\t" + ln_text)


# --------------------------------------------------------------------------
def argv_to_dict(argv):
    """The original's ArgvToGlobal(): every -name / -name:value token."""
    arr = {}
    for arg in argv:
        if arg.startswith('-'):
            k = arg[1:].split(':')
            # NOTE: `empty($k[1]) ? true : $k[1]` means -flag:0 yields *true*,
            # so e.g. -showallchar:0 does not turn the option off.
            arr[k[0]] = k[1] if len(k) > 1 and php_truthy(k[1]) else True
    return arr


def main(argv):
    # PHP echoes raw bytes; latin-1 makes Python do the same.
    sys.stdout.reconfigure(encoding='latin-1', errors='replace', newline='')

    o = {'showlinenum': 0, 'findline': 0, 'finddecode': 0, 'findtxt': '',
         'lang': 'de', 'keymet': 0, 'showallchar': 1, 'findshowall': 0,
         'method': 1, 'maxlines': 0, 'save': 0, 'showonlyerror': 0,
         'z': -1, 'p': -1, 'metvarz': -1, 'metvarp': -1, 'fastbrt': 0,
         'saveto': ''}
    o.update(argv_to_dict(argv))

    print(MAINMSG, end='')

    filename = argv[1] if len(argv) > 1 else ''
    cmd = argv[2].lower() if len(argv) > 2 else ''

    if filename in ('?', 'help', '--help', '-h') or len(filename) < 2:
        print(HELP)
        return 0
    if not os.path.exists(filename):
        print('can`t find file')
        return 1

    metvarz, metvarp = php_int(o['metvarz']), php_int(o['metvarp'])
    if php_int(o['z']) > 0:
        metvarz = php_int(o['z'])
    if php_int(o['p']) > 0:
        metvarp = php_int(o['p'])

    method = php_int(o['method'])
    maxlines = php_int(o['maxlines'])
    findline = php_int(o['findline'])
    finddecode = php_int(o['finddecode'])
    findtxt = '' if o['findtxt'] is True else str(o['findtxt'])
    lang = 'de' if o['lang'] is True else str(o['lang'])
    saveto = '' if o['saveto'] is True else str(o['saveto'])
    save = php_truthy(o['save']) or bool(saveto)

    data = clb_to_array(filename, cmd == 'enc')
    print(";File:\t%s" % filename)
    print(";KeySize:\t%d" % len(KEY))
    print(";CountLines:\t%d" % len(data))

    # ---------------------------------------------------------------- encode
    if cmd == 'enc':
        if metvarp < 1 or metvarz < 1:
            print('set P and Z , -p: and -z:')
            return 1
        savedata = bytearray()
        for line_num, clb_txt in enumerate(data):
            pos = get_key_pos(line_num, metvarp, metvarz)
            savedata += encode_line(clb_txt, pos) + b'\x00\n'
            print("%d\t%s" % (line_num,
                              trim_line(clb_txt.decode('latin-1'))))
        outname = re.sub('clb\\.lbl', 'out', filename, flags=re.I)
        save_filename = saveto + os.path.basename(outname) + '.clb'
        print("; save to : %s " % save_filename)
        with open(save_filename, 'wb') as fp:
            fp.write(savedata)
        print("\n\t encode done ... see %s\n " % save_filename)
        return 0

    # ------------------------------------------------------------ brute force
    if cmd == 'brt':
        trusted = {}
        print(";Only line num:: %s" % findline)
        print(";Find in line:: %s" % findtxt)
        for line_num, clb_txt in enumerate(data):
            if maxlines and maxlines < line_num:
                break
            if findline:
                clb_txt = data[findline]
            lns = find_decode_line(clb_txt,
                                   only_clean=not findline,
                                   lang=lang,
                                   showall=php_int(o['findshowall']),
                                   fast=php_truthy(o['fastbrt']))
            if finddecode:
                print(";Show only line:%d" % finddecode, end='')
                txt = lns.get(finddecode, '')
                print("%s\n" % txt)
                for f, ch in enumerate(txt):
                    print(";%d\t%d\t%s" % (f, ord(ch), ch))
            else:
                if not lns:
                    dump_line(line_num, -1, ';!--CANT--')
                if len(lns) == 1:
                    only = next(iter(lns))
                    # NOTE: the {'x': ';'} short-line sentinel lands here too;
                    # PHP5 coerced 'x' > 0 to false, so it was ignored.
                    if isinstance(only, int) and only > 0:
                        trusted[line_num] = only
                for pos, ln in lns.items():
                    if len(findtxt) > 1:
                        if findtxt.lower() in ln.lower():
                            dump_line(line_num, pos, ln, '-')
                    else:
                        dump_line(line_num, pos, ln)
            if findline:
                break
        if trusted:
            p, z = find_key_pos_values(trusted)
            if p > 0 and z > 0:
                metvarp, metvarz = p, z
        if not (metvarz > 0 and metvarp > 0):
            return 1

    # ---------------------------------------------------------------- decode
    if metvarz > 0 and metvarp > 0:
        print(";\tmanual method decode  CMD : -metvarz:%d -metvarp:%d "
              % (metvarz, metvarp))
    print(";\tuse method `%d`:\t%s" % (method, 'NEW' if method == 2 else 'OLD'))

    if metvarz > 0 and metvarp > 0:
        p, z = metvarp, metvarz
    else:
        p, z = METHODS.get(method, METHODS[1])

    savedata = []
    print(';---------------- !FILE! ------------')
    print(MAINMSG, end='')
    for line_num, clb_txt in enumerate(data):
        if maxlines and cmd != 'brt' and maxlines < line_num:
            break
        txt = decode_line(get_key_pos(line_num, p, z), clb_txt)
        savedata.append(txt)
        if php_truthy(o['showlinenum']):
            print("%d\t" % line_num, end='')
        if php_truthy(o['showonlyerror']):
            # NOTE: chk_line() is 1 for a *bad* line, so this prints the clean
            # ones - the option does the opposite of what its name says.
            if not chk_line(txt):
                print("%d\t%s" % (line_num, txt))
        elif php_truthy(o['showallchar']):
            if txt:
                print(txt, end='' if txt.endswith("\n") else "\n")
        else:
            print(trim_line(txt))

    if save:
        if len(saveto) > 2 and saveto[-1] not in '\\/':
            saveto += os.sep
        elif len(saveto) <= 2:
            saveto = ''
        save_filename = saveto + os.path.basename(filename) + '.lbl'
        print("; save to : %s " % save_filename)
        with open(save_filename, 'w', encoding='latin-1', newline='') as fp:
            fp.write("\n".join(savedata) + ("\n" if savedata else ""))
    print(';---------------- !END FILE! ------------\n')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except KeyExhausted as e:
        print("\n\n\nend key :%s:" % e.args[0])
        sys.exit(1)
    except BrokenPipeError:
        sys.exit(0)
