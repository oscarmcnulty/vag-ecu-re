# COM message directory — every message, its direction, and its descriptors

The complete `id → direction → descriptors` listing for the COM stack, derived from the two firmware
tables rather than from geometry or heuristics. `can_signal_map.md` documents the table formats and
the proofs; this file is the directory they produce.

Confidence: the whole listing is **[C]** — read out of the image. DBC names are a *join*, not
evidence: `vw_mlb.dbc` mixes B8/D4/C7 platform variants, so a blank name means "the DBC has no
message with that id", not "unknown message".

## Where direction comes from

Each COM message record carries, at `+0x2c`, the index of its **hardware message object**. The
corresponding MO configuration record — `0x8003e640 + (idx+1)*0x18` — holds the direction byte at
`+0x09`: **1 = TX, 2 = RX**. That is the controller's own configuration, so it is definitive: no
inference step, no DBC transmitter field, no writer heuristic. Layout in `can_signal_map.md`.

Of the 111 valid message records: **46 TX, 65 RX.** (The MO table configures more objects than the
COM stack uses — 52 TX / 74 RX on node 0 — the surplus being diagnostic and network-management
objects that do not go through the COM signal layer.)

## The writer map, and why it is a corroboration and not a test

A one-pass constant-propagation dump of every resolvable RAM store
(`core/ghidra/DumpAllWrites.java`, seeded `a0/a1/a8/a9` from `ecu.conf`, window
`0xd0000000..0xd0020000`) shows a genuinely useful structural fact:

> **RX buffers and TX staging buffers do not mix.** `FUN_8008b17c`
> (`COM_rx_default_substitution`, the RX timeout/default setter) writes 148 RAM addresses. Of the
> ~5900 other functions, exactly **one** (`FUN_80089b00`, one address) ever writes any of them. The
> high-volume marshallers `FUN_80316b2a` (217 addresses), `FUN_80313d20`, `FUN_803151fc`,
> `FUN_80316310`, `FUN_80312f70` have **zero** overlap with the RX set.

So "written by `COM_rx_default_substitution`" is a reliable positive marker for an RX target. The
converse is not: **being written by a marshaller does not make a message TX.** Checked against the MO
table, classifying by writer alone gets **105 of 129 groups right (81%)**, and the failures are
systematic:

- *Marshaller writes an RX target.* `0x106` ESP_05 is RX, but `FUN_80316b2a` writes its
  `ESP_BKV_Unterdruck` shadow `0xd0008dd2` — the engine re-publishes a received value. Same for
  `0x607`, `0x6a4`, `0x3ac`, `0x3b2`, `0x3af`, `0x6a3`, `0x3aa`, `0x124`.
- *No resolvable writer on a TX message.* Every CHECKSUM/COUNTER descriptor is filled by the COM
  stack through a descriptor pointer, so a message whose only descriptor in a group is its counter
  looks writer-less and gets guessed RX. That is what mislabelled the TSK counters
  (`0x800393c0` TSK_01, `0x800392d0` TSK_02, `0x800391e0` TSK_04, `0x800390a0` TSK_05) and eight
  other engine-TX messages.

Use the writer map for what it is good at — deciding *which application function produces a signal* —
and take direction from the MO table.

## Reproduce

```bash
python3 core/maps/decode_can_table.py ecus/med17/firmware/8R0907115N_0006.bin --csv /tmp/can_map.csv
# optional, for the writer map (read-only w.r.t. the Ghidra project, ~40 s):
source .env.sh
analyzeHeadless <proj> MED1711 -process 8R0907115N_0006.bin -noanalysis \
  -scriptPath core/ghidra -postScript DumpAllWrites.java 0xd0000000 0xd0020000 allwrites.csv true
```

## The listing

`record` = COM message record (`0x30` stride from `0x80030c38`). `MO cfg #` = the `+0x2c` index into
the MO configuration table. `DBC geom` = how many of the record's bindings hit an exact
`start_bit|bit_len` match in `vw_mlb.dbc`; blank where the DBC has no such id. Descriptor columns
give the address span of the record's own descriptors — for the two duplicated ids (`0x092`,
`0x560`) the span covers both records.

| CAN id | DBC name | dir | record | MO cfg # | n_bool | n_sig | signal descriptors | boolean descriptors | DBC geom |
|---|---|---|---|---:|---:|---:|---|---|---|
| `0x040` | Airbag_01 | **RX** | `0x80031628` | 65 | 6 | 4 | `0x80038970-0x800389e8` | `0x8003493c-0x800349a0` | 9/10 |
| `0x051` | - | **RX** | `0x80032048` | 119 | 0 | 1 | `0x80035e00` | - | - |
| `0x07f` | - | **RX** | `0x80030ff8` | 32 | 7 | 7 | `0x8003a4a0-0x8003a590` | `0x800354b8-0x80035530` | - |
| `0x080` | Motor_01 | **TX** | `0x80030c68` | 13 | 2 | 7 | `0x8003b6c0-0x8003b7b0` | `0x80035c10-0x80035c24` | 9/9 |
| `0x081` | Motor_02 | **TX** | `0x80030c98` | 14 | 5 | 9 | `0x8003b558-0x8003b698` | `0x80035bac-0x80035bfc` | 14/14 |
| `0x082` | Getriebe_01 | **RX** | `0x80031148` | 39 | 3 | 6 | `0x80039e88-0x80039f50` | `0x80035210-0x80035238` | 9/9 |
| `0x083` | Getriebe_02 | **RX** | `0x80031178` | 40 | 3 | 9 | `0x80039d20-0x80039e60` | `0x800351d4-0x800351fc` | 12/12 |
| `0x085` | SCU_01 | **RX** | `0x80031388` | 51 | 1 | 3 | `0x80039528-0x80039578` | `0x80034c34` | 4/4 |
| `0x086` | LWI_01 | **RX** | `0x800313b8` | 52 | 4 | 4 | `0x80039488-0x80039500` | `0x80034be4-0x80034c20` | 8/8 |
| `0x087` | - | **TX** | `0x80030d28` | 17 | 3 | 4 | `0x8003b210-0x8003b288` | `0x80035968-0x80035990` | - |
| `0x090` | - | **TX** | `0x800320a8` | 121 | 0 | 2 | `0x80035d60-0x80035d88` | - | - |
| `0x091` | - | **TX** | `0x80030e18` | 22 | 0 | 9 | `0x8003ad88-0x8003aec8` | - | - |
| `0x092` | - | **TX** | `0x80030e48` | 23 | 0 | 7 | `0x80035d10-0x8003ad60` | - | - |
| `0x092` | - | **TX** | `0x800320d8` | 122 | 0 | 2 | `0x80035d10-0x8003ad60` | - | - |
| `0x096` | - | **TX** | `0x80030e78` | 24 | 1 | 6 | `0x8003ab80-0x8003ac48` | `0x8003588c` | - |
| `0x097` | - | **RX** | `0x80030f38` | 28 | 15 | 6 | `0x8003a838-0x8003a900` | `0x800356e8-0x80035800` | - |
| `0x098` | - | **RX** | `0x800310b8` | 36 | 1 | 6 | `0x8003a180-0x8003a248` | `0x800353a0` | - |
| `0x099` | - | **RX** | `0x80031118` | 38 | 8 | 7 | `0x80039f78-0x8003a068` | `0x8003524c-0x800352d8` | - |
| `0x09c` | - | **RX** | `0x80031028` | 33 | 5 | 5 | `0x8003a3d8-0x8003a478` | `0x80035454-0x800354a4` | - |
| `0x09d` | - | **TX** | `0x80030d88` | 19 | 2 | 9 | `0x8003afe0-0x8003b120` | `0x8003592c-0x80035940` | - |
| `0x09e` | - | **RX** | `0x80031208` | 43 | 9 | 7 | `0x800399d8-0x80039ac8` | `0x800350bc-0x8003515c` | - |
| `0x0a3` | - | **TX** | `0x80030ea8` | 25 | 1 | 7 | `0x8003aa68-0x8003ab58` | `0x80035878` | - |
| `0x0a4` | - | **TX** | `0x80030ed8` | 26 | 3 | 5 | `0x8003a9a0-0x8003aa40` | `0x8003583c-0x80035864` | - |
| `0x0a5` | - | **RX** | `0x80031238` | 44 | 8 | 8 | `0x80039898-0x800399b0` | `0x8003501c-0x800350a8` | - |
| `0x0a6` | - | **RX** | `0x80031268` | 45 | 4 | 6 | `0x800397a8-0x80039870` | `0x80034fcc-0x80035008` | - |
| `0x0a8` | - | **TX** | `0x80030d58` | 18 | 1 | 5 | `0x8003b148-0x8003b1e8` | `0x80035954` | - |
| `0x0a9` | - | **RX** | `0x80030fc8` | 31 | 4 | 5 | `0x8003a5b8-0x8003a658` | `0x80035544-0x80035580` | - |
| `0x100` | **ESP_01** | **RX** | `0x80030f68` | 29 | 13 | 5 | `0x8003a770-0x8003a810` | `0x800355e4-0x800356d4` | 18/18 |
| `0x101` | ESP_02 | **RX** | `0x800316e8` | 69 | 3 | 4 | `0x80038678-0x800386f0` | `0x80034860-0x80034888` | 7/7 |
| `0x102` | Getriebe_03 | **RX** | `0x800311a8` | 41 | 2 | 8 | `0x80039be0-0x80039cf8` | `0x800351ac-0x800351c0` | 10/10 |
| `0x103` | ESP_03 | **RX** | `0x80030f98` | 30 | 4 | 6 | `0x8003a680-0x8003a748` | `0x80035594-0x800355d0` | 10/10 |
| `0x104` | EPB_01 | **RX** | `0x80031808` | 75 | 6 | 6 | `0x80038150-0x80038218` | `0x800345a4-0x80034608` | 10/12 |
| `0x105` | Motor_03 | **TX** | `0x80030cc8` | 15 | 14 | 6 | `0x8003b468-0x8003b530` | `0x80035a94-0x80035b98` | 20/20 |
| `0x106` | **ESP_05** | **RX** | `0x80031718` | 70 | 19 | 6 | `0x80038588-0x80038650` | `0x800346e4-0x8003484c` | 25/25 |
| `0x107` | Motor_04 | **TX** | `0x800314a8` | 57 | 2 | 2 | `0x80039028-0x80039050` | `0x80034aa4-0x80034ab8` | 4/4 |
| `0x109` | **ACC_01** | **RX** | `0x800315c8` | 63 | 2 | 9 | `0x80038ad8-0x80038c18` | `0x80034a04-0x80034a18` | 11/11 |
| `0x10a` | **TSK_01** | **TX** | `0x800313e8` | 53 | 1 | 6 | `0x80039398-0x80039460` | `0x80034bd0` | 4/7 |
| `0x10b` | LS_01 | **RX** | `0x80031298` | 46 | 11 | 3 | `0x80039730-0x80039780` | `0x80034ef0-0x80034fb8` | 14/14 |
| `0x10c` | **TSK_02** | **TX** | `0x80031418` | 54 | 6 | 6 | `0x800392a8-0x80039370` | `0x80034b58-0x80034bbc` | 7/12 |
| `0x10d` | **ACC_05** | **RX** | `0x800315f8` | 64 | 4 | 5 | `0x80038a10-0x80038ab0` | `0x800349b4-0x800349f0` | 9/9 |
| `0x10e` | **TSK_04** | **TX** | `0x80031448` | 55 | 2 | 6 | `0x800391b8-0x80039280` | `0x80034b30-0x80034b44` | 8/8 |
| `0x111` | **TSK_05** | **TX** | `0x80031478` | 56 | 5 | 8 | `0x80039078-0x80039190` | `0x80034acc-0x80034b1c` | 13/13 |
| `0x114` | Motor_10 | **TX** | `0x800314d8` | 58 | 4 | 8 | `0x80038ee8-0x80039000` | `0x80034a54-0x80034a90` | 10/12 |
| `0x115` | - | **RX** | `0x80030f08` | 27 | 2 | 3 | `0x8003a928-0x8003a978` | `0x80035814-0x80035828` | - |
| `0x11d` | LH_EPS_02 | **RX** | `0x800318c8` | 79 | 0 | 2 | `0x80037ed0-0x80037ef8` | - | 0/2 |
| `0x123` | - | **TX** | `0x80031598` | 62 | 0 | 3 | `0x80038c40-0x80038c90` | - | - |
| `0x124` | - | **RX** | `0x800316b8` | 68 | 1 | 7 | `0x80038718-0x80038808` | `0x8003489c` | - |
| `0x131` | - | **TX** | `0x80031538` | 60 | 1 | 4 | `0x80038dd0-0x80038e48` | `0x80034a2c` | - |
| `0x309` | BEM_01 | **RX** | `0x80031088` | 35 | 1 | 6 | `0x8003a270-0x8003a338` | `0x800353b4` | 7/7 |
| `0x30b` | Kombi_01 | **RX** | `0x80031058` | 34 | 7 | 3 | `0x8003a360-0x8003a3b0` | `0x800353c8-0x80035440` | 8/10 |
| `0x30e` | Motor_05 | **TX** | `0x80030cf8` | 16 | 12 | 11 | `0x8003b2b0-0x8003b440` | `0x800359a4-0x80035a80` | 23/23 |
| `0x312` | TSK_03 | **TX** | `0x80030c38` | 12 | 0 | 6 | `0x8003b7d8-0x8003b8a0` | - | 6/6 |
| `0x319` | - | **RX** | `0x80031688` | 67 | 1 | 2 | `0x80038830-0x80038858` | `0x800348b0` | - |
| `0x32b` | - | **TX** | `0x80030db8` | 20 | 1 | 2 | `0x8003af90-0x8003afb8` | `0x80035918` | - |
| `0x385` | Charisma_01 | **RX** | `0x80031328` | 49 | 0 | 4 | `0x800395a0-0x80039618` | - | 4/4 |
| `0x38a` | - | **RX** | `0x80031358` | 50 | 4 | 0 | - | `0x80034c48-0x80034c84` | - |
| `0x391` | OBD_01 | **TX** | `0x800319e8` | 85 | 5 | 5 | `0x80037868-0x80037908` | `0x800340cc-0x8003411c` | 10/10 |
| `0x392` | ESP_07_FR | **RX** | `0x80031748` | 71 | 3 | 6 | `0x80038498-0x80038560` | `0x800346a8-0x800346d0` | 8/9 |
| `0x39c` | Gateway_05 | **RX** | `0x800312c8` | 47 | 22 | 6 | `0x80039640-0x80039708` | `0x80034d38-0x80034edc` | 28/28 |
| `0x3a1` | PSD_01 | **RX** | `0x80031868` | 77 | 5 | 12 | `0x80037f20-0x800380d8` | `0x8003452c-0x8003457c` | 17/17 |
| `0x3a2` | PSD_02 | **RX** | `0x80031898` | 78 | 0 | 0 | - | - | 0/0 |
| `0x3a4` | - | **RX** | `0x80031778` | 72 | 4 | 10 | `0x80038308-0x80038470` | `0x80034658-0x80034694` | - |
| `0x3a5` | - | **TX** | `0x80031988` | 83 | 3 | 5 | `0x80037ac0-0x80037b60` | `0x800341a8-0x800341d0` | - |
| `0x3a6` | - | **TX** | `0x80030de8` | 21 | 6 | 4 | `0x8003aef0-0x8003af68` | `0x800358a0-0x80035904` | - |
| `0x3a7` | - | **TX** | `0x80031a78` | 88 | 0 | 8 | `0x80037598-0x800376b0` | - | - |
| `0x3a8` | - | **TX** | `0x80032078` | 120 | 0 | 2 | `0x80035db0-0x80035dd8` | - | - |
| `0x3aa` | - | **RX** | `0x80031ce8` | 101 | 0 | 8 | `0x80036800-0x80036918` | - | - |
| `0x3ab` | - | **RX** | `0x800310e8` | 37 | 9 | 6 | `0x8003a090-0x8003a158` | `0x800352ec-0x8003538c` | - |
| `0x3ac` | - | **RX** | `0x80031e38` | 108 | 0 | 7 | `0x80036328-0x80036418` | - | - |
| `0x3af` | - | **RX** | `0x80031d78` | 104 | 5 | 7 | `0x800364b8-0x800365a8` | `0x80033f28-0x80033f78` | - |
| `0x3b2` | BEM_03 | **RX** | `0x80031dd8` | 106 | 1 | 1 | `0x80036490` | `0x80033f00` | 2/2 |
| `0x3bf` | Klima_01 | **RX** | `0x80031658` | 66 | 6 | 6 | `0x80038880-0x80038948` | `0x800348c4-0x80034928` | 12/12 |
| `0x3c0` | Klemmen_Status_01 | **RX** | `0x80031e08` | 107 | 2 | 2 | `0x80036440-0x80036468` | `0x80033ed8-0x80033eec` | 4/4 |
| `0x440` | Motor_06 | **TX** | `0x800318f8` | 80 | 32 | 7 | `0x80037db8-0x80037ea8` | `0x800342ac-0x80034518` | 37/39 |
| `0x441` | Getriebe_04 | **RX** | `0x800311d8` | 42 | 3 | 6 | `0x80039af0-0x80039bb8` | `0x80035170-0x80035198` | 9/9 |
| `0x471` | Licht_hinten_01 | **RX** | `0x80031f28` | 113 | 4 | 1 | `0x80036030` | `0x80033dac-0x80033de8` | 5/5 |
| `0x494` | STS_01 | **RX** | `0x80031838` | 76 | 1 | 2 | `0x80038100-0x80038128` | `0x80034590` | 3/3 |
| `0x520` | Airbag_02 | **RX** | `0x80031c58` | 98 | 0 | 1 | `0x80036a80` | - | 1/1 |
| `0x521` | STH_01 | **RX** | `0x80031ef8` | 112 | 7 | 2 | `0x80036058-0x80036080` | `0x80033dfc-0x80033e74` | 9/9 |
| `0x560` | - | **TX** | `0x80031568` | 61 | 0 | 7 | `0x800376d8-0x80038da8` | - | - |
| `0x560` | - | **TX** | `0x80031a48` | 87 | 0 | 4 | `0x800376d8-0x80038da8` | - | - |
| `0x562` | - | **TX** | `0x80031aa8` | 89 | 0 | 4 | `0x800374f8-0x80037570` | - | - |
| `0x564` | - | **TX** | `0x80031ad8` | 90 | 0 | 6 | `0x80037408-0x800374d0` | - | - |
| `0x585` | Systeminfo_01 | **RX** | `0x80031fb8` | 116 | 2 | 1 | `0x80035fb8` | `0x80033d48-0x80033d5c` | 2/3 |
| `0x590` | Kessy_02 | **RX** | `0x80031f88` | 115 | 0 | 1 | `0x80035fe0` | - | 1/1 |
| `0x5bd` | - | **RX** | `0x80031fe8` | 117 | 0 | 2 | `0x80035f68-0x80035f90` | - | - |
| `0x600` | - | **TX** | `0x80031b38` | 92 | 0 | 7 | `0x80037110-0x80037200` | - | - |
| `0x601` | - | **TX** | `0x80031b68` | 93 | 0 | 6 | `0x80037020-0x800370e8` | - | - |
| `0x602` | - | **TX** | `0x80031b98` | 94 | 0 | 8 | `0x80036ee0-0x80036ff8` | - | - |
| `0x603` | - | **TX** | `0x80031bc8` | 95 | 0 | 5 | `0x80036e18-0x80036eb8` | - | - |
| `0x604` | - | **TX** | `0x80031bf8` | 96 | 5 | 13 | `0x80036c10-0x80036df0` | `0x80034068-0x800340b8` | - |
| `0x605` | - | **TX** | `0x80031c28` | 97 | 0 | 9 | `0x80036aa8-0x80036be8` | - | - |
| `0x607` | - | **RX** | `0x80031e98` | 110 | 0 | 3 | `0x800361c0-0x80036210` | - | - |
| `0x640` | Motor_07 | **TX** | `0x80031928` | 81 | 9 | 9 | `0x80037c50-0x80037d90` | `0x800341f8-0x80034298` | 18/18 |
| `0x641` | Motor_Code_01 | **TX** | `0x800319b8` | 84 | 6 | 10 | `0x80037930-0x80037a98` | `0x80034130-0x80034194` | 13/16 |
| `0x642` | WIV_01 | **TX** | `0x80031a18` | 86 | 0 | 6 | `0x80037778-0x80037840` | - | 6/6 |
| `0x643` | Einheiten_01 | **RX** | `0x80031da8` | 105 | 1 | 0 | - | `0x80033f14` | 1/1 |
| `0x644` | Gateway_11 | **RX** | `0x800312f8` | 48 | 8 | 0 | - | `0x80034c98-0x80034d24` | 8/8 |
| `0x647` | Motor_09 | **TX** | `0x80031958` | 82 | 1 | 5 | `0x80037b88-0x80037c28` | `0x800341e4` | 6/6 |
| `0x659` | - | **RX** | `0x80031c88` | 99 | 0 | 1 | `0x80036a58` | - | - |
| `0x65e` | OBD_Tankgeber_01 | **RX** | `0x80032018` | 118 | 0 | 8 | `0x80035e28-0x80035f40` | - | 8/8 |
| `0x661` | Anhaenger_01 | **RX** | `0x80031f58` | 114 | 3 | 1 | `0x80036008` | `0x80033d70-0x80033d98` | 4/4 |
| `0x670` | Motor_18 | **TX** | `0x80031508` | 59 | 1 | 3 | `0x80038e70-0x80038ec0` | `0x80034a40` | 3/4 |
| `0x6a2` | - | **TX** | `0x80031b08` | 91 | 0 | 12 | `0x80037228-0x800373e0` | - | - |
| `0x6a3` | - | **RX** | `0x80031d18` | 102 | 5 | 7 | `0x800366e8-0x800367d8` | `0x80033f8c-0x80033fdc` | - |
| `0x6a4` | - | **RX** | `0x80031e68` | 109 | 4 | 6 | `0x80036238-0x80036300` | `0x80033e88-0x80033ec4` | - |
| `0x6b2` | Diagnose_01 | **RX** | `0x80031ec8` | 111 | 0 | 7 | `0x800360a8-0x80036198` | - | 7/7 |
| `0x6b3` | - | **RX** | `0x80031d48` | 103 | 0 | 7 | `0x800365d0-0x800366c0` | - | - |
| `0x6b7` | Kombi_02 | **RX** | `0x800317a8` | 73 | 3 | 4 | `0x80038268-0x800382e0` | `0x8003461c-0x80034644` | 6/7 |
| `0x6b8` | Kombi_03 | **RX** | `0x800317d8` | 74 | 0 | 1 | `0x80038240` | - | 1/1 |
| `0x6c0` | NMH_Gateway | **RX** | `0x80032138` | 124 | 0 | 0 | - | - | 0/0 |

## Notes on the edges

- **Three descriptors belong to no message record**: `0x80035c48`, `0x80036940` and `0x8003b8c8`.
  The last is the tail of the `0x28`-stride array and decodes as `112|105`, i.e. it is not a
  descriptor at all — array terminator or neighbouring structure.
- Two descriptors inside the `0x092` span carry "RAM" targets in flash (`0x8002793c`,
  `0x800278fc`) — signals bound to ROM constants.
- `0x3a2` (PSD_02), `0x6c0` (NMH_Gateway) and one variant-disabled record have a message record but
  no signal or boolean descriptors: the message is configured on the controller and monitored, but
  no signal is unpacked from it.
- Booleans and multi-bit signals never collide on the same frame bits in this decode. Under the old
  off-by-one boolean binding they collided systematically — that mismatch is what exposed the error.

## Where TSK_01 frame bit 23 comes from

Bit 23 is bit 7 of `0xd0005e34` (descriptor `0x80039460`, `16|24`, `TSK_Status_AB`). Its full
producer chain — and the reason it moves with vehicle speed — is the ECD relay: see
**`ecd_relay.md`**. Do not re-derive it here.
