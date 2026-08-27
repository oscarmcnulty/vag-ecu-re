#!/usr/bin/env python3
"""Simos 8.5 SecurityAccess "SA2" seed->key interpreter.

The SA2 bytecode ships in the ECU's own flash container
(ecus/simos85/frf_extract/FL_8R0907551F__0007.odx):
    <SECURITY-METHOD>SA2</SECURITY-METHOD>
    <FW-SIGNATURE>6805824A10680493300419624A05871510197082499324041966824A0587...

SA2 is a tiny bytecode VM over a SINGLE 32-bit register (seeded with the challenge)
plus a carry bit and a loop stack. This implementation is the VM as verified against
this repo's firmware and the acceptance test: running it on the bytecode below yields
seed 0x00000000 -> 0x4DCC7D0C, 0xDEADBEEF -> 0x55612515, 0xFFFFFFFF -> 0x30CFB280
(and the ECU-side check in CBOOT computes the same key from the same seed).

Opcode set (operand widths are what make the stream parse):
    0x81 RSL           rotate register left  1 bit  (carry <- old bit31)
    0x82 RSR           rotate register right 1 bit  (carry <- old bit0)
    0x84 SUB imm32     reg -= imm32                          (4-byte big-endian imm)
    0x93 ADD imm32     reg += imm32   (carry set on 32-bit overflow)
    0x87 EOR imm32     reg ^= imm32
    0x68 FOR n         push loop: iterations = n-1, body starts at next ip
    0x49 NEXT          if iterations>0: dec + jump to body; else pop loop
    0x4A BCC k         if carry==0: ip += k+2 ; else ip += 2   (branch on carry clear)
    0x6B BRA k         ip += k+2  (unconditional)
    0x4C FIN           terminator / no-op (execution ends by running off the tape)

An earlier version of this file used a made-up register-file model with wrong operand
widths; it is replaced by this verified VM. (Bytes 0x19/0x04 are NOT opcodes here — they
only ever occur inside 4-byte immediates, e.g. 0x30041962, 0x24041966.)
"""
from __future__ import annotations
import argparse

MASK = 0xFFFFFFFF

# The Simos 8.5 (8R0907551F) SA2 bytecode, verbatim from the ODX container.
SIMOS85_SA2 = bytes.fromhex(
    "6805824A10680493300419624A05871510197082499324041966824A058702031970824A0181494C")

_NAMES = {0x81: "RSL", 0x82: "RSR", 0x84: "SUB", 0x93: "ADD", 0x87: "EOR",
          0x68: "FOR", 0x49: "NEXT", 0x4A: "BCC", 0x6B: "BRA", 0x4C: "FIN"}
_IMM32 = {0x84, 0x93, 0x87}
_ARG1 = {0x68, 0x4A, 0x6B}


def disassemble(code: bytes):
    """Yield (ip, opcode, operand_int_or_None) — for auditing the program."""
    ip = 0
    while ip < len(code):
        op = code[ip]
        if op in _IMM32:
            yield ip, op, int.from_bytes(code[ip + 1:ip + 5], "big"); ip += 5
        elif op in _ARG1:
            yield ip, op, code[ip + 1]; ip += 2
        else:
            yield ip, op, None; ip += 1


def pretty(code: bytes) -> str:
    out = []
    for ip, op, arg in disassemble(code):
        name = _NAMES.get(op, f"?{op:02x}")
        if arg is None:
            out.append(f"  {ip:3} {name}")
        elif op in _IMM32:
            out.append(f"  {ip:3} {name} 0x{arg:08x}")
        else:
            out.append(f"  {ip:3} {name} {arg}")
    return "\n".join(out)


def seed_to_key(code: bytes, seed: int, max_steps: int = 1_000_000) -> int:
    reg = seed & MASK
    carry = 0
    ip = 0
    loops = []            # [iterations_remaining, body_ip]
    steps = 0
    while ip < len(code):
        steps += 1
        if steps > max_steps:
            raise RuntimeError("SA2 program did not terminate")
        op = code[ip]
        if op == 0x81:                                    # RSL
            carry = (reg >> 31) & 1
            reg = ((reg << 1) | carry) & MASK
            ip += 1
        elif op == 0x82:                                  # RSR
            carry = reg & 1
            reg = ((reg >> 1) | (carry << 31)) & MASK
            ip += 1
        elif op == 0x87:                                  # EOR imm32
            reg = (reg ^ int.from_bytes(code[ip + 1:ip + 5], "big")) & MASK
            ip += 5
        elif op == 0x93:                                  # ADD imm32
            s = reg + int.from_bytes(code[ip + 1:ip + 5], "big")
            carry = 1 if s > MASK else 0
            reg = s & MASK
            ip += 5
        elif op == 0x84:                                  # SUB imm32
            reg = (reg - int.from_bytes(code[ip + 1:ip + 5], "big")) & MASK
            ip += 5
        elif op == 0x68:                                  # FOR n
            loops.append([code[ip + 1] - 1, ip + 2])
            ip += 2
        elif op == 0x49:                                  # NEXT
            if loops and loops[-1][0] > 0:
                loops[-1][0] -= 1
                ip = loops[-1][1]
            else:
                if loops:
                    loops.pop()
                ip += 1
        elif op == 0x4A:                                  # BCC k
            ip += (code[ip + 1] + 2) if carry == 0 else 2
        elif op == 0x6B:                                  # BRA k
            ip += code[ip + 1] + 2
        elif op == 0x4C:                                  # FIN
            ip += 1
        else:
            ip += 1
    return reg & MASK


def main():
    ap = argparse.ArgumentParser(description="Simos8.5 SA2 seed->key")
    ap.add_argument("seed", nargs="?", help="4-byte seed hex, e.g. DEADBEEF")
    ap.add_argument("--bytecode", default=SIMOS85_SA2.hex())
    a = ap.parse_args()
    code = bytes.fromhex(a.bytecode)
    print("SA2 disassembly:")
    print(pretty(code))
    if a.seed:
        seed = int(a.seed, 16)
        print(f"\nseed 0x{seed:08x} -> key 0x{seed_to_key(code, seed):08x}")


if __name__ == "__main__":
    main()
