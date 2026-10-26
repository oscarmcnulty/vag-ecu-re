import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/home/om/openpilot")
from openpilot.tools.lib.logreader import LogReader
import numpy as np

SEGS = sys.argv[1:]
def ule(d, st, w):
    v = 0
    for i in range(w):
        b = st + i
        if b // 8 >= len(d): return None
        v |= ((d[b // 8] >> (b % 8)) & 1) << i
    return v

IDX, DIST, VREL = [], [], []
for SEG in SEGS:
    lt, ld, lp, lv = [], [], [], []
    rows = []
    for m in LogReader(SEG):
        w = m.which()
        if w == "modelV2":
            try:
                L = m.modelV2.leadsV3[0]
                lt.append(m.logMonoTime*1e-9); ld.append(float(L.x[0]))
                lp.append(float(L.prob)); lv.append(float(L.v[0]))
            except Exception: pass
        elif w == "can":
            t = m.logMonoTime*1e-9
            for c in m.can:
                if c.src == 2 and c.address == 0x30c: rows.append((t, bytes(c.dat)))
    lt = np.array(lt); ld = np.array(ld); lp = np.array(lp); lv = np.array(lv)
    if len(lt) < 10 or not rows:
        print(f"{SEG.split('/')[-1]}: insufficient"); continue
    for t, d in rows:
        rel = ule(d, 46, 2); idx = ule(d, 24, 10)
        if rel != 1: continue
        k = np.searchsorted(lt, t); k = min(max(k, 1), len(lt)-1)
        if lp[k] > 0.8 and 5 < idx < 1000:      # object present both sides, drop sentinel
            IDX.append(idx); DIST.append(ld[k]); VREL.append(lv[k])
    print(f"{SEG.split('/')[-1]}: {len([x for x in IDX])} cumulative obj frames")

IDX = np.array(IDX, float); DIST = np.array(DIST, float)
print(f"\nTOTAL object-present frames: {len(IDX)}")
if len(IDX) < 30:
    print("not enough data"); sys.exit()
print(f"Abstandsindex range {IDX.min():.0f}..{IDX.max():.0f};  modelDist {DIST.min():.0f}..{DIST.max():.0f}m")

def fit_report(name, x, y):
    A = np.polyfit(x, y, 1)
    pred = np.polyval(A, x)
    ss = 1 - ((y-pred)**2).sum()/((y-y.mean())**2).sum()
    print(f"  {name:22} R2={ss:+.3f}  dist = {A[0]:.4f}*X {A[1]:+.1f}")
    return ss

print("\n=== functional forms (X -> modelDist) ===")
fit_report("linear(idx)", IDX, DIST)
fit_report("inverse(1/idx)", 1.0/IDX, DIST)
fit_report("inverse(1000/idx)", 1000.0/IDX, DIST)
fit_report("sqrt(idx)", np.sqrt(IDX), DIST)
fit_report("log(idx)", np.log(IDX), DIST)
# binned monotonicity check
print("\n=== binned (idx -> mean modelDist) ===")
for lo in range(0, 1000, 100):
    m = (IDX >= lo) & (IDX < lo+100)
    if m.sum() > 5:
        print(f"  idx {lo:4}-{lo+99}: dist {DIST[m].mean():6.1f}m  (n={m.sum()}, sd {DIST[m].std():.1f})")
# raw corr
print(f"\nPearson corr(idx, dist) = {np.corrcoef(IDX, DIST)[0,1]:+.3f}")
