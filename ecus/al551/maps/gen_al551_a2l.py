#!/usr/bin/env python3
"""Generate al551.a2l — an ASAP2 1.71 tuning description for the Audi AL551 TCU
(ZF 8HP, Renesas SH72519 SH-2A, big-endian; image 8R0927158AM SW1003).

METADATA ONLY: emits addresses / names / scalings recovered by the RE in this pack
(CAN tables, calibration-map RE, control-loop traces, init-emulator RAM resolution)
plus VW MLB DBC signal layouts. Contains no firmware bytes / no decompiled code.

Inputs (pack-relative, committed metadata):
  analysis/can_map.csv         - CAN sender/receiver inventory
  analysis/can_rx_buffers.csv  - RX data-buffer RAM addresses
  analysis/can_tx_buffers.csv  - TX frame-buffer RAM addresses
  analysis/torque_maps.csv     - input-torque-limit Kennfelder (0x1b0cc0+)
  analysis/shift_curves.csv    - shift-curve output columns (shared rpm axis)
  opendbc vw_mlb.dbc           - DBC signal layouts (optional; skipped if absent)

Run:  python3 gen_al551_a2l.py   ->  writes ../maps/al551.a2l
"""
import csv, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)                    # ecus/al551
A    = os.path.join(BASE, "analysis")
DBC  = "/home/om/openpilot/opendbc_repo/opendbc/dbc/vw_mlb.dbc"

# Flash/RAM memory map (bri3d VW_Flash#123 + SH72519). attr: CODE/DATA/RESERVED
SEGMENTS = [
    ("RESERVED_boot", 0x000000, 0x040000, "RESERVED", "FLASH"),
    ("CODE_asw",      0x040080, 0x13FAF0, "CODE",     "FLASH"),
    ("CODE_boot2",    0x180280, 0x00FD80, "CODE",     "FLASH"),
    ("DATA_cal",      0x190000, 0x06FD60, "DATA",     "FLASH"),   # CRC32 @0x180244
    ("RAM_signals",   0xFFF80000, 0x40000, "DATA",    "RAM"),
]
CAL_CRC_ADDR = 0x180244

# Control-loop RAM signals recovered by tracing (MEASUREMENTs). (addr,name,dtype,cm,comment)
RAM_SIGNALS = [
    (0xfff95175, "CHARISMA_FahrPr_latched", "UBYTE", "CM_IDENT", "Latched drive program, echoed Getriebe_04"),
    (0xfff95172, "CHARISMA_FahrPr_input",   "UBYTE", "CM_IDENT", "Drive-program input from Charisma_01(0x385)"),
    (0xfff89454, "CHARISMA_FahrPr_rx",      "UBYTE", "CM_IDENT", "Decoded Charisma_01 drive-program byte"),
    (0xfff8c814, "TorqueLimit_result_0",    "UWORD", "CM_NM",    "Input-torque-limit map result cell 0"),
    (0xfff8c81c, "TorqueLimit_result_1",    "UWORD", "CM_NM",    "Input-torque-limit map result cell 1"),
    (0xfff8c824, "TorqueLimit_result_2",    "UWORD", "CM_NM",    "Input-torque-limit map result cell 2"),
    (0xfff95524, "TCU_OutputShaftSpeed",    "UWORD", "CM_RPM",   "Output-shaft speed (gear-ratio numerator)"),
    (0xfff95518, "TCU_InputSpeed_gear",     "UWORD", "CM_RPM",   "Per-gear input/turbine speed (6 words 0xfff95518..22)"),
]

def load_tx_signals():
    want = {"Getriebe_01","Getriebe_02","Getriebe_03","Getriebe_04","WBA_01","Waehlhebel_02"}
    out, cur = [], None
    try:
        for ln in open(DBC):
            m = re.match(r"^BO_ \d+ (\w+):", ln)
            if m: cur = m.group(1) if m.group(1) in want else None
            s = re.match(r"^ SG_ (\w+)[^:]*: (\d+)\|(\d+)@\d[+-] \(([-\d.]+),([-\d.]+)\)", ln)
            if s and cur:
                nm, sb, sl, fac, off = s.groups()
                if nm in ("CHECKSUM","COUNTER"): continue
                out.append((cur, nm, int(sb), int(sl), float(fac), float(off)))
    except FileNotFoundError:
        pass
    return out

def rd(name):
    p = os.path.join(A, name)
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []

def emit():
    rxbufs = rd("can_rx_buffers.csv")
    txbufs = rd("can_tx_buffers.csv")
    tqmaps = rd("torque_maps.csv")
    shifts = rd("shift_curves.csv")
    txsig  = load_tx_signals()
    L=[]; P=L.append

    P('ASAP2_VERSION 1 71')
    P('/begin PROJECT AL551 "Audi AL551 / ZF 8HP TCU (Renesas SH72519, big-endian)"')
    P('  /begin HEADER "AL551 tuning A2L - RE in ecus/al551 (CAN + control loops + cal maps)"')
    P('    VERSION "8R0927158AM_1003"')
    P('  /end HEADER')
    P('  /begin MODULE AL551 "ZF 8HP45/8HP55 TCU; Q5/SQ5 3.0T; SW1003"')
    P('    /begin MOD_COMMON "big-endian SH-2A, byte-aligned"')
    P('      BYTE_ORDER MSB_FIRST')
    P('      ALIGNMENT_BYTE 1  ALIGNMENT_WORD 2  ALIGNMENT_LONG 4')
    P('    /end MOD_COMMON')
    # --- MOD_PAR ---
    P('    /begin MOD_PAR "flash/RAM layout (bri3d VW_Flash#123 + SH72519 map)"')
    P(f'      /* CAL CRC32 over 0x190000..0x1FFD5F stored at 0x{CAL_CRC_ADDR:06X} */')
    for nm,start,size,attr,mt in SEGMENTS:
        P(f'      /begin MEMORY_SEGMENT {nm} "{attr}" {attr} {mt} INTERN 0x{start:X} 0x{size:X} -1 -1 -1 -1 -1')
        P('      /end MEMORY_SEGMENT')
    P('    /end MOD_PAR')
    # --- COMPU_METHODs ---
    P('    /begin COMPU_METHOD CM_IDENT "identity" IDENTICAL "%.0f" "" /end COMPU_METHOD')
    P('    /begin COMPU_METHOD CM_RAW "raw byte" IDENTICAL "%.0f" "-" /end COMPU_METHOD')
    P('    /begin COMPU_METHOD CM_RPM "engine/turbine speed" IDENTICAL "%.0f" "rpm" /end COMPU_METHOD')
    P('    /begin COMPU_METHOD CM_KMH "vehicle speed" LINEAR "%.2f" "km/h" COEFFS_LINEAR 0.01 0 /end COMPU_METHOD')
    P('    /begin COMPU_METHOD CM_NM "torque" IDENTICAL "%.0f" "Nm" /end COMPU_METHOD')
    P('    /begin COMPU_METHOD CM_PCT "throttle/load" IDENTICAL "%.1f" "%" /end COMPU_METHOD')
    # --- RECORD_LAYOUTs ---
    for t,sz in (("U8","UBYTE"),("U16","UWORD"),("U32","ULONG"),("S16","SWORD")):
        P(f'    /begin RECORD_LAYOUT RL_{t} FNC_VALUES 1 {sz} ROW_DIR DIRECT /end RECORD_LAYOUT')
    P('    /begin RECORD_LAYOUT RL_AXIS_U16 AXIS_PTS_X 1 UWORD INDEX_INCR DIRECT /end RECORD_LAYOUT')
    P('    /begin RECORD_LAYOUT RL_CURVE_U16 FNC_VALUES 1 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT')
    P('    /begin RECORD_LAYOUT RL_MAP_U16 FNC_VALUES 1 UWORD COLUMN_DIR DIRECT /end RECORD_LAYOUT')

    # --- shared axes (AXIS_PTS COM_AXIS) ---
    # shift-curve shared rpm input axis lives at record+0 ; a canonical copy is at 0x1d3330
    P('    /* shared shift-curve input axis [1340 2015 3000 3770 4885 6300 7500] rpm */')
    P('    /begin AXIS_PTS AX_shift_rpm "shift input rpm axis (7pt)" 0x1d3330 '
      'NO_INPUT_QUANTITY RL_AXIS_U16 0 CM_RPM 7 0 8000 /end AXIS_PTS')
    # torque-limit engine-torque column axis [0 48 102 198 300 402 498 600] at first kennfeld+0x1c
    tq0 = int(tqmaps[0]["kennfeld_addr"],16) if tqmaps else 0x1b0cc0
    P('    /* torque-limit engine-input-torque column axis (8pt, 0..600 Nm) */')
    P(f'    /begin AXIS_PTS AX_tq_col "engine input torque axis (Nm)" 0x{tq0+0x1c:06x} '
      'NO_INPUT_QUANTITY RL_AXIS_U16 0 CM_NM 8 0 600 /end AXIS_PTS')
    P(f'    /begin AXIS_PTS AX_tq_row "torque-map row axis (10pt)" 0x{tq0+0x4:06x} '
      'NO_INPUT_QUANTITY RL_AXIS_U16 0 CM_IDENT 10 0 4096 /end AXIS_PTS')

    # --- MEASUREMENTs: CAN RX raw buffers ---
    P('    /* ---- CAN RX 8-byte frame buffers (on-chip RAM) ---- */')
    for r in rxbufs:
        idx=r.get("msg_index","?"); addr=r.get("databuf_ram")
        if not addr: continue
        P(f'    /begin MEASUREMENT CANRX_buf_{idx} "CAN RX frame buffer msg_index {idx}" '
          f'UBYTE CM_RAW 0 0 0 255 ECU_ADDRESS {addr} MATRIX_DIM 8 /end MEASUREMENT')
    # --- MEASUREMENTs: CAN TX frame buffers ---
    P('    /* ---- CAN TX frame buffers ---- */')
    for r in txbufs:
        msg=r.get("dbc_message","?"); frame=r.get("frame_ram"); dlc=int(r.get("dlc",8))
        if not frame: continue
        P(f'    /begin MEASUREMENT CANTX_{msg} "TX frame {r.get("can_id","")} {msg}" '
          f'UBYTE CM_RAW 0 0 0 255 ECU_ADDRESS {frame} MATRIX_DIM {dlc} /end MEASUREMENT')
    # --- MEASUREMENTs: traced control-loop RAM signals ---
    P('    /* ---- traced control-loop RAM signals ---- */')
    for addr,name,dt,cm,cmt in RAM_SIGNALS:
        hi = 255 if dt=="UBYTE" else 65535
        P(f'    /begin MEASUREMENT {name} "{cmt}" {dt} {cm} 0 0 0 {hi} '
          f'ECU_ADDRESS 0x{addr:08x} /end MEASUREMENT')

    # --- CHARACTERISTICs: input-torque-limit Kennfelder ---
    P('    /* ==== TUNABLE: input-torque-limit Kennfelder (gear x mode selected) ==== */')
    for r in tqmaps:
        a=int(r["kennfeld_addr"],16); grid=a+0x2c
        P(f'    /begin CHARACTERISTIC TQLIM_{a:06x} "input-torque limit Nm @0x{a:06x} (10x8 grid)" '
          f'MAP 0x{grid:06x} RL_MAP_U16 0 CM_NM 0 4950')
        P('      /begin AXIS_DESCR COM_AXIS NO_INPUT_QUANTITY CM_NM 8 0 600 AXIS_PTS_REF AX_tq_col /end AXIS_DESCR')
        P('      /begin AXIS_DESCR COM_AXIS NO_INPUT_QUANTITY CM_IDENT 10 0 4096 AXIS_PTS_REF AX_tq_row /end AXIS_DESCR')
        P('    /end CHARACTERISTIC')
    # --- CHARACTERISTICs: shift curves (output columns) ---
    P('    /* ==== TUNABLE: shift-curve output columns (shift-RPM thresholds) ==== */')
    for r in shifts:
        a=int(r["record_addr"],16); out=a+0xe   # output column starts after 7-pt input axis
        P(f'    /begin CHARACTERISTIC SHIFT_{a:06x} "shift curve out-col @0x{a:06x} (max {r.get("out_max","")})" '
          f'CURVE 0x{out:06x} RL_CURVE_U16 0 CM_RPM 0 8000')
        P('      /begin AXIS_DESCR COM_AXIS NO_INPUT_QUANTITY CM_RPM 7 0 8000 AXIS_PTS_REF AX_shift_rpm /end AXIS_DESCR')
        P('    /end CHARACTERISTIC')

    # --- GROUPs ---
    P('    /begin GROUP CAN "CAN RX/TX buffers" ROOT /end GROUP')
    P('    /begin GROUP TorqueLimit "input-torque-limit Kennfelder" ROOT /end GROUP')
    P('    /begin GROUP ShiftPoints "shift-curve output columns" ROOT /end GROUP')
    P('    /begin GROUP Charisma "drive-program (echo-only on this SW)" ROOT /end GROUP')
    P('  /end MODULE')
    P('/end PROJECT')
    return "\n".join(L)+"\n"

if __name__ == "__main__":
    out = os.path.join(HERE, "al551.a2l")
    open(out,"w").write(emit())
    print("wrote", out)
