# Simos 18 — placeholder pack

Not yet started. When you add Simos18 (18.1 / 18.10, Continental on TC1791/93,
TriCore — same `core/` Ghidra pipeline applies), the key difference vs Simos8.5 is
the **flash/security layer**, which is already solved publicly:

- **bri3d/VW_Flash** — flashing over UDS, ECM3/CBOOT checksum correction, and
  AES-encrypted flashware handling. **Vendor this** rather than reimplementing.
- **bri3d SBOOT exploit** — unsigned-flash bootloader unlock (background).
- **simos-hsl** — high-speed RAM logger.

So a Simos18 pack mostly = `core/` (disasm/decompile/annotate/map) + VW_Flash
(container/flash/checksum). Expect to *consume* community tooling here, unlike the
comparatively novel Simos8.5 work.

TODO when starting:
- [ ] Add `firmware/` (decrypt blocks via VW_Flash first)
- [ ] Confirm Ghidra language/base for the specific 18.x variant
- [ ] Link VW_Flash as the flash/checksum backend
