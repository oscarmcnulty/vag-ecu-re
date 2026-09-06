# .data known-plaintext alignment attack — RESULT: NO .data image exists (attack N/A)

Goal: pin the `.data` flash load-image (LMA/VMA/size) by aligning known init-value anchors, so the
object table `*0x4069b4` materializes and EPB (handle 0x25b) buffer can be read.

## VERDICT: refuted — there is no copied `.data` image to align against.

Evidence:
1. **Config-table addresses appear ONLY in code literals, never in a flash data blob.** The known
   init values `0xb6a44` (com_sig_group_table) and `0xb6ffc` (com_pdu_descriptor) occur as flash u32
   words only at code literal-pool slots (`0x50110`, `0x95544`, `0x95548`, `0x6e68`, `0x503d4`, …),
   all `< 0xa2000`. `0xbda34` (bump limit) likewise only in code pools. So these tables are `.rodata`
   accessed by **direct flash address**, not values copied into RAM `.data`.
2. **No control-block `.data` image in flash.** Scanning the whole data region for flash words
   pointing into `0x406000-0x407000` (what a copied control block would contain) returns only the
   `.rodata` COM signal/PDU config (records with the `0x01000000` marker + `sig_id` fields pointing at
   `.bss` buffers in `0x406xxx`), i.e. config that *references* `.bss`, not an image of the control
   block itself.
3. **The object table is runtime-built.** Every accessor (`FUN_0006b936`, `FUN_0008dac0`
   `while(i< *cnt){ flags = objbase[i*0x10+0xf]; ... }`, `FUN_0009db84`, `FUN_0009e3f4`,
   `FUN_00089194/891b8`) reads `*0x4069b4` as an **already-set base** and indexes it (stride 0x10,
   `+6`=sigcount, `+8`=descriptor-array ptr, `+0xf` bit5=valid / bit6=ready). None writes the base.
   `FUN_0009e3f4` even allocates a handle (`FUN_000a29dc(8)`=byteswap) and copies fields OUT of the
   object table — confirming it pre-exists. So `*0x4069b4` is populated by an init that builds the
   table in RAM from the `.rodata` config; there is no straight flash→RAM `.data` copy for it.

## Implication
The known-plaintext alignment premise (a contiguous `.data` LMA→VMA blob) does not hold for this
image. The correct target is the **object-table BUILDER** — the init code that writes `*0x4069b4` and
populates the table from the `.rodata` COM config (root near the `0x50xxx`/`0x89xxx` COM-init tree).
Address-exact xref does not catch the base write (done through a base register), so it needs a
data-flow / decompile sweep of the COM-init entry, or the SVC-modeled boot emulation to let init run.

## Confirmed facts (proven)
- Object table: base `*0x4069b4`, msg count `*0x4069fc`, bump ptr `*0x4069b0`; stride 0x10 records
  `{+6 sigcount, +8 descr-array ptr (RAM), +0xf flags bit5=valid bit6=ready}`. Runtime-built.
- `0xb6a44`/`0xb6ffc`/`0xbda34` are `.rodata`, direct-addressed (code pools only).
