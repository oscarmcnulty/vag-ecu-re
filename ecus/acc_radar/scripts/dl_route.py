import json, os, time, sys, urllib.request
tok = json.load(open("/home/om/.comma/auth.json"))["access_token"]
import requests
R = "15e6fc3f7f90b0c5|00000051--957a33a9e7"
h = {"Authorization": f"JWT {tok}"}
d = requests.get(f"https://api.commadotai.com/v1/route/{R}/files", headers=h, timeout=30).json()
logs = d["logs"]
DEST = "/home/om/vag-ecu-re/captures/00000051--957a33a9e7"
os.makedirs(DEST, exist_ok=True)

def seg_of(u):
    # .../00000051--957a33a9e7/<seg>/rlog.zst?...
    base = u.split("?")[0]
    parts = base.split("/")
    return int(parts[-2])

# sort by segment number
logs = sorted(logs, key=seg_of)
ok = 0
for u in logs:
    seg = seg_of(u)
    out = f"{DEST}/seg{seg}.rlog.zst"
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        print(f"seg{seg}: cached", flush=True); ok += 1; continue
    for attempt in range(3):
        try:
            t = time.monotonic()
            with requests.get(u, stream=True, timeout=120) as r:  # URL unmodified, no JWT to Azure
                r.raise_for_status()
                with open(out, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            print(f"seg{seg}: {os.path.getsize(out)} bytes {time.monotonic()-t:.1f}s", flush=True)
            ok += 1
            break
        except Exception as e:
            print(f"seg{seg}: attempt {attempt} failed: {e}", flush=True)
            time.sleep(2)
print(f"DONE {ok}/{len(logs)} segments -> {DEST}", flush=True)
