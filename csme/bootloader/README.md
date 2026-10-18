# Bootloader and memory map

The C files here implement the first native platform scaffold: ROM, SRAM,
DRAM, a read-only SPI window, fake PCH controls, clocks, reset, MEI status,
and a deterministic startup state machine.

The default path reaches `auth-pending` and then `rejected`. That is an
explicit model boundary, not a claim that the real CSME firmware has booted.
