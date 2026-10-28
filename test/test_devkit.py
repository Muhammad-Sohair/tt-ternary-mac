# SPDX-License-Identifier: Apache-2.0
"""Runs the board script devkit/tmac_bringup.py, unmodified, against the RTL.

The script is blocking MicroPython-style code. It runs in a cocotb bridge thread and
talks to a FakeTT that has the slice of the tt-micropython-firmware API the script uses.
Every pin access becomes a short coroutine on the simulator thread.

The test calls the script's own run_all(), so it checks the stage order and whatever
state one stage leaves for the next. S8 (clock sweep) is replaced by a stub: BIST at
50 MHz says nothing in RTL. Everything else runs as on the board, S4 and S5 in full.

Run: mingw32-make COCOTB_TEST_MODULES=test_devkit   (RTL only)
"""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.task import bridge, resume
from cocotb.triggers import Timer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "devkit"))
import tmac_bringup as B  # noqa: E402


@resume
async def _sleep_ns(ns):
    await Timer(max(int(ns), 1), unit="ns")


@resume
async def _write(sig, v):
    sig.value = v


@resume
async def _read(sig):
    return sig.value


class Port:
    def __init__(self, get=None, put=None):
        self.get, self.put = get, put

    def __getitem__(self, n):
        return (self.get() >> n) & 1

    def __setitem__(self, n, v):
        self.put(n, v)

    @property
    def value(self):
        return self.get()

    @value.setter
    def value(self, v):
        self.put(None, v)


class FakeTime:
    def sleep_us(self, us):
        _sleep_ns(us * 1000)

    def sleep_ms(self, ms):
        _sleep_ns(ms * 1e6)


class FakeTT:
    def __init__(self, dut):
        self.dut, self.clk_task, self.ui = dut, None, 0b0010
        self.ui_in = Port(lambda: self.ui, self._put_ui)
        self.uo_out = Port(lambda: int(_read(dut.uo_out)))

        class Design:
            def enable(self):
                _write(dut.ena, 1)

        class Shuttle:
            pass

        self.shuttle = Shuttle()
        setattr(self.shuttle, "tt_um_msohair_tmac", Design())

    def _put_ui(self, n, v):
        self.ui = v if n is None else (self.ui & ~(1 << n)) | (v << n)
        _write(self.dut.ui_in, self.ui)

    def clock_project_PWM(self, hz):
        _restart_clock(self, hz)

    def reset_project(self, on):
        _write(self.dut.rst_n, 0 if on else 1)


@resume
async def _restart_clock(tt, hz):
    if tt.clk_task is not None:
        tt.clk_task.stop()
    tt.clk_task = Clock(tt.dut.clk, round(1e9 / hz), unit="ns")
    tt.clk_task.start()


@cocotb.test()
async def test_devkit_run_all(dut):
    """run_all() as on the board: S1-S7 must all pass on a correct chip (S8 stubbed)."""
    dut.ui_in.value = 0b0010
    dut.uio_in.value = 0
    dut.ena.value = 0
    dut.rst_n.value = 0
    tt = FakeTT(dut)
    B.time = FakeTime()
    B.s8_clock_sweep = lambda t: "skipped (RTL)"

    out = await bridge(B.run_all)(tt)
    dut._log.info(f"run_all: {out}")
    failed = [k for k, v in out.items() if v is not True and k != "S8"]
    assert not failed, f"stages failed on the RTL: {failed}"
