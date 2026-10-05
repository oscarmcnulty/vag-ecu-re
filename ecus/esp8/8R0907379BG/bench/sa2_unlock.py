#!/usr/bin/env python3
"""ESP8 (8R0907379BG) SecurityAccess via the SA2 bytecode recovered from the OEM flash container
(SGO 31222011-8R0907379BG_0030.sgo, security blob @0x1bb, 24-byte SA2 program). Computes key=SA2(seed)
with bri3d's SA2 VM (github.com/bri3d/sa2_seed_key) and drives 27 <seed> -> 27 <key> over TP2.0+KWP.

SAFE BY DEFAULT: dry-run (requests a seed, prints the computed key, sends NOTHING). Only --send
transmits the key, which costs one of the ~3 key attempts before lockout. Lockout counter is volatile
RAM (sa_lockout_counter 0x405e12) -> a FEPS power-cycle (power.py) resets it.

Usage (32-bit python, ignition ON):
  sa2_unlock.py                      # dry-run: session 89, 27 03 seed -> computed key (no send)
  sa2_unlock.py --level 1 --session 85   # dry-run: programming session, 27 01
  sa2_unlock.py --send               # ACTUALLY send the key (uses a lockout attempt)
"""
import argparse, os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from can_raw import RawCAN
from tp20_kwp import TP20KWP, kfmt

# SA2 bytecode extracted from the SGO security section (@0x1bb, len 0x18). Provenance: OEM flash
# container for 8R0907379BG/0030. Decodes as: ADD 0x974c58ab; BCC +7; EOR 0xfedcba98; BRA +5;
# EOR 0x98765432; FOR 11 { RSR } FINISH.
SA2_TAPE = bytes.fromhex("93974c58ab4a0787fedcba986b05879876543268 0b82494c".replace(" ", ""))

class Sa2SeedKey:  # faithful port of bri3d/sa2_seed_key (BE operands)
    def __init__(self, tape, seed, le_operand=False):
        self.t=bytearray(tape); self.r=seed&0xffffffff; self.c=0; self.ip=0
        self.fp=deque(); self.fi=deque(); self.le=le_operand
    def _op32(self):
        o=self.t[self.ip+1:self.ip+5]
        return (o[3]<<24|o[2]<<16|o[1]<<8|o[0]) if self.le else (o[0]<<24|o[1]<<16|o[2]<<8|o[3])
    def execute(self):
        while self.ip < len(self.t):
            op=self.t[self.ip]
            if op==0x81:   # RSL
                self.c=self.r&0x80000000; self.r=((self.r<<1)|(1 if self.c else 0))&0xffffffff; self.ip+=1
            elif op==0x82: # RSR
                self.c=self.r&1; self.r>>=1
                if self.c: self.r|=0x80000000
                self.ip+=1
            elif op==0x93: # ADD
                self.c=0; r=self.r+self._op32()
                if r>0xffffffff: self.c=1; r&=0xffffffff
                self.r=r; self.ip+=5
            elif op==0x84: # SUB
                self.c=0; r=self.r-self._op32()
                if r<0: self.c=1; r&=0xffffffff
                self.r=r; self.ip+=5
            elif op==0x87: # EOR
                self.r^=self._op32(); self.ip+=5
            elif op==0x68: # FOR
                self.fi.appendleft(self.t[self.ip+1]-1); self.ip+=2; self.fp.appendleft(self.ip)
            elif op==0x49: # NEXT
                if self.fi[0]>0: self.fi[0]-=1; self.ip=self.fp[0]
                else: self.fi.popleft(); self.fp.popleft(); self.ip+=1
            elif op==0x4A: # BCC
                sc=self.t[self.ip+1]+2; self.ip+= sc if self.c==0 else 2
            elif op==0x6B: # BRA
                self.ip+=self.t[self.ip+1]+2
            elif op==0x4C: # FINISH
                self.ip+=1
            else:
                raise ValueError(f"bad SA2 opcode 0x{op:02x} @ip{self.ip}")
        return self.r & 0xffffffff

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=3, help="SA level: 1 (27 01/02) or 3 (27 03/04)")
    ap.add_argument("--session", default="89", help="StartDiagnosticSession subfn hex (default 89)")
    ap.add_argument("--send", action="store_true", help="actually send the key (uses a lockout attempt)")
    ap.add_argument("--op-le", action="store_true", help="read SA2 bytecode operands little-endian")
    ap.add_argument("--key-le", action="store_true", help="send the key little-endian (byte-swapped)")
    ap.add_argument("--seed-le", action="store_true", help="load the seed little-endian")
    a=ap.parse_args()
    seed_sf=a.level; key_sf=a.level+1
    c=RawCAN(); tp=TP20KWP(c)
    try:
        if not tp.open(): print("[!] could not open TP2.0 channel — ignition ON?"); return
        print(f"[*] channel OPEN  we TX->0x{tp.tx:03x} RX<-0x{tp.rx:03x}")
        print(f"  Session 10 {a.session} -> {kfmt(tp.request(bytes.fromhex('10'+a.session)))}")
        sr = tp.request(bytes([0x27, seed_sf]))
        print(f"  27 {seed_sf:02x} (request seed) -> {kfmt(sr)}")
        if not sr or sr[0]!=0x67 or len(sr)<6:
            print("  [!] no seed; aborting"); return
        seed_bytes=sr[2:6]; seed=int.from_bytes(seed_bytes,'little' if a.seed_le else 'big')
        key=Sa2SeedKey(SA2_TAPE, seed, le_operand=a.op_le).execute()
        kb=key.to_bytes(4,'little' if a.key_le else 'big')
        variant=f"seed{'LE' if a.seed_le else 'BE'} op{'LE' if a.op_le else 'BE'} key{'LE' if a.key_le else 'BE'}"
        print(f"      seed = {seed_bytes.hex(' ')} (0x{seed:08x})")
        print(f"      KEY  = {kb.hex(' ')} (0x{key:08x})   [SA2 from SGO; {variant}]")
        if a.send:
            print(f"  >>> SENDING 27 {key_sf:02x} {kb.hex(' ')} ...")
            kr=tp.request(bytes([0x27, key_sf])+kb)
            print(f"  27 {key_sf:02x} (send key) -> {kfmt(kr)}")
            if kr and kr[0]==0x67: print("  *** UNLOCKED ***")
        else:
            print(f"  [dry-run] would send: 27 {key_sf:02x} {kb.hex(' ')}   (re-run with --send)")
    finally:
        tp.close(); c.close()

if __name__=="__main__":
    main()
