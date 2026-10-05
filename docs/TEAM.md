# Team work division — Phase 1 (datapath)

Five people, five blocks, one pipeline stage each. Every interface is **already frozen** in
`docs/contracts/phase1-interfaces.md`, so nobody needs to negotiate with anybody else.

Repository: `https://github.com/UGRA-IITBHU/Multi-Core-SoC`
Setup instructions: **`docs/SETUP.md`** — read that first, it is complete and standalone.

---

## The one rule that makes this work

**You own your files. You do not touch anyone else's.**

The port list of every module is frozen. Every module also has to build and pass its tests
**completely on its own**, from its own source file alone — that is how we prove no hidden
coupling crept in. If you find a bug in another person's module, or you think their port list
is wrong: **do not edit it.** Report it. Changing a port list is a contract change and needs
the integrator, because four other people are building against it.

You will find at least one thing you think is wrong in someone else's block. Report it; don't
fix it.

---

## Before you write any code

```bash
git clone https://github.com/UGRA-IITBHU/Multi-Core-SoC.git
cd Multi-Core-SoC
git checkout main
```

Then follow `docs/SETUP.md` end to end. When `make lint TOP=alu` and `make test TOP=alu` both
work, you are ready.

### Before you code: read `docs/REFERENCES.md`

It has the **RISC-V ISA specification** links (including the exact chapters for your block),
**annotated datapath diagrams** with control signals, and — importantly — a table of **how our
design deliberately differs from those diagrams**, so you do not copy the wrong thing.

The short version of the differences that will bite you:

- Branches resolve in **EX**, not MEM.
- **Every** redirect goes through one funnel in `pc_gen`. There is no second path.
- `core` owns all four pipeline bundles and every `valid` bit; your module produces values only.
- The load-use interlock is **exactly one** stall cycle.
- Writeback has **three** sources, not two — `wb_sel` includes PC+4 for `JAL`/`JALR`.

**Your first real check** — confirm the stubs still assert "not implemented":

```bash
make test TOP=regfile
```

You should see a failure saying `not implemented: regfile.<signal>`. That is correct. Your job
is to make it pass.

---
## The diagram of implementation
![](https://notes.cs61c.org/build/five-stage-pipeline-690dc2e5439eb5f4dde99d25cba144bc.png)
## Who owns what

| Person | Block | Files you implement | Test file you write |
|---|---|---|---|
| **P1** | Fetch (IF) | `rtl/core/pc_gen.v`, `rtl/core/if_stage.v` | `tb/test_pc_gen.py`, `tb/test_if_stage.py` |
| **P2** | Decode (ID) | `rtl/core/regfile.v`, `rtl/core/decode.v`, `rtl/core/imm_gen.v` | `tb/test_regfile.py`, `tb/test_decode.py`, `tb/test_imm_gen.py` |
| **P3** | Execute (EX) | `rtl/core/alu.v`, `rtl/core/ex_stage.v` | `tb/test_alu.py`, `tb/test_branch.py` |
| **P4** | Memory + retire | `rtl/core/lsu.v`, `rtl/core/mem_stage.v`, `rtl/core/wb_stage.v` | `tb/test_lsu.py`, `tb/test_mem_stage.py`, `tb/test_wb.py` |
| **P5** | Hazards + glue | `rtl/core/hazard_unit.v`, `rtl/core/forwarding.v` | `tb/test_forwarding.py` |

`rtl/core/core.v` belongs to the integrator. **Nobody implements it.** It wires all five
blocks together. If you think it needs a wire you cannot get, say so.

---

## P1 — Fetch

**`pc_gen`**: the PC and the one redirect funnel.

- `pc` starts at the reset vector and advances by 4.
- `next_pc` is combinational, priority `redirect_valid` > `pred_taken` > `pc + 4`.
- `pc` only advances when `stall` is low.
- **`pred_taken` and `pred_pc` are inputs tied to constants by `core` this phase.** Do not
  implement a predictor. Phase 5 plugs one in here and nothing else changes.

**`if_stage`**: drive `if_req_valid`/`if_req_addr` from the current `pc`, hold them until
`if_rsp_valid`, then latch `if_rsp_rdata` into `instr`. `flush` must force the stage's valid
state low regardless of `if_rsp_rdata`.

This is the **only** module that produces a redirect today. Every redirect in the whole core
funnels through `redirect_valid`/`redirect_pc` here — traps and interrupts join this same path
in phase 3. Do not add a second path.

## P2 — Decode

**`decode`**: pure combinational, `instr` in, control out. No state.

- `alu_op` — nine operations: add, sub, sll, slt, sltu, xor, srl, sra, or, and.
- `op1_sel` / `op2_sel` — choose operand sources. This replaces a simple `alu_src_imm`; use it.
- `imm_sel` — 0=I, 1=S, 2=B, 3=U, 4=J.
- `branch_funct3`, and `is_branch` / `is_jal` / `is_jalr` which are **mutually exclusive**.
- `is_illegal` — set for any encoding you do not implement. Phase 1 is RV32I only, so the
  M-extension and C-extension encodings are **illegal here**, not silently ignored.
- `mem_size`, `mem_unsigned` — needed for correct `LB`/`LH`/`LBU`/`LHU` and `SB`/`SH`.
- `wb_sel`, `reg_write`, `mem_read`, `mem_write`, `uses_rs1`, `uses_rs2`, `uses_rd`.

**Critical:** default every output to *illegal*, not to a working operation. A decoder with a
permissive default silently executes garbage. `0xFFFF_FFFF` must come out illegal.

You do **not** produce register addresses. The integrator extracts `rs1`/`rs2`/`rd` from the
instruction bits directly — that is wiring, not decoding.

**`regfile`**: 32×32, two combinational read ports, one synchronous write port
(`wb_waddr`/`wb_wdata`/`wb_we`). **`x0` must be discarded, twice**: gate `wb_we` low when
`wb_waddr` is 0, *and* hardwire `x0` to zero. Also honour `rs1_used`/`rs2_used`.

**`imm_gen`**: all five RV32I immediate formats. B and J need the bit-reversal:

```
b: {{19{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0}
j: {{11{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0}
```

## P3 — Execute

**`alu`**: combinational, nine `alu_op` cases. Also output `zero`, `slt` and `sltu` — the
branch comparator uses them, which is why they are separate outputs.

**`ex_stage`**: **branch resolution happens here**, in EX. It computes `ex_redirect_valid` and
`ex_redirect_pc`.

- `jal` target = `pc + imm`
- `jalr` target = `(rs1 + imm)` with bit 0 cleared
- conditional branches compare per `branch_funct3`, using `alu`'s `zero`/`slt`/`sltu`
- Phase 1 has no compressed instructions, so **a target with bit 1 set is
  instruction-address-misaligned**: assert `ex_target_misaligned`, do not redirect somewhere
  wrong.

`ex_store_data` is `rs2` for stores. `ex_mem_size`/`ex_mem_unsigned` pass through to the LSU.

## P4 — Memory and retire

**`lsu`**: address generation, the memory handshake, and byte enables.

- Hold `mem_req_valid` until `mem_rsp_valid`, then deassert. Never lose or duplicate a request.
- Derive `mem_req_wstrb[3:0]` from `ex_mem_addr[1:0]` and `ex_mem_size` — this is what makes
  `SB` and `SH` correct. Assert the byte lanes on writes, drive zero on reads.
- Misaligned word or halfword access → assert `data_misaligned`. Never behave in an undefined
  way.
- Pass `mem_rd_addr`, `mem_reg_write`, `mem_wb_sel` through to writeback.

**`mem_stage`**: select the writeback value per `wb_sel` — including the **pc+4** case for
`JAL`/`JALR` link registers. It reports `data_misaligned`; it does **not** gate anything —
the integrator applies that gate when packing.

**`wb_stage`**: the final writeback. Note the contract currently has a `data_misaligned`
input with no consumer — **you decide**: either use it, or delete the port and say so in your
report. Do not leave a dead port behind.

Gate `fwd_reg_write` with `wb_waddr != x0`, the same rule `regfile` applies at the other end.

## P5 — Hazards and forwarding

**`forwarding`**: three-way priority into the execute operands.

1. EX/MEM result (most recent)
2. MEM/WB result
3. register file value (least recent)

**`hazard_unit`**: **only the load-use interlock.** When ID needs an operand that EX is about
to produce with a load, assert `id_stall` for exactly one cycle.

The `id_stall` duration is the single most bug-prone thing in this block. Write a test that
asserts the stall **count equals 1**, not merely that the value is eventually correct — an
off-by-one passes every value check and corrupts only dependent back-to-back code.

You also own the harness (Task 2), and one harness bug is open against it: **`make test` cannot
pass on a machine whose Verilator is 4.x**, including most Linux installs from `apt`, because
cocotb 2.x needs Verilator 5. It fails for every module in a `g++` error inside cocotb's own
shim, which reads like a broken DUT. See the "Open item against T2" block in the plan and
docs/SETUP.md §2. Until it is fixed at the Makefile level, everyone has to install 5.x into
`.venv` and put it ahead on `PATH` by hand.

---

## Commands you run

For each of your modules:

```bash
make lint        TOP=<module>      # must be zero warnings
make asic-check  TOP=<module>      # must succeed
make test        TOP=<module>      # your cocotb test, must pass
```

Then, before you push:

```bash
make test-contracts               # the frozen contract must still hold
make lint TOP=<each of your modules>
make test-4state TOP=<module>     # catches X-propagation Verilator hides
```

**A note on `asic-check` warnings.** Right now every module reports
`Wire <module>.<output> is used but has no driver`, because the bodies are empty. **Those
warnings should be gone when you finish.** If they persist, you have written a stub, not a
module. This is your single best "am I actually done?" signal.

---

## Definition of done, per person

- [ ] Your module's `make lint` reports zero warnings
- [ ] Your module's `make asic-check` succeeds with **no "no driver" warnings**
- [ ] Your cocotb tests pass, and they genuinely test behaviour — not that a wire is a wire
- [ ] `make test-contracts` still passes — you did not break the freeze
- [ ] Every module still builds alone from its own source file
- [ ] Your five-part header comment at the top of each file is still accurate
- [ ] Committed on your own branch, pushed to GitHub

## Style rules, briefly

Pure Verilog-2001. `` `default_nettype none `` at the top of every file,
`` `default_nettype wire `` at the bottom. No `logic`, `always_ff`, `always_comb`, `enum`,
`typedef struct`, or `interface` — use `` `define `` only for bundle offsets if you need to,
otherwise `localparam`. **No gated clocks**: use an enable inside `always @(posedge clk)`.
Immediate assertions are fine and encouraged: `assert (c) else $error("...")`.

## Handing your work in

```bash
git checkout -b <your-name>-<block>
git add rtl/core/<your modules> tb/<your tests>
git commit -m "feat(<block>): implement ..."
git push -u origin <your-name>-<block>
```

Then tell the integrator. Your branch gets reviewed and merged into
`main`, and then `core.v` wires it all together. **You will not be asked
to write `core.v`.**

## Suggested build order

Everyone can start in parallel — the contract is frozen, so no one is blocked. For **merge**
order, go front to back so each block has its inputs available when it lands:

**P2 decode → P1 fetch → P4 memory → P3 execute → P5 hazards**

Reasoning: P2 produces the control bundle every other block consumes, so its names are settled
first. P3 execute sits last among the blocks because it depends on P2's control and P1's
redirect, and P5's forwarding ties together values produced by P3 and P4.
