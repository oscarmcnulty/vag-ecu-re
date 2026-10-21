import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/om/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np
from collections import Counter

SEGS = sys.argv[1:]
def ule(d, st, w):
    v = 0
    for i in range(w):
        b = st + i
        if b // 8 >= len(d): return None
        v |= ((d[b // 8] >> (b % 8)) & 1) << i
    return v

# ACC_02 (0x30c) signal map from vw_mlb.dbc: name -> (startbit, width, scale, offset)
SIGS = [
    ("ACC_Wunschgeschw_02", 12, 10, 0.32, 0),
    ("ACC_Status_Prim_Anz", 22, 2, 1, 0),
    ("ACC_Abstandsindex", 24, 10, 1, 0),
    ("ACC_Akustik", 34, 3, 1, 0),
    ("ACC_Gesetzte_Zeitluecke", 37, 3, 1, 0),
    ("ACC_Optischer_Fahrerhinweis", 40, 1, 1, 0),
    ("ACC_Typ_Tachokranz", 41, 1, 1, 0),
    ("ACC_Anzeige_Zeitluecke", 42, 1, 1, 0),
    ("ACC_Tachokranz", 43, 1, 1, 0),
    ("ACC_Display_Prio", 44, 2, 1, 0),
    ("ACC_Relevantes_Objekt", 46, 2, 1, 0),
    ("ACC_Texte_Primaeranz", 48, 7, 1, 0),
    ("ACC_Wunschgeschw_erreicht", 55, 1, 1, 0),
    ("ACC_Status_Anzeige", 61, 3, 1, 0),
]

raw = []   # stock ACC_02 payloads (bus2), only when ACC engaged (TSK_04 status 1/2)
eng_now = [False]
for SEG in SEGS:
    for m in LogReader(SEG):
        if m.which() != "can": continue
        for c in m.can:
            if c.src == 1 and c.address == 0x10e and len(c.dat) >= 8:   # TSK_04 bus1
                st = (c.dat[7] & 0xC0) >> 6
                eng_now[0] = st in (1, 2)
            if c.src == 2 and c.address == 0x30c and len(c.dat) >= 8 and eng_now[0]:
                raw.append(bytes(c.dat))

print(f"stock ACC_02 frames (ACC engaged): {len(raw)}\n")
print(f"{'signal':28} {'distinct':>8}  stock values / range")
for name, stb, w, sc, off in SIGS:
    vals = [ule(d, stb, w) for d in raw]
    vals = [v for v in vals if v is not None]
    c = Counter(vals)
    uq = len(c)
    if uq <= 6:
        disp = ", ".join(f"{k}x{v}" for k, v in sorted(c.items()))
    else:
        arr = np.array(vals)
        disp = f"range {arr.min()}..{arr.max()} (e.g. top {[k for k,_ in c.most_common(4)]})"
    print(f"  {name:26} {uq:8}  {disp}")

# What openpilot's mlbcan.create_acc_hud_control SETS (for reference, acc_active case)
print("\n=== openpilot mlbcan ACC_02 spoof (what OP sets) ===")
op = {
    "ACC_Wunschgeschw_02": "set_speed (real)",
    "ACC_Status_Prim_Anz": "2 if visualAlert else (1 if acc_active else 0)",
    "ACC_Abstandsindex": "1023 if acc_active else 1022  <-- SENTINEL, never real distance",
    "ACC_Akustik": "1 if audibleAlert==5 else 0",
    "ACC_Gesetzte_Zeitluecke": "hud_control.leadDistanceBars",
    "ACC_Optischer_Fahrerhinweis": "(not set -> 0)",
    "ACC_Typ_Tachokranz": "(not set -> 0)",
    "ACC_Anzeige_Zeitluecke": "1 if acc_active else 0",
    "ACC_Tachokranz": "1 if acc_active else 0",
    "ACC_Display_Prio": "0",
    "ACC_Relevantes_Objekt": "2 if visualAlert else (1 if acc_active and leadVisible else 0)",
    "ACC_Texte_Primaeranz": "mlb_hud_text",
    "ACC_Wunschgeschw_erreicht": "(not set -> 0)",
    "ACC_Status_Anzeige": "acc_hud_status",
}
for name, _, _, _, _ in SIGS:
    print(f"  {name:26} {op.get(name,'?')}")
