# TMAC tests

`tmac_model.py` is the bit-exact Python reference model. `test.py` drives the chip's pins through a
cocotb SPI master and compares every observable value with the model.

| test | what it proves |
|---|---|
| test_reset_state | status 0x81; weights, accumulators and flags are zero after reset |
| test_decoder_exhaustive | all 256 byte values: PACKING_FORMAT v1.0 decode, illegal 243–255 → zeros + sticky flag, CLEAR |
| test_random_matvec | random weights and activations (incl. −128/127), CMP vs CMP_CLR |
| test_streamed_matvec | LOAD_AC streaming: K-chunked matrix-vector product |
| test_signed_readback | negative / boundary results read back as two's-complement int16 |
| test_saturation | clamp at +32767 / −32768, sticky per-row SAT flags, accumulating back from the rails, CLEAR |
| test_bist | BIST via opcode and pin, signature = model, SPI writes ignored while busy |
| test_spi_abort_and_reset | a half-sent byte writes nothing; rst_n mid-frame restores the reset state |

Mutation check: see notes/03_rtl_and_verification.md.

## Running on Windows

```
cd test
mingw32-make                        # RTL
mingw32-make GATES=yes              # gate level: copy the hardened netlist to gate_level_netlist.v, set PDK_ROOT
python tmac_model.py --write-rtl    # regenerate the BIST signature in src/ after changing the model or BIST
```
