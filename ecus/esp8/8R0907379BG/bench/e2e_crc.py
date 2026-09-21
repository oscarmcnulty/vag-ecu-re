#!/usr/bin/env python3
"""ESP8 (8R0907379BG) E2E CRC computation (reversed from FUN_0003d780 + FUN_0005f43a).

Two schemes (both CRC-8, init 0xFF, xorout 0xFF, MSB-first table lookup crc=table[byte^crc]):
  crc8_j1850(data)              - app messages (0x060 etc.); VERIFIED vs live 0x060. (FUN_0003d780)
  e2e_crc8_dataid(buf, data_id) - AUTOSAR E2E P01 style with data-id fold, byte0=CRC. (FUN_0005f43a)
     crc over buf[1:], then fold data_id at end. Table poly J1850(0x1D) or H2F(0x2F) - try both.
"""
def _tab(poly):
    t=[]
    for i in range(256):
        c=i
        for _ in range(8): c=((c<<1)^poly)&0xFF if c&0x80 else (c<<1)&0xFF
        t.append(c)
    return t
J1850=_tab(0x1D); H2F=_tab(0x2F)

def crc8_j1850(data):
    crc=0xFF
    for b in data: crc=J1850[b^crc]
    return crc^0xFF

def e2e_crc8_dataid(buf, data_id, poly='j1850'):
    """buf includes the byte0 CRC slot (ignored). CRC over buf[1:] then fold data_id."""
    t=J1850 if poly=='j1850' else H2F
    crc=0xFF
    for b in buf[1:]: crc=t[b^crc]
    return t[data_id^crc]^0xFF

if __name__=="__main__":
    # self-test vs live 0x060 ctr=6 -> 0x1e
    print("0x060 ctr=6:", hex(crc8_j1850(bytes([0,0,0,0,0,0x08,0x06]))), "(expect 0x1e)")
    b=bytes([0x00,0x07,0x00,0x06,0x00,0x5f,0x20,0x00])
    print("container 0x600 dataid=0x12 j1850:", hex(e2e_crc8_dataid(b,0x12,'j1850')),
          "h2f:", hex(e2e_crc8_dataid(b,0x12,'h2f')))
