## How it works

An 8-bit register `count` drives `uo_out`. On each rising clock edge:
`rst_n` low clears it to 0; else `LOAD` (ui[1]) copies `uio_in` into it; else `EN` (ui[0]) increments it (wrapping 255 to 0).
LOAD has priority over EN.

## How to test

Hold `rst_n` low for a few clocks, then release. Set `EN` high: `uo_out` counts up once per clock.
Put a value on `uio_in`, pulse `LOAD` for one clock: `uo_out` shows that value.

## External hardware

None. LEDs on `uo_out` help at slow clock rates.
