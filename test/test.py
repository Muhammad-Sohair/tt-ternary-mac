# SPDX-License-Identifier: Apache-2.0
# Practice testbench for the 8-bit loadable counter.
# The Python model below is the "golden reference": every cycle the DUT
# output is compared with it, bit for bit.

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge


class CounterModel:
    def __init__(self):
        self.count = 0

    def step(self, rst_n, en, load, value):
        if not rst_n:
            self.count = 0
        elif load:
            self.count = value
        elif en:
            self.count = (self.count + 1) & 0xFF


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1


async def drive_and_check(dut, model, en, load, value):
    # Called at a falling edge. Drive inputs here, let the rising edge capture
    # them, then sample at the next falling edge. Sampling mid-cycle (not right
    # after the rising edge) matters for gate-level sim: every cell has a
    # delay, so Q changes *after* the edge, just as on silicon.
    dut.ui_in.value = (load << 1) | en
    dut.uio_in.value = value
    await RisingEdge(dut.clk)
    model.step(1, en, load, value)
    await FallingEdge(dut.clk)
    got = int(dut.uo_out.value)
    assert got == model.count, f"en={en} load={load} val={value}: got {got}, want {model.count}"


@cocotb.test()
async def test_reset_and_hold(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    assert int(dut.uo_out.value) == 0, "count must be 0 after reset"
    model = CounterModel()
    for _ in range(5):                       # EN low: must hold
        await drive_and_check(dut, model, 0, 0, 0)


@cocotb.test()
async def test_wraparound(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    model = CounterModel()
    await drive_and_check(dut, model, 0, 1, 0xFD)   # load 253
    for _ in range(5):                              # 254,255,0,1,2
        await drive_and_check(dut, model, 1, 0, 0)
    assert model.count == 2


@cocotb.test()
async def test_load_priority(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    model = CounterModel()
    await drive_and_check(dut, model, 1, 1, 0x42)   # LOAD wins over EN
    assert model.count == 0x42


@cocotb.test()
async def test_random(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset(dut)
    model = CounterModel()
    rng = random.Random(1234)
    for _ in range(2000):
        await drive_and_check(dut, model, rng.randint(0, 1), int(rng.random() < 0.1), rng.randint(0, 255))
