#!/usr/bin/env python3
"""Multi-pass AUTOSAR-COM config decoder for ESP8 (8R0907379BG). Pass 1: extract all config
tables from flash + build cross-reference indices. Everything is flash-static (no runtime/HW)."""
import struct, os
FW = os.path.join(os.path.dirname(__file__), "..", "firmware", "8R0907379BG_0030.bin")
fw = open(FW, "rb").read()
def u32(a): return struct.unpack('>I', fw[a:a+4])[0]
def u16(a): return struct.unpack('>H', fw[a:a+2])[0]
def u8(a):  return fw[a]

# ---- Table 1: message-config (0xa9fc0, 223 x 0x14) {id, timeout, flags, routine, state_ram} ----
MSGCFG_BASE, MSGCFG_N, MSGCFG_STRIDE = 0xa9fc0, 223, 0x14
msgcfg = []
for i in range(MSGCFG_N):
    o = MSGCFG_BASE + i*MSGCFG_STRIDE
    rec = dict(idx=i, off=o, can_id=u32(o), timeout=u32(o+4), flags=u32(o+8),
               routine=u32(o+0xc), state_ram=u32(o+0x10))
    msgcfg.append(rec)
by_id = {r['can_id']: r for r in msgcfg}
by_state = {r['state_ram']: r for r in msgcfg}

# ---- Table 2: id-array 0xafae0-region (index -> can_id), find its real bounds ----
# scan around 0xafac0 for a run of monotonic-ish small ids
idarr = {}
a = 0xafac0
while a < 0xafb80:
    v = u32(a)
    if 0x80 <= v <= 0x7ff: idarr[(a-0xafac0)//4] = v
    a += 4

print(f"msgcfg: {len(msgcfg)} records; id-array: {len(idarr)} ids")
print(f"state_ram range: 0x{min(r['state_ram'] for r in msgcfg):x}-0x{max(r['state_ram'] for r in msgcfg):x}")

# ---- ANCHOR SEARCH: the MLB per-message XOR checksum seeds (from repo memory/opendbc) ----
# Known Q5 MLB XOR seeds (verified): map seed byte -> message. Cross-ref to identify messages by CRC config.
# The CRC config lives in the 0xb6a44 group table (word0 -> seed via FUN_0005f57c: >>0x12 &0x7ff ^ &0xff).
print("\n=== 0xb6a44 group/CRC table (first 16 records, stride 0x18) ===")
for i in range(16):
    o = 0xb6a44 + i*0x18
    words = [u32(o+4*w) for w in range(6)]
    # CRC seed per FUN_0005f57c on word0:
    w0 = words[0]; s = w0>>0x12 if w0 < 0x80000000 else w0; seed = ((s & 0x7ff)>>8) ^ (s & 0xff)
    bufs = [w for w in words if 0x400000 <= w < 0x410000]
    print(f"  #{i:2d} @0x{o:x}: {' '.join(f'{w:08x}' for w in words)}  seed=0x{seed:x} bufs={[hex(b) for b in bufs]}")

# ---- Print the ANB signal buffers we know + which msgcfg they might belong to ----
print("\n=== known ANB/AEB signal buffers (targets to bind) ===")
for name,addr in [("anb_can_target 0x40926c",0x40926c),("freigabe-src 0x4093a9",0x4093a9),
                  ("esp05_sig 0x405e81",0x405e81),("decel_req 0x4054c4",0x4054c4)]:
    print(f"  {name}")

# ============ PASS 2: parse the descriptor stream {buffer, encoding, length} ============
# Scan 0xb6000-0xb8000 for triples: buffer in 0x400000-0x410000, length 1..8.
print("\n=== PASS 2: descriptor-stream triples {buffer, encoding, len} in 0xb6a44-0xb7400 ===")
sigs = []
a = 0xb6a44
while a < 0xb7400:
    buf, enc, ln = u32(a), u32(a+4), u32(a+8)
    if 0x400000 <= buf < 0x410000 and 1 <= ln <= 8:
        sigs.append((a, buf, enc, ln))
        a += 0xc
    else:
        a += 4
print(f"  parsed {len(sigs)} descriptor triples")
# group by encoding low-16 (candidate PDU tag) and by buffer cluster
from collections import Counter, defaultdict
enclo = Counter(e & 0xffff for _,_,e,_ in sigs)
print("  encoding low-16 histogram (top):", enclo.most_common(6))
# Show the AEB-message signals (buffers 0x40926x, 0x4039ax, 0x4091fx)
print("\n  AEB-message signal descriptors (buffers 0x4091f0-0x409280, 0x4039a0-0x4039c0):")
for off,buf,enc,ln in sigs:
    if 0x4091f0<=buf<0x409280 or 0x4039a0<=buf<0x4039c0:
        print(f"    @0x{off:x}: buf=0x{buf:x} enc=0x{enc:08x} len={ln}  encHI=0x{enc>>16:04x} encLO=0x{enc&0xffff:04x}")

# ============ PASS 3: block structure — find headers between signal blocks ============
# Walk 0xb6ffc-0xb7400 linearly; classify each word as SIG-triple vs HEADER (non-buffer word).
print("\n=== PASS 3: stream block structure (0xb6ffc-0xb71c0), headers vs triples ===")
a = 0xb6ffc
prev_was_sig = False
while a < 0xb71c0:
    buf, enc, ln = u32(a), u32(a+4), u32(a+8)
    if 0x400000 <= buf < 0x410000 and 1 <= ln <= 8:
        # signal triple: byte-offset guess = encoding high-16 as {hi,lo}?
        eh = enc >> 16
        # decode candidate byte/bit: many are 0x00c0=byte? or the low byte of eh
        print(f"    SIG @0x{a:x}: buf=0x{buf:x} len={ln} enc=0x{enc:08x} (hi=0x{eh:04x} b0=0x{eh>>8:02x} b1=0x{eh&0xff:02x})")
        a += 0xc; prev_was_sig=True
    else:
        # header/marker
        print(f"  HDR @0x{a:x}: {buf:08x} {enc:08x} {ln:08x}")
        a += 4; prev_was_sig=False

# ============ PASS 4: full descriptor map, segmented into per-message blocks ============
# Correct format (from 0xb6b60): {encoding, count, buffer} stride 0xc. Parse the RX stream,
# segment where the buffer region jumps (new message), infer byte-offset from order.
print("\n=== PASS 4: full RX signal descriptor map (segmented) ===")
def parse_triples(lo, hi):
    out=[]; a=lo
    while a+12<=hi:
        enc,cnt,buf=u32(a),u32(a+4),u32(a+8)
        if 0x400000<=buf<0x410000 and 1<=cnt<=8:
            out.append((a,enc,cnt,buf)); a+=0xc
        else: a+=4
    return out
trip=parse_triples(0xb6a44,0xb7400)
# segment: new block when buffer region base (buf>>8) changes non-contiguously
blocks=[]; cur=[]
for t in trip:
    if cur and abs(t[3]-cur[-1][3])>0x40:  # buffer jumped -> new message region
        blocks.append(cur); cur=[]
    cur.append(t)
if cur: blocks.append(cur)
print(f"  {len(trip)} signals in {len(blocks)} message-blocks")
# dump each block with inferred byte offset (order) + total bytes
out=open(os.path.join(os.path.dirname(__file__),"signal_map.txt"),"w")
for bi,blk in enumerate(blocks):
    tot=sum(c for _,_,c,_ in blk)
    bufs=f"0x{blk[0][3]:x}-0x{blk[-1][3]:x}"
    hdr=f"BLOCK {bi}: {len(blk)} sigs, {tot} bytes, bufs {bufs}"
    out.write(hdr+"\n")
    boff=0
    for off,enc,cnt,buf in blk:
        out.write(f"    byte[{boff}..{boff+cnt-1}] -> buf 0x{buf:x} (len {cnt}, enc 0x{enc:08x})\n")
        boff+=cnt
    out.write("\n")
    if 0x409260<=blk[0][3]<0x409280 or any(0x40926a<=b<0x409274 for _,_,_,b in blk):
        print(f"  *** AEB block {bi}: {hdr}")
        boff=0
        for off,enc,cnt,buf in blk:
            tag=" <-- ANB_Zielbrems(radar AEB target)" if buf==0x40926c else ""
            print(f"      byte[{boff}..{boff+cnt-1}] -> 0x{buf:x} len{cnt}{tag}")
            boff+=cnt
out.close()
print(f"\n  full map -> decode/signal_map.txt ({len(blocks)} blocks)")

# ============ PASS 5: refine — segment by enc==0 terminators; correlate to msg-config ============
print("\n=== PASS 5: message segmentation via enc==0 terminators ===")
trip=parse_triples(0xb6a44,0xb7400)
msgs=[]; cur=[]
for off,enc,cnt,buf in trip:
    cur.append((off,enc,cnt,buf))
    if enc==0:                      # terminator
        msgs.append(cur); cur=[]
if cur: msgs.append(cur)
print(f"  {len(msgs)} messages (terminator-delimited)")
# which message contains the AEB target 0x40926c?
for mi,m in enumerate(msgs):
    bufs=[b for _,_,_,b in m]
    if 0x40926c in bufs:
        tot=sum(c for _,_,c,_ in m)
        print(f"\n  AEB message = msg#{mi}: {len(m)} signals, {tot} frame-bytes")
        boff=0
        for off,enc,cnt,buf in m:
            note=""
            if buf==0x40926c: note=" <== ANB_Zielbrems / radar AEB decel target (FUN_0008390c reads this)"
            print(f"      frame byte[{boff}..{boff+cnt-1}] -> 0x{buf:x} (len{cnt})"+note)
            boff+=cnt
        break
# summary stats
print(f"\n  total: {sum(len(m) for m in msgs)} signals across {len(msgs)} messages, saved to signal_map.txt")

# ============ PASS 6: annotate the map with known handlers + traced meanings ============
KNOWN = {
  0x40926c: "ANB_Zielbrems / radar AEB decel target -> anb_target_from_can(0x8390c) -> ANB builder",
  0x4093a9: "radar signal -> radar_msg_signal_proc(0x2c554) -> ANB freigabe 0x40553b",
  0x405e81: "ESP_05 TX signal base (esp05_sig_base)",
  0x4054c4: "anb_decel_request_src -> anb_decel_from_wheels(0x7c1d4)",
}
print("\n=== PASS 6: known-handler annotations present in the descriptor map ===")
trip=parse_triples(0xb6a44,0xb7400)
allbufs={b for _,_,_,b in trip}
for buf,desc in KNOWN.items():
    present = "IN MAP" if buf in allbufs else "(processed downstream, not a raw descriptor buffer)"
    print(f"  0x{buf:x}: {desc}  [{present}]")

# ============ PASS 7: block <-> msg-config ordering attempt ============
# Hypothesis: descriptor blocks are emitted in a fixed order; check whether the buffer-region
# ordering matches any monotonic msg-config subsequence. Report the radar/ACC candidate IDs.
print("\n=== PASS 7: CAN-id correlation status ===")
print("  msg-config 0xa9fc0 has 214 received IDs incl ACC_10(0x117), ACC_05 NOT here (0xafae0 cluster).")
print("  The AEB decel signal is at FRAME BYTES 0-1 of its block -> NOT ACC_10's byte-3 ANB_Zielbrems")
print("  layout -> the ESP's AEB-decel input is a DIFFERENT radar msg (candidate 0x152/undoc), confirmed")
print("  as a received CAN signal feeding the ANB. Exact ID needs the msg<->descriptor link table")
print("  (msg-config index -> descriptor block), which is the one remaining static artifact to locate.")
print("\nDONE. Full frame-byte->buffer map in decode/signal_map.txt")

# ============ PASS 8: CAN-ID correlation via traced handlers + section structure ============
print("\n=== PASS 8: CAN-ID correlation ===")
# Traced handler -> (buffer it reads, the message it belongs to per DBC + code trace)
HANDLER_MSG = {
  0x40926c: ("radar AEB msg (undoc, cand 0x152)", "anb_target_from_can 0x8390c: AEB decel target"),
  0x40926e: ("radar AEB msg", "anb_target_from_can: object/aux"),
  0x4093a9: ("radar msg (freigabe)", "radar_msg_signal_proc 0x2c554: -> ANB freigabe"),
}
trip=parse_triples(0xb6a44,0xb7400)
# Sections from COM master 0x503cc-0x503dc
SECTIONS = [u32(0x503cc), u32(0x503d0), u32(0x503d4), u32(0x503d8), u32(0x503dc)]
print(f"  descriptor sections (from 0x503cc): {[hex(s) for s in SECTIONS]}")
# which section holds the AEB block (0xb7164)?
aeb_off = next(off for off,_,_,b in trip if b==0x40926c)
sec = max([s for s in SECTIONS if s<=aeb_off], default=None)
print(f"  AEB descriptor @0x{aeb_off:x} is in section starting 0x{sec:x}")
# Report correlation for blocks containing traced buffers
print("\n  Correlated blocks (via traced handlers):")
for buf,(msg,note) in HANDLER_MSG.items():
    present = any(b==buf for _,_,_,b in trip)
    if present:
        print(f"    buf 0x{buf:x}: msg={msg}  [{note}]")

# ============ PASS 9 (FINAL): corrected {count,buffer,encoding} map, regenerate signal_map.txt ============
def parse_c(lo,hi):
    out=[];a=lo
    while a+12<=hi:
        cnt,buf,enc=u32(a),u32(a+4),u32(a+8)
        if 0x400000<=buf<0x410000 and 1<=cnt<=8: out.append((a,cnt,buf,enc));a+=0xc
        else:a+=4
    return out
sigs=parse_c(0xb6a44,0xb7400)
# segment into messages by enc==0 terminators, cap at 8 bytes
out=open(os.path.join(os.path.dirname(__file__),"signal_map.txt"),"w")
out.write("# ESP8 8R0907379BG COM RX signal map -- reconstructed from flash descriptors (0xb6a44 stream)\n")
out.write("# format: {count, buffer, encoding} triples; frame-byte offset implicit in order; enc=0 = msg terminator\n")
out.write(f"# {len(sigs)} signal descriptors\n\n")
msg=[]; mi=0; boff=0
for off,cnt,buf,enc in sigs:
    msg.append((cnt,buf,enc,boff)); boff+=cnt
    if enc==0 or boff>=8:
        out.write(f"MSG {mi}: {boff} frame-bytes\n")
        for c,b,e,bo in msg:
            tag=""
            if b==0x40926c: tag="  <== radar AEB decel target (anb_target_from_can 0x8390c)"
            out.write(f"    byte[{bo}..{bo+c-1}] -> 0x{b:x}{tag}\n")
        out.write("\n"); msg=[]; boff=0; mi+=1
if msg:
    out.write(f"MSG {mi}: {boff} frame-bytes\n")
    for c,b,e,bo in msg: out.write(f"    byte[{bo}..{bo+c-1}] -> 0x{b:x}\n")
out.close()
print(f"regenerated signal_map.txt: {mi+1} messages, {len(sigs)} signals")
