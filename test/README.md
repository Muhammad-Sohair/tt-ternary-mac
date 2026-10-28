# TMAC tests

`tmac_model.py` is the bit-exact Python reference model. `test.py` drives the chip's pins through a
cocotb SPI master and compares every observable value with the model.

| test | what it proves |
|---|---|
| test_reset_state | status 0x81; weights, accumulators and flags are zero after reset |
| test_decoder_exhaustive | all 256 byte values: PACKING_FORMAT v1.0 decode, illegal 243–255 → zeros + sticky flag, CLEAR |
| test_random_matvec | random weights and activations (incl. −128/127), CMP vs CMP_CLR, random shifts 0–31 |
| test_streamed_matvec | LOAD_AC streaming: K-chunked matrix-vector product |
| test_shift_floor_semantics | readout uses floor division: −1 >>> 1 = −1, −3 >>> 1 = −2 |
| test_readout_saturation | int16 clamp on READ_ACC, RSAT status bit, READ_RAW still exact |
| test_internal_saturation | 24-bit clamp and sticky SAT flags (RTL only: ~6,600 transactions) |
| test_bist | BIST via opcode and pin, signature = model, SPI writes ignored while busy |
| test_spi_abort_and_reset | a half-sent byte writes nothing; rst_n mid-frame restores the reset state |

Mutation check (6 injected bugs, all caught): ±1 code swap in the decoder (2 tests), logical instead of
arithmetic shift, missing +1 carry-ins of negated terms, wrapping instead of saturating, LOAD_AC not
computing.

`test_devkit.py` runs the board script `devkit/tmac_bringup.py` against the RTL: its own `run_all()` in a cocotb
bridge thread, with a fake `tt` object that has the firmware API the script uses. S1–S7 run in full (S4 all 256
bytes, S5 200 trials); S8, the BIST clock sweep, is stubbed because it measures silicon, not RTL. Not in the
default run (about 5 min): `mingw32-make COCOTB_TEST_MODULES=test_devkit`.

## Running on Windows

```
cd test
mingw32-make                        # RTL
mingw32-make GATES=yes              # gate level: copy the hardened netlist to gate_level_netlist.v, set PDK_ROOT
python tmac_model.py --write-rtl    # regenerate the BIST signature in src/ after changing the model or BIST
```
