# SPDX-License-Identifier: Apache-2.0
"""cocotb tests for TMAC. Every check is bit-exact against tmac_model.TMAC.

The SPI master below drives the pins the way the devkit's RP2040 will:
mode 0, MSB first, SCK half-period = HALF clk cycles (f_SCK = f_clk / 16),
sampling MISO just before each rising edge.

GATES=yes runs the same tests on the hardened netlist.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

from tmac_model import ACC_MAX, ACC_MIN, COLS, ROWS, TMAC, bist_expected, decode, pack_matrix

HALF = 8                                   # clk cycles per SCK phase
GL = os.environ.get("GATES") == "yes"

OP_STATUS, OP_LOAD_W, OP_LOAD_A, OP_LOAD_AC = 0x00, 0x10, 0x20, 0x21
OP_CMP, OP_CMP_CLR, OP_READ_A = 0x30, 0x31, 0x40
OP_READ_W, OP_BIST, OP_READ_S, OP_CLEAR = 0x50, 0x60, 0x61, 0x70

UO_MISO, UO_DONE, UO_PASS, UO_ILL, UO_SAT, UO_BUSY, UO_ACT = 0, 2, 3, 4, 5, 6, 7


# ---------------- pin-level helpers ----------------
_ui = {}


def set_ui(dut, sck=None, csn=None, mosi=None, bist=None):
    # Keep a Python shadow of ui_in. Reading dut.ui_in.value back is wrong here:
    # cocotb applies writes at the end of the timestep, so two set_ui() calls in
    # the same timestep would read the same stale value and the second would
    # undo the first (this kept SCK stuck high in the first version).
    v = _ui.get("v", 0)
    for bit, val in ((0, sck), (1, csn), (2, mosi), (3, bist)):
        if val is not None:
            v = (v & ~(1 << bit)) | (val << bit)
    _ui["v"] = v
    dut.ui_in.value = v


def uo_bit(dut, bit):
    return (int(dut.uo_out.value) >> bit) & 1


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())   # 50 MHz
    dut.ena.value = 1
    dut.uio_in.value = 0
    _ui["v"] = 0b0010
    dut.ui_in.value = 0b0010                                   # CS_n high, SCK low
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)


async def xfer(dut, tx, nread=0):
    """One CS_n-framed transaction. Sends tx (+ nread zero bytes); returns all MISO bytes."""
    out = list(tx) + [0] * nread
    rx = []
    set_ui(dut, csn=0)
    await ClockCycles(dut.clk, HALF, rising=False)
    for byte in out:
        got = 0
        for i in range(7, -1, -1):
            set_ui(dut, mosi=(byte >> i) & 1)
            await ClockCycles(dut.clk, HALF, rising=False)
            got = (got << 1) | uo_bit(dut, UO_MISO)                # sample just before the rise
            set_ui(dut, sck=1)
            await ClockCycles(dut.clk, HALF, rising=False)
            set_ui(dut, sck=0)
        rx.append(got)
    await ClockCycles(dut.clk, HALF, rising=False)
    set_ui(dut, csn=1, mosi=0)
    await ClockCycles(dut.clk, HALF, rising=False)
    return rx


async def read_status(dut):
    return (await xfer(dut, [OP_STATUS], 2))


async def read_acc16(dut):
    rx = await xfer(dut, [OP_READ_A], 2 * ROWS)
    vals = []
    for r in range(ROWS):
        v = rx[1 + 2 * r] << 8 | rx[2 + 2 * r]
        vals.append(v - 65536 if v & 0x8000 else v)
    return vals


async def read_codes(dut):
    n = (ROWS * COLS + 3) // 4
    return (await xfer(dut, [OP_READ_W], n))[1:]


async def check_all(dut, m, tag=""):
    """Compare every observable register with the model."""
    acc = await read_acc16(dut)
    assert acc == m.acc, f"{tag}: acc {acc} != model {m.acc}"
    sat_b, status = (await read_status(dut))[1:]
    assert sat_b == m.sat_byte(), f"{tag}: sat flags 0x{sat_b:02x} != 0x{m.sat_byte():02x}"
    assert status == m.status(), f"{tag}: status 0x{status:02x} != 0x{m.status():02x}"


def rand_weights(rng, p_zero=1 / 3):
    return [[0 if rng.random() < p_zero else rng.choice((-1, 1)) for _ in range(COLS)] for _ in range(ROWS)]


# ---------------- tests ----------------
@cocotb.test()
async def test_reset_state(dut):
    """After reset: status 0x81, accumulators/weights zero, BIST pins low."""
    await start(dut)
    m = TMAC()
    rx = await xfer(dut, [OP_STATUS], 2)
    assert rx[0] == 0x81, f"status during opcode byte: 0x{rx[0]:02x}"
    assert await read_codes(dut) == m.weight_codes()
    await check_all(dut, m, "reset")
    for b in (UO_DONE, UO_PASS, UO_ILL, UO_SAT, UO_BUSY):
        assert uo_bit(dut, b) == 0, f"uo[{b}] not 0 after reset"


@cocotb.test()
async def test_decoder_exhaustive(dut):
    """All 256 byte values through the decoder: legal bytes decode per PACKING_FORMAT,
    243..255 decode to zero and raise the sticky ILLEGAL flag (pin and status)."""
    await start(dut)
    for b in range(256):
        await xfer(dut, [OP_LOAD_W, b])                         # lands in weight byte 0 = row 0, cols 0..4
        codes = (await xfer(dut, [OP_READ_W], 2))[1:]
        ws, bad = decode(b)
        exp = 0
        for k, w in enumerate(ws):
            exp |= {-1: 3, 0: 0, 1: 1}[w] << (2 * k)
        assert (codes[0] | codes[1] << 8) & 0x3FF == exp, f"byte {b}: codes 0x{codes[1]:02x}{codes[0]:02x} want 0x{exp:03x}"
        status = (await read_status(dut))[2]
        assert bool(status & 0x08) == bad and uo_bit(dut, UO_ILL) == int(bad), f"byte {b}: ILLEGAL flag wrong"
        if bad:
            await xfer(dut, [OP_CLEAR])
            assert uo_bit(dut, UO_ILL) == 0, "CLEAR did not clear ILLEGAL"


@cocotb.test()
async def test_random_matvec(dut):
    """Random weights/activations (incl. -128/127 edges), CMP_CLR and CMP."""
    await start(dut)
    rng = random.Random(2026)
    m = TMAC()
    for trial in range(40 if not GL else 12):
        W = rand_weights(rng)
        await xfer(dut, [OP_LOAD_W] + pack_matrix(W))
        for i, byte in enumerate(pack_matrix(W)):
            m.write_wbyte(i, byte)
        assert await read_codes(dut) == m.weight_codes(), f"trial {trial}: weight readback"
        edge = rng.random() < 0.3
        acts = [rng.choice((-128, 127, -1, 0)) if edge else rng.randint(-128, 127) for _ in range(COLS)]
        await xfer(dut, [OP_LOAD_A] + [x & 0xFF for x in acts])
        for i, x in enumerate(acts):
            m.write_act(i, x & 0xFF)
        clear = trial % 3 == 0
        await xfer(dut, [OP_CMP_CLR if clear else OP_CMP])
        m.compute(clear)
        await check_all(dut, m, f"trial {trial}")


@cocotb.test()
async def test_streamed_matvec(dut):
    """LOAD_AC streaming: y = W x for K = 10*nvec in one transaction per weight chunk,
    as a K-chunked matrix-vector product would run."""
    await start(dut)
    rng = random.Random(7)
    m = TMAC()
    await xfer(dut, [OP_CLEAR])
    for chunk in range(3):
        W = rand_weights(rng, p_zero=0.2)
        await xfer(dut, [OP_LOAD_W] + pack_matrix(W))
        for i, byte in enumerate(pack_matrix(W)):
            m.write_wbyte(i, byte)
        nvec = 6 if not GL else 3
        stream = []
        for _ in range(nvec):
            acts = [rng.randint(-128, 127) for _ in range(COLS)]
            stream += [x & 0xFF for x in acts]
            for i, x in enumerate(acts):
                m.write_act(i, x & 0xFF)
            m.compute(clear=False)
        await xfer(dut, [OP_LOAD_AC] + stream)
        await check_all(dut, m, f"chunk {chunk}")


@cocotb.test()
async def test_signed_readback(dut):
    """Negative and boundary results read back as two's-complement int16, MSB first."""
    await start(dut)
    m = TMAC()
    # row r has a single +1 weight, in column r, so acc[r] = acts[r] = targets[r]
    targets = [-1, -3, 5, -128]
    W = [[1 if c == r else 0 for c in range(COLS)] for r in range(ROWS)]
    acts = [targets[c] if c < ROWS else 0 for c in range(COLS)]
    await xfer(dut, [OP_LOAD_W] + pack_matrix(W))
    await xfer(dut, [OP_LOAD_A] + [x & 0xFF for x in acts])
    await xfer(dut, [OP_CMP_CLR])
    for i, byte in enumerate(pack_matrix(W)):
        m.write_wbyte(i, byte)
    for i, x in enumerate(acts):
        m.write_act(i, x & 0xFF)
    m.compute(clear=True)
    assert m.acc == targets
    await check_all(dut, m, "signed")


@cocotb.test()
async def test_saturation(dut):
    """Accumulators clamp at +32767 / -32768 and set sticky per-row SAT flags instead
    of wrapping; a clamped value is a real value (accumulating back down from it works);
    CLEAR resets value and flags."""
    await start(dut)
    m = TMAC()
    # per compute: row 0 +1270, rows 1-2 -1270, row 3 +635 (stays in range: control row)
    W = [[1] * COLS, [-1] * COLS, [-1] * COLS, [1] * 5 + [0] * 5]
    acts = [127] * COLS

    async def load(Wm):
        await xfer(dut, [OP_LOAD_W] + pack_matrix(Wm))
        for i, byte in enumerate(pack_matrix(Wm)):
            m.write_wbyte(i, byte)

    await load(W)
    await xfer(dut, [OP_LOAD_A] + acts)
    for i, x in enumerate(acts):
        m.write_act(i, x)
    for _ in range(ACC_MAX // 1270 + 2):                 # 27 computes: rows 0-2 saturate
        await xfer(dut, [OP_CMP])
        m.compute(clear=False)
    assert m.acc[:3] == [ACC_MAX, ACC_MIN, ACC_MIN] and m.sat_flags == [True, True, True, False]
    await check_all(dut, m, "saturated")
    assert uo_bit(dut, UO_SAT) == 1
    await load([[-1] * COLS, [1] * COLS, [0] * COLS, [0] * COLS])
    await xfer(dut, [OP_CMP])                            # 32767 - 1270, -32768 + 1270
    m.compute(clear=False)
    assert m.acc[:2] == [ACC_MAX - 1270, ACC_MIN + 1270]
    await check_all(dut, m, "back from the rails")
    await xfer(dut, [OP_CLEAR])
    m.clear()
    await check_all(dut, m, "after CLEAR")
    assert uo_bit(dut, UO_SAT) == 0


@cocotb.test()
async def test_bist(dut):
    """BIST from the opcode and from the ui[3] pin: PASS, DONE, signature = model,
    accumulators left equal to the model's; SPI writes during BIST are ignored."""
    await start(dut)
    exp = bist_expected()
    for trigger in ("opcode", "pin"):
        if trigger == "opcode":
            await xfer(dut, [OP_BIST])
        else:
            set_ui(dut, bist=1)
            await ClockCycles(dut.clk, 4, rising=False)
            set_ui(dut, bist=0)
        # try to corrupt state while it runs: these must be ignored
        await xfer(dut, [OP_LOAD_W, 0x00])
        while uo_bit(dut, UO_BUSY):
            await ClockCycles(dut.clk, 16)
        assert uo_bit(dut, UO_DONE) == 1 and uo_bit(dut, UO_PASS) == 1, f"BIST ({trigger}) failed"
        sig = (await xfer(dut, [OP_READ_S], 2))[1:]
        assert sig[0] << 8 | sig[1] == exp, f"signature 0x{sig[0]:02x}{sig[1]:02x} != 0x{exp:04x}"
        m = TMAC()
        m.run_bist(exp)
        await check_all(dut, m, f"after BIST ({trigger})")


@cocotb.test()
async def test_spi_abort_and_reset(dut):
    """A transaction aborted mid-byte must not write anything; rst_n mid-transaction
    returns everything to the reset state."""
    await start(dut)
    m = TMAC()
    # abort: send LOAD_A opcode then only 4 bits of a data byte
    set_ui(dut, csn=0)
    await ClockCycles(dut.clk, HALF, rising=False)
    for byte, nbits in ((OP_LOAD_A, 8), (0x7F, 4)):
        for i in range(7, 7 - nbits, -1):
            set_ui(dut, mosi=(byte >> i) & 1)
            await ClockCycles(dut.clk, HALF, rising=False)
            set_ui(dut, sck=1)
            await ClockCycles(dut.clk, HALF, rising=False)
            set_ui(dut, sck=0)
    set_ui(dut, csn=1)
    await ClockCycles(dut.clk, HALF, rising=False)
    W = [[1] * COLS for _ in range(ROWS)]
    await xfer(dut, [OP_LOAD_W] + pack_matrix(W))
    await xfer(dut, [OP_CMP_CLR])
    for i, byte in enumerate(pack_matrix(W)):
        m.write_wbyte(i, byte)
    m.compute(clear=True)                                  # activations still 0 -> acc 0
    await check_all(dut, m, "after abort")
    # now load something, then reset in the middle of a transaction
    await xfer(dut, [OP_LOAD_A] + [5] * COLS)
    await xfer(dut, [OP_CMP_CLR])
    set_ui(dut, csn=0)
    await ClockCycles(dut.clk, 20, rising=False)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5, rising=False)
    dut.rst_n.value = 1
    set_ui(dut, csn=1)
    await ClockCycles(dut.clk, 10, rising=False)
    m.reset()
    assert await read_codes(dut) == m.weight_codes()
    await check_all(dut, m, "after mid-transaction reset")
