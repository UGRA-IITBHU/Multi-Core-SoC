# Setting up and working on this repository

## What this project is

This is a from-scratch RV32IMAC 5-stage pipelined RISC-V SoC written in pure
Verilog-2001, with no vendor primitives and no behavioural shortcuts. It is
being built for an open-source ASIC flow: Yosys + the sky130 standard-cell
library, not an FPGA flow and not a simulator-only flow. The five pipeline
stages are fetch, decode, execute, memory and writeback, and the thirteen
modules that make them up are each drop-in replaceable from their own source
file alone. Everything you build is gated by a lint pass, a synthesis and
elaboration pass, and a cocotb regression that runs under two different
simulators.

Repository: <https://github.com/UGRA-IITBHU/Multi-Core-SoC>

---

## 1. Prerequisites

| Requirement | Why |
|---|---|
| macOS, Linux or WSL2 | the tooling below is POSIX-shell based |
| Command-line tools | `git`, `make`, `curl`, `python3` |
| ~3 GB free disk | Verilator, Icarus, Yosys, the sky130 liberty file and a per-checkout Python virtualenv |
| Python 3.9 or newer | cocotb 2.x |

On **Linux** everything below is the same except that Homebrew is not
available: install Verilator, Icarus Verilog and Yosys from your distribution
(`apt install verilator iverilog yosys`) or from the OSS CAD Suite, install
cocotb into the virtualenv exactly as shown, and get the RISC-V cross-compiler
from the `xpack-dev-tools/riscv-none-elf-gcc` project rather than from
`brew`. On **Windows**, use WSL2 and follow the Linux instructions; the `sh`
scripts under `scripts/` and `make` itself are not usable from native
PowerShell or `cmd.exe`.

### Alternative: the OSS CAD Suite

The [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) bundles
Yosys, Icarus Verilog, Verilator, iverilog's VPI modules and a matching
`cocotb` into one download. It is worth considering if you would rather not
manage six separate installs, but it does **not** cover the RISC-V
cross-compiler, and its versions will differ from the ones below. This
document describes the Homebrew-plus-virtualenv route, which is what the
project is currently verified against.

---

## 2. Install the tools

### macOS (Homebrew)

```sh
brew install verilator icarus-verilog yosys riscv64-elf-gcc
```

### cocotb, in a per-checkout virtualenv

Homebrew's Python is "externally managed" (PEP 668), so `pip install cocotb`
into it will be refused — that refusal is expected, not a problem. Use a
virtualenv inside the checkout instead:

```sh
cd Multi-Core-SoC
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install cocotb
```

The Makefile finds `.venv/bin/python` automatically and falls back to whatever
`python3` is on `PATH` if the virtualenv is absent, so nothing else needs
configuring. `.venv/` is gitignored: never commit it, and never install
cocotb into your system Python "just this once".

### sky130 liberty files

The synthesis targets need a standard-cell liberty file and there is no area
without one. It is 12.8 MB, so it is downloaded rather than committed:

```sh
scripts/fetch-liberty.sh
```

That fetches `third_party/sky130_fd_sc_hd__tt_025C_1v80.lib` (452 cells) into
`third_party/`, which is gitignored. `make asic-check` and `make area` both
refuse to run until it is there, and tell you this command. The download is
idempotent: run it as often as you like.

---

## 3. Verify the install

Run these five commands from the repository root. Each one should succeed and
print what is described.

```sh
verilator --version        # Verilator 5.052
iverilog -V | head -1      # Icarus Verilog version 12.0 (stable)
yosys -V                   # Yosys 0.69+post
riscv64-elf-gcc --version  # riscv64-elf-gcc (GCC) 16.2.0
.venv/bin/cocotb-config --version   # 2.1.0
```

Those are the versions this project was developed and verified against. Other
versions will very likely work; if you see a failure that this document does
not explain, check your versions first and say so in your report.

Then check the harness itself. All of these must pass:

```sh
scripts/fetch-liberty.sh    # third_party/...lib is present (12800135 bytes).

make lint                                              # silence = success
make asic-check                                        # no ERROR, reaches "Printing statistics"
make test MODULE=test_reset_sync TOP=reset_sync        # TESTS=2 PASS=2 FAIL=0
make test-4state MODULE=test_reset_sync TOP=reset_sync # TESTS=2 PASS=2 FAIL=0
make test-contracts                                    # Ran 11 tests ... OK
make area                                              # module -> um^2 table
```

**What success looks like.** `make lint` prints the Verilator banner and
nothing else — it must be completely silent, because `-Wall` is a hard gate.
`make asic-check` and `make test` print a lot of tool output; read the
`TESTS=2 PASS=2 FAIL=0` line and the absence of `ERROR`. `make sw` and
`make arch-test` **fail** on purpose, because their scripts arrive in Task 9; a
non-zero exit with a "not implemented until Task 9" message is the correct
result, not a broken setup.

---

## 4. The everyday commands

| Command | What it does |
|---|---|
| `make lint` | `verilator --lint-only -Wall` on the module named by `TOP`. Silence means clean. |
| `make asic-check` | Yosys reads, elaborates with `hierarchy -check`, synthesises, maps to sky130 and reports area. |
| `make area` | The `asic-check` flow run over every module, as a module → µm² table. |
| `make test` | The cocotb regression under Verilator (two-state X handling). |
| `make test-4state` | The same regression under Icarus Verilog (4-state X propagation). |
| `make test-contracts` | The interface-freeze guard for all 13 core modules. |
| `make sw` | Fails loudly: `scripts/build-sw.sh` arrives in Task 9. |
| `make arch-test` | Fails loudly: `scripts/fetch-arch-tests.sh` arrives in Task 9. |

### Choosing what gets built and tested

Two variables drive everything:

* **`TOP=`** — the module name. This is the whole point of the harness: the
  source list is derived from `TOP` *by name*, never by a glob, so a build can
  only ever contain the one module you asked for plus the shared headers.
* **`MODULE=`** — the cocotb test module in `tb/` that `make test` should run.

```sh
make lint TOP=alu
make asic-check TOP=ex_stage
make test MODULE=test_alu TOP=alu
make test-4state MODULE=test_alu TOP=alu
```

You do not need to read the Makefile to use these: `TOP` is the design module,
`MODULE` is the test file. A test module and its design module normally share a
name with `test_` in front (`tb/test_alu.py` drives `alu`), which is the
convention to follow when you add one.

`TOP` defaults to `core` and `MODULE` defaults to `test_$(TOP)`, so
`make test TOP=alu` finds `tb/test_alu.py` by itself and you only need `MODULE=`
when a module has more than one test file.

### Running every module's lint in one go

This is the loop to run before you open a pull request, and the one to copy
when you replace a stub with a real implementation:

```sh
for m in pc_gen if_stage regfile decode imm_gen alu ex_stage lsu \
         mem_stage wb_stage hazard_unit forwarding core reset_sync; do
  make lint TOP=$m || break
done
```

### Writing a testbench

`tb/conftest.py` is the only support code a testbench should need. Use its
three helpers and nothing else:

```python
import cocotb
from conftest import Clock, cycles, reset


@cocotb.test()
async def test_something(dut):
    cocotb.start_soon(Clock(dut.clk).start())
    await reset(dut)            # 10 cycles of reset, then released and settled
    await cycles(dut, 4)        # 4 rising edges, settled
    assert int(dut.result.value) == 0
```

The clock period lives in `conftest.CLOCK_PERIOD_NS`; no testbench should
hard-code a time. `reset` drives whichever reset inputs the DUT actually has
(`rst_n`, `arst_n`, or both) and `cycles` returns with the design settled, so a
signal read straight afterwards is the value produced *by* the last edge and
not the value that edge replaced. Both details matter: get them wrong and every
assertion in your test is off by a cycle.

---

## 5. Troubleshooting

### "A command silently matched no files and passed"

The nastiest failure mode in this harness, because it produces a green gate
that checked nothing. `/bin/sh` on macOS has no `**` globstar, so a `**`
pattern matches nothing at all — and linting zero files exits 0.

Two defences are already in place, and both are load-bearing:

* No target uses a `**` glob. Sources come from `find rtl -name '$(TOP).v'`,
  and `asic-area.sh` enumerates with `find rtl -name '*.v'` at one level.
* The Makefile refuses to run at all if `TOP` matches nothing:

  ```
  Makefile:64: *** TOP='aluu' matched no source file.  aluu.v does not exist
  under rtl/.  Lint on zero files exits 0, so this must fail rather than pass.
  Stop.
  ```

If you ever add a target, keep both defences. If you add one that enumerates
files, assert that the list is non-empty before you loop over it — a `for` loop
over an empty list runs zero times and reports success.

### "`%Error: ... does not have a port named 'slt_typo'`" / `PINNOTFOUND`

A port name is wrong on one side of an instantiation — almost always a typo, or
a rename on one side only. Two different tools report it:

```
%Warning-PINCONNECTEMPTY: rtl/core/core.v:131:6: Instance pin connected by
  name with empty reference: 'slt_typo'          <- make lint TOP=core
ERROR: Module `alu' referenced in module `core' in cell `orphan_probe' does
  not have a port named 'slt_typo'.               <- make asic-check TOP=core
```

Check the port against `docs/contracts/phase1-interfaces.md`, which is the
frozen contract. **A port list is frozen**: changing one requires the
controller's sign-off and must land in its own commit with no behavioural
change alongside it. So the fix is nearly always to correct the *caller*, not
the callee.

### "Green lint, but elaboration fails"

Expected, and not a lint bug. Every module currently suppresses Verilator's
`UNDRIVEN` and `UNUSEDSIGNAL` warnings around its port list, because an empty
body drives and reads nothing. That suppression means **lint cannot prove a
port list is self-consistent** — an orphaned port lints clean. `make asic-check`
is what proves it, through `hierarchy -check`. Run both; do not treat a green
`make lint` as evidence that a port list is coherent.

### "syntax error, unexpected TOK_ELSE, expecting ';'"

You wrote an immediate assertion as `assert (cond) else $error("...");` and
handed the file to Yosys directly. Yosys's built-in Verilog frontend accepts
only `assert (cond);` — with no action clause — and its Homebrew build has no
slang or Verific frontend, so no flag fixes it. `make asic-check` and
`make area` therefore go through `scripts/yosys-prep.sh`, which copies the
sources with exactly those whole-line assertions removed before Yosys sees
them. Verilator and Icarus still see the real files with the real assertions.
If you add a new assertion form, check it against that script's single
deletion pattern; anything the pattern does not match is passed through and
Yosys will fail loudly, which is the safe outcome.

### "Area for cell type $_DFF_PN0_ is unknown!"

You ran `stat -liberty` on a netlist that has not been mapped onto the library
yet. `make asic-check` and `make area` do `dfflibmap -liberty` and
`abc -liberty` between `synth` and `stat` for this reason. If you are running
Yosys by hand, do the same.

### "Wire alu.\result [7] is used but has no driver"

Expected while a module is still an empty stub, and it will disappear when you
implement the body. It is the same condition Verilator's `UNDRIVEN`
suppression hides, so Yosys is telling you something lint will not. Do **not**
suppress it: it is the honest signal that a body is missing.

### "make: *** [test-contracts] Error 127 ... No such file or directory"

Your virtualenv is missing or incomplete. Recreate it with the two commands in
section 2. Check `.venv/bin/python` exists and that
`.venv/bin/cocotb-config --version` prints a version.

### "ModuleNotFoundError: No module named 'cocotb'"

You ran cocotb with your system Python instead of the virtualenv one. Either
use `make test` (which picks the virtualenv up automatically), or activate it
first with `source .venv/bin/activate`.

### A cocotb test fails but `make test` reported success

It cannot: `tb/run_test.py` reads the simulator's results file and exits
non-zero if any test failed. If you ever see a green `make test` over a red
summary, that is a bug in the harness, not in your test — report it rather
than working around it. A gate that cannot fail is worse than no gate.

### "not implemented: &lt;module&gt;.&lt;signal&gt;"

Not a failure of your environment. Every stub carries an immediate assertion
that fires until its body is written, so this message is the module telling you
it is still a stub. Replace the body and the message goes away.

---

## 6. Reference: what is where

| Path | What it is |
|---|---|
| `rtl/common/defs.vh` | Global datapath widths, as macros, included at file scope. |
| `rtl/core/ctrl_fields.vh` | Decode/execute control field widths, as macros. |
| `rtl/core/pipeline_regs.vh` | Bit offsets of the four stage bundles, as `localparam`, included **inside** `core`. |
| `rtl/common/reset_sync.v` | Asynchronous-assert, synchronous-deassert reset synchroniser. |
| `docs/contracts/phase1-interfaces.md` | The frozen port lists. Read this before you write a body. |
| `tb/conftest.py` | `Clock`, `reset`, `cycles`. The only testbench support code. |
| `tb/run_test.py` | Thin wrapper over cocotb's Python runner. |
| `tb/test_stubs.py` | The interface-freeze guard. Bypasses the Makefile on purpose. |
| `scripts/fetch-liberty.sh` | Downloads the sky130 liberty file. |
| `scripts/asic-area.sh` | The module → µm² table. |
| `scripts/yosys-prep.sh` | Works around Yosys not being able to parse immediate assertions. |

`tb/test_stubs.py` deliberately does not use the Makefile. It is a
self-driving stdlib `unittest` that generates its own Verilog wrappers and
drives Icarus directly, because no single `TOP=`-driven target can span all 13
modules at once. Run it with `make test-contracts`, and never fold it into
`make test`.