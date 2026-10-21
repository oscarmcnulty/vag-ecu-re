import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/om/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

SEG = sys.argv[1] if len(sys.argv) > 1 else "/home/om/vag-ecu-re/captures/00000051--957a33a9e7/seg5.rlog.zst"
BUS = 2
CANDS = [0x30c, 0x311, 0x117, 0x30f, 0x63a, 0x63c, 0x63d, 0x109, 0x10d]

lead_t, lead_d, lead_p, lead_v = [], [], [], []
can = {a: [] for a in CANDS}
for m in LogReader(SEG):
    w = m.which()
    if w == "modelV2":
        try:
            L = m.modelV2.leadsV3[0]
            lead_t.append(m.logMonoTime * 1e-9); lead_d.append(float(L.x[0]))
            lead_p.append(float(L.prob)); lead_v.append(float(L.v[0]))
        except Exception: pass
    elif w == "can":
        t = m.logMonoTime * 1e-9
        for c in m.can:
            if c.src == BUS and c.address in can:
                can[c.address].append((t, bytes(c.dat)))

lead_t = np.array(lead_t); lead_d = np.array(lead_d); lead_p = np.array(lead_p)
present = lead_p > 0.5
if present.any():
    print(f"model lead: {present.sum()}/{len(lead_p)} present; dist {lead_d[present].min():.1f}..{lead_d[present].max():.1f}m std {lead_d[present].std():.1f}")
else:
    print("NO model lead in this segment");

def ule(d, st, w):
    v = 0
    for i in range(w):
        b = st + i
        if b // 8 >= len(d): return None
        v |= ((d[b // 8] >> (b % 8)) & 1) << i
    return v

def series(rows, st, w):
    T, V = [], []
    for t, d in rows:
        v = ule(d, st, w)
        if v is not None: T.append(t); V.append(v)
    return np.array(T), np.array(V)

def corr(ts, vs):
    if len(ts) < 20: return None
    idx = np.searchsorted(lead_t, ts).clip(1, len(lead_t) - 1)
    ld = lead_d[idx]; lp = lead_p[idx]
    m = lp > 0.5
    if m.sum() < 15: return None
    v = vs[m].astype(float); d = ld[m]
    if v.std() < 1e-6 or d.std() < 1e-6: return None
    r = np.corrcoef(v, d)[0, 1]
    nm = lp <= 0.5
    sep = abs(v.mean() - vs[nm].astype(float).mean()) / (vs.std() + 1e-6) if nm.sum() > 15 else 0
    return r, v.min(), v.max(), sep

print("\n=== 0x311 explicit (byte0, byte1, 16-bit combos) ===")
r311 = can[0x311]
for name, st, w in [("byte0", 0, 8), ("byte1", 8, 8), ("b0|b1<<8", 0, 16), ("byte2", 16, 8), ("byte3", 24, 8)]:
    ts, vs = series(r311, st, w)
    c = corr(ts, vs)
    uq = len(set(vs.tolist())) if len(vs) else 0
    print(f"  {name:10} uniq={uq:3} range {vs.min() if len(vs) else '-'}..{vs.max() if len(vs) else '-'}"
          + (f"  corr={c[0]:+.2f} sep={c[3]:.2f}" if c else "  (const/insuff)"))

print("\n=== ACC_02 (0x30c) known fields ===")
for name, st, w in [("Abstandsindex", 24, 10), ("Relevantes_Objekt", 46, 2), ("Wunschgeschw", 12, 10)]:
    ts, vs = series(can[0x30c], st, w)
    c = corr(ts, vs); uq = len(set(vs.tolist())) if len(vs) else 0
    print(f"  {name:18} uniq={uq:3} range {vs.min() if len(vs) else '-'}..{vs.max() if len(vs) else '-'}"
          + (f"  corr={c[0]:+.2f} sep={c[3]:.2f}" if c else "  (const/insuff)"))

print("\n=== brute force all candidates (|corr|>0.4 or sep>2) ===")
res = []
for a in CANDS:
    rows = can[a]
    if len(rows) < 50: continue
    nb = min(len(rows[0][1]), 8) * 8
    for w in (8, 10, 12, 16):
        for st in range(0, nb - w + 1):
            ts, vs = series(rows, st, w)
            if len(vs) < 50 or len(set(vs.tolist())) < 4: continue
            c = corr(ts, vs)
            if c and (abs(c[0]) > 0.4 or c[3] > 2):
                res.append((abs(c[0]), c[0], c[3], a, st, w, c[1], c[2], len(set(vs.tolist()))))
res.sort(reverse=True)
for ar, r, sep, a, st, w, lo, hi, uq in res[:25]:
    print(f"  {a:#06x} bit{st:2}+{w:2}: corr={r:+.2f} sep={sep:.2f} range {lo:.0f}..{hi:.0f} uniq={uq}")

# timeline for the single best correlate
if res:
    _, r, sep, a, st, w, lo, hi, uq = res[0]
    ts, vs = series(can[a], st, w)
    idx = np.searchsorted(lead_t, ts).clip(1, len(lead_t) - 1)
    print(f"\n=== timeline best: {a:#06x} bit{st}+{w} vs model lead ===")
    step = max(1, len(ts) // 20)
    for k in range(0, len(ts), step):
        print(f"  t={ts[k]-ts[0]:5.1f}s  field={vs[k]:6}  modelDist={lead_d[idx[k]]:5.1f}m prob={lead_p[idx[k]]:.2f}")
