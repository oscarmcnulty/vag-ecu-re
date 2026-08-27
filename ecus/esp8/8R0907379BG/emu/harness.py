#!/usr/bin/env python3
# Unicorn emulation harness for the Bosch ESP8 (8R0907379BG) ARM BE32 firmware.
# Function-level emulation: map flash+RAM+stack, call a function with args, log RAM
# writes and unmapped (MMIO/peripheral) accesses. Auto-detects ARM vs Thumb per entry.
import os, struct
from unicorn import *
from unicorn.arm_const import *
import capstone

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(HERE, "..", "firmware", "8R0907379BG_0030.bin")

FLASH_BASE = 0x0
RAM_BASE, RAM_SIZE     = 0x00400000, 0x00200000   # 0x400000-0x600000
STACK_BASE, STACK_SIZE = 0x00300000, 0x00080000
RET_MAGIC  = 0xFFFFFFF0

_md_arm = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM|capstone.CS_MODE_BIG_ENDIAN)
_md_thm = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB|capstone.CS_MODE_BIG_ENDIAN)

class Emu:
    def __init__(self, verbose=False):
        self.fw = open(FW,'rb').read()
        self.verbose = verbose
        self.reset()

    def reset(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM|UC_MODE_BIG_ENDIAN)
        fsize = (len(self.fw)+0xFFFF) & ~0xFFFF
        self.uc.mem_map(FLASH_BASE, max(fsize, 0x140000))
        self.uc.mem_write(FLASH_BASE, self.fw)
        self.uc.mem_map(RAM_BASE, RAM_SIZE)
        self.uc.mem_map(STACK_BASE, STACK_SIZE)
        self.writes = []          # (pc, addr, size, value)
        self.mmio   = {}          # addr -> {'r':n,'w':n,'wvals':[]}
        self.mapped_extra = set()
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._on_write)
        self.uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED
                         | UC_HOOK_MEM_FETCH_UNMAPPED, self._on_unmapped)
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)

    # --- hooks ---
    def _on_write(self, uc, access, addr, size, value, ud):
        pc = uc.reg_read(UC_ARM_REG_PC)
        self.writes.append((pc, addr, size, value))

    def _on_unmapped(self, uc, access, addr, size, value, ud):
        page = addr & ~0xFFF
        if page not in self.mapped_extra:
            try:
                uc.mem_map(page, 0x1000); self.mapped_extra.add(page)
            except UcError:
                pass
        rec = self.mmio.setdefault(addr, {'r':0,'w':0,'wvals':[]})
        if access in (UC_MEM_WRITE_UNMAPPED,):
            rec['w'] += 1; rec['wvals'].append(value)
        else:
            rec['r'] += 1
        return True   # continue after mapping

    def _on_intr(self, uc, intno, ud):
        # SVC/software_interrupt (COM critical sections) -> just continue
        return

    # --- memory helpers (big-endian) ---
    def wr(self, addr, value, size=4):
        self.uc.mem_write(addr, int(value).to_bytes(size,'big'))
    def rd(self, addr, size=4):
        return int.from_bytes(self.uc.mem_read(addr, size),'big')
    def rds(self, addr, size=2):
        v = self.rd(addr,size); bits=size*8
        return v-(1<<bits) if v>=(1<<(bits-1)) else v

    # --- ARM/Thumb detection: valid function prologue? ---
    def detect_thumb(self, addr):
        b = self.fw[addr:addr+4]
        # Thumb push {..,lr}: 0xB5xx ; ARM push: 0xE92Dxxxx (stmfd sp!,{..,lr})
        if b[0]==0xE9 and b[1]==0x2D: return False
        if b[0]==0xB5: return True
        # fallback: whichever disassembles to push/stmdb
        try:
            i=next(_md_thm.disasm(b,addr));
            if i.mnemonic.startswith('push'): return True
        except StopIteration: pass
        try:
            i=next(_md_arm.disasm(b,addr))
            if i.mnemonic.startswith(('push','stmdb','stmfd')): return False
        except StopIteration: pass
        return False

    def call(self, addr, args=(), thumb=None, maxinsn=500000, trace=False):
        if thumb is None: thumb = self.detect_thumb(addr)
        for i,a in enumerate(args[:4]):
            self.uc.reg_write(UC_ARM_REG_R0+i, a & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_SP, STACK_BASE+STACK_SIZE-0x200)
        self.uc.reg_write(UC_ARM_REG_LR, RET_MAGIC)
        self.writes = []
        if trace:
            self._trace_hh = self.uc.hook_add(UC_HOOK_CODE, self._on_code)
        start = addr | (1 if thumb else 0)
        try:
            self.uc.emu_start(start, RET_MAGIC, count=maxinsn)
        except UcError as e:
            return ('ERR', str(e), self.uc.reg_read(UC_ARM_REG_PC))
        finally:
            if trace: self.uc.hook_del(self._trace_hh)
        return ('OK', self.uc.reg_read(UC_ARM_REG_R0))

    def _on_code(self, uc, addr, size, ud):
        code = uc.mem_read(addr, size)
        thumb = uc.reg_read(UC_ARM_REG_CPSR) & (1<<5)
        md = _md_thm if thumb else _md_arm
        for i in md.disasm(bytes(code), addr):
            print(f"    {addr:08x}: {i.mnemonic:8s} {i.op_str}")
            break

if __name__ == "__main__":
    # VALIDATION: ecd_emergency_pressure (0x9c788, Thumb) should copy the ANB request
    # value at 0x407c0a into all 6 setpoints at 0x403d94..0x403d9e.
    e = Emu()
    MARK = 0x1234
    e.wr(0x407c0a, MARK, 2)                 # ANB request value (DAT_0009c810[3])
    res = e.call(0x9c788)
    print("call ecd_emergency_pressure ->", res)
    sp = [e.rds(0x403d94 + 2*i, 2) for i in range(6)]
    print("setpoints 0x403d94[0..5] =", [hex(x & 0xffff) for x in sp])
    ok = all((x & 0xffff)==MARK for x in sp)
    print("VALIDATION", "PASS ✓" if ok else "FAIL ✗", "(all 6 == request value)")
    if e.mmio:
        print("unmapped/MMIO touched:", {hex(a):v for a,v in list(e.mmio.items())[:10]})
