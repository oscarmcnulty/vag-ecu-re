# openpilot integration

The EPB dynamic-brake relay panda code (previously here as `panda/*.patch` +
`epb_relay.h`) now lives as real source on the forks, not as a patch set:

- **panda**: `oscarmcnulty/panda` branch `vw-epb-relay` (base `f849893b`, last commit
  supporting the black panda). Files: `board/drivers/epb_relay.h`, `board/main.c`,
  `board/drivers/bxcan.h`. F4-only (`#ifndef STM32H7`).
- **opendbc**: `oscarmcnulty/opendbc` branch `vw-epb-relay` (base `45bf6c8f`). The
  `SAFETY_VW_EPB_RELAY` safety-hooks (`opendbc/safety/`), required for the panda fork
  to build.

Build/flash recipe and on-car wiring are in agent memory (`black-panda-firmware`,
`comma3x-onroad-flicker-ign-backfeed`).
