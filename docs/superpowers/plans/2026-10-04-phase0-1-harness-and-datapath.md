# Phase 0 + Phase 1: Harness and Datapath Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the simulation/synthesis harness on macOS, then build the complete RV32I 5-stage pipelined datapath until the `rv32ui` ISA suite passes and bare-metal loops and function calls execute.

**Architecture:** Five pipeline stages IF / ID / EX / MEM / WB with flat stage-boundary register files named `<from>__<to>__<field>`. Full forwarding (EX→EX, MEM→EX, WB→ID) with a one-bubble load-use interlock. All control redirects — branch mispredict today, traps and interrupts from phase 3 — funnel through a single redirect mechanism declared in phase 1 and exercised by its branch arm only. The core is bus-agnostic: it drives `mem_req` / `mem_rsp`, which is what lets phases 7 and 10 swap in AXI and a real memory subsystem without touching the pipeline.

**Tech Stack:** Pure Verilog-2001 · Verilator 5.052 · Icarus Verilog (4-state nightly) · cocotb · Yosys (`synth` + `stat -liberty`) · SymbiYosys (later phases) · `riscv64-elf-gcc` with `-march=rv32imac_zicsr -mabi=ilp32` · riscv-arch-test + Sail in a Linux Docker container

**Spec:** `docs/superpowers/specs/2026-10-04-rv32imc-pipeline-soc-design.md` — read §3 (conventions), §4.1 (the eight architectural decisions), §4.3 (kernel boot contract — phase 1 owes only its misaligned-access and illegal-instruction rows; the CSR rows are phase 3), §5 (phases 0–1), §7 (verification), §9 (portability). The spec travels with this plan; executors read both.

## Global Constraints

- **Pure Verilog-2001.** Every file opens with `` `default_nettype none `` and closes with `` `default_nettype wire ``. Never use `logic`, `bit`, `int`, `always_ff`, `always_comb`, `enum`, `typedef struct`, `interface`, `modport`, or `assert property`. Immediate assertions (`assert (c) else $error(...)`), `$error`, `$fatal` and `$clog2` are permitted and expected.
- **File extension is `.v`.** Never `.sv`.
- **Naming.** Modules and files `snake_case`. Signals `snake_case`. Parameters and localparams `p_UPPER_SNAKE`. Signal crossing a stage boundary is `<from>__<to>__<field>`, e.g. `if_id__pc`, `id_ex__rs1_val`.
- **Pipeline bundle field offsets** live in `rtl/core/pipeline_regs.vh` as `localparam`s. Slices are never written with literal bit ranges.
- **Top-level ports on every leaf module:** `input wire clk`, `input wire rst_n` (active-low, asynchronous assert, synchronised deassert). One clock and one reset only — never a gated clock (`assign clk_g = clk & en;` is forbidden).
- **No vendor primitives in `rtl/`.** No `RAMB36E1`, `DSP48E1`, `BUFG`, `MMCME2_BASE`, `IBUF`, `ODDR`. `FPGA/` may hold them; `rtl/` may not.
- **Toolchain flags are exactly** `-march=rv32imac_zicsr -mabi=ilp32`. Soft ABI, no `F`, never `ilp32d`. Encoded in the Makefile and linker script, not passed ad hoc.
- **Architectural decisions already made** (spec §4.1) — do not relitigate: branch resolves in EX (2-cycle flush); MEM stage exists from the start; one unified redirect path; regfile writes in WB with a WB→ID bypass; predictor interface present but tied to constants.
- **Lint is a gate.** `make lint` runs Verilator `--lint-only -Wall` and must report zero warnings.
- **`make asic-check` is a gate.** Yosys `synth` must succeed from task 1 onward.
- Every task ends with a commit. Commit messages are lowercase, imperative, conventional-commit prefixed.

## Review Focus

Failure modes the spec implies, that no task's happy-path tests would otherwise catch. Each has a test pinned to the task that owns the code, listed in that task.

1. **Pipeline valid bits are never cleared by reset.** Verilator is 2-state and reads X as 0, so an unreset valid bit passes every functional test and then boots nondeterministically on silicon. *Expected:* after reset deasserts, no stage holds `valid = 1`. → Task 11
2. **Load-use hazard is exactly one bubble.** Off-by-one here is the single most common 5-stage bug; it passes straight-line tests and corrupts only dependent back-to-back code. *Expected:* `lw a0, 0(a1)` immediately followed by `add a2, a0, a3` stalls one cycle and yields the correct sum. → Task 10
3. **A write to `x0` is discarded.** `rd = 0` must never reach the register file write port, or `addi x0, x0, 1` corrupts the ISA. *Expected:* after executing it, `x0` is still 0. → Task 9
4. **Memory backpressure loses nothing and duplicates nothing.** `mem_rsp_valid` arriving late or held must not lose a load result, corrupt a store, or issue a request twice. *Expected:* with randomised stall patterns, every load returns the value that was written. → Task 8
5. **An unrecognised opcode raises `is_illegal` rather than falling through to a default ALU op.** A decoder with a permissive default silently executes garbage. *Expected:* `0xFFFF_FFFF` decodes as illegal, and `core.v` does not perform the default add. → Task 4

---

## File Structure

```
Makefile                          one entry point: lint / asic-check / area / test / arch-test
.gitattributes                    normalise line endings (macOS edits, Windows builds)
rtl/common/defs.vh                widths and global localparams
rtl/common/reset_sync.v           2-flop reset synchroniser, async assert / sync deassert
rtl/core/pipeline_regs.vh         stage-boundary bundle field offsets
rtl/core/pc_gen.v                 PC, next-PC, unified redirect arbiter, predictor stub
rtl/core/regfile.v                32x32, 2 read + 1 write, x0 hardwired
rtl/core/decode.v                 RV32I decode -> control bundle
rtl/core/imm_gen.v                all six RV32I immediate formats
rtl/core/alu.v                    add / sub / logic / shift / compare
rtl/core/hazard_unit.v            interlock detection
rtl/core/forwarding.v             EX->EX, MEM->EX, WB->ID bypass muxes
rtl/core/lsu.v                    address generation, load/store, mem_req/mem_rsp
rtl/core/core.v                   top: five stages, stall and flush propagation
tb/conftest.py                    cocotb clock/reset driver and common helpers
tb/test_smoke.v py                phase 0 clocking smoke test
tb/test_regfile.py                Task 3
tb/test_decode.py                 Task 4
tb/test_imm_gen.py                Task 5
tb/test_alu.py                    Task 6
tb/test_branch.py                 Task 7
tb/test_lsu.py                    Task 8
tb/test_wb.py                     Task 9
tb/test_forwarding.py             Task 10
tb/test_core_reset.py             Task 11, pins Review Focus 1 and 3
tb/test_core_isa.py               Task 12, runs rv32ui binaries end-to-end
sw/linker/rv32.ld                 text at 0x0000_0000, data, bss
sw/src/crt0.S                     set SP, copy .data, zero .bss, call main, halt loop
sw/src/main.c                     smoke program: loops, function calls, UART-free
scripts/fetch-arch-tests.sh       clone riscv-arch-test + Sail container image
scripts/build-sw.sh               assemble sw/ with the exact flags
scripts/asic-area.sh              per-module sky130 area via Yosys stat -liberty
scripts/fetch-liberty.sh          download sky130 liberty files into third_party/
third_party/                      liberty + fetched test suites; never committed
```

---

### Task 1: Simulation and synthesis harness

**Files:**
- Create: `Makefile`, `.gitattributes`, `rtl/common/defs.vh`, `rtl/common/reset_sync.v`, `rtl/core/core.v` (skeleton), `tb/conftest.py`, `tb/test_smoke.py`, `scripts/fetch-liberty.sh`, `scripts/asic-area.sh`
- Test: `tb/test_smoke.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `defs.vh` localparams: `p_XLEN = 32`, `p_PC_W = 32`, `p_INSTR_W = 32`, `p_REG_W = 32`, `p_ADDR_W = 32`, `p_DATA_W = 32`, `p_RESET_VEC = 32'h0000_0000`
  - `module reset_sync (input wire clk, input wire arst_n, output wire srst_n)`
  - `module core (input wire clk, input wire rst_n)` — skeleton with five 32-bit pipeline registers shifting a counter; signature is final, internals replaced by Tasks 2–11
  - Makefile targets `lint`, `asic-check`, `area`, `test` requiring `MODULE=<name>` and `TOP=<module>`, `arch-test`, `sw`

- [ ] **Step 1: Write the failing smoke test**

`tb/conftest.py` drives clock and reset: toggle `clk` at the simulator's clock period, hold `rst_n` low for 10 rising edges then release it, and expose a helper `reset(dut)` usable by every later test.

`tb/test_smoke.py` contains `test_pipeline_advances`: hold reset, release it, then for 20 cycles assert that `dut.core_id__value` equals the cycle count. `core.v` does not exist yet, so this fails at elaboration.

- [ ] **Step 2: Run to verify it fails**

Run: `make test MODULE=test_smoke TOP=core`
Expected: FAIL — Verilator cannot find module `core`, or cocotb reports the signal `core_id__value` does not exist.

- [ ] **Step 3: Create `defs.vh` and `reset_sync.v`**

`defs.vh` defines the seven localparams listed in Interfaces.

`reset_sync.v` is a 2-flop synchroniser: asynchronous assertion of `arst_n`, synchronous deassertion of `srst_n`.

```verilog
`default_nettype none
module reset_sync (input wire clk, input wire arst_n, output wire srst_n);
  reg [1:0] sync_q;
  always @(posedge clk or negedge arst_n)
    if (!arst_n) sync_q <= 2'b00;
    else         sync_q <= {sync_q[0], 1'b1};
  assign srst_n = sync_q[1];
endmodule
`default_nettype wire
```

- [ ] **Step 4: Create the `core.v` skeleton**

Five 32-bit registers named `core_id__value`, `core_ex__value`, `core_mem__value`, `core_wb__value`, plus `core_rr__value`, each shifting a counter. The module port list is exactly `(input wire clk, input wire rst_n)` and must not change in later tasks.

- [ ] **Step 5: Create the Makefile**

Targets and their fixed commands:

| Target | Command |
|---|---|
| `lint` | `verilator --lint-only -Wall --top-module $(TOP) rtl/**/*.v` |
| `asic-check` | `yosys -p "read_verilog -sv rtl/**/*.v; synth -top $(TOP); stat -liberty $(LIBERTY)"` |
| `area` | `scripts/asic-area.sh` (per-module; Task 12) |
| `test` | `verilator --x-assign unique --x-initial unique --assert --cc --exe` plus cocotb `MODULE=$(MODULE) TOPLEVEL=$(TOP)` |
| `sw` | `scripts/build-sw.sh` (Task 12) |
| `arch-test` | `scripts/fetch-arch-tests.sh` then run the suite (Task 12) |

Default `TOP=core`. `-Wall` warnings are errors — the target fails on any warning.

- [ ] **Step 6: Create `scripts/asic-area.sh` and `scripts/fetch-liberty.sh`**

`asic-area.sh` loops over each module in `rtl/core`, runs Yosys `synth -flatten` then `stat -liberty`, and prints a module → µm² table. `LIBERTY` defaults to `third_party/sky130_fd_sc_hd__tt_025C_1v80.lib`; `fetch-liberty.sh` downloads the sky130 liberty set into `third_party/`. `third_party/` is gitignored.

- [ ] **Step 7: Run all three gates**

Run: `make lint TOP=core && make asic-check TOP=core && make test MODULE=test_smoke TOP=core`
Expected: lint reports zero warnings, Yosys prints a cell count and chip area, cocotb reports `test_smoke` PASS.

- [ ] **Step 8: Commit**

```bash
git add Makefile .gitattributes rtl/common/defs.vh rtl/common/reset_sync.v \
        rtl/core/core.v tb/conftest.py tb/test_smoke.py scripts/
git commit -m "build: add verilator, cocotb and yosys harness with per-module area tracking"
```

---

### Task 2: PC generator and unified redirect arbiter

**Files:** Create `rtl/core/pc_gen.v` · Test `tb/test_pc_gen.py`

**Interfaces:**
- Consumes: `p_RESET_VEC` from `defs.vh`; `rst_n` like every leaf module (`core.v` instantiates `reset_sync` and drives the rest)
- Produces:

```verilog
module pc_gen (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        stall,           // upstream hold
  input  wire        redirect_valid,  // unified redirect from EX, and traps later
  input  wire [31:0] redirect_pc,
  input  wire        pred_taken,      // stub tied to 1'b0 until phase 5
  input  wire [31:0] pred_pc,         // stub tied to 32'b0 until phase 5
  input  wire        mem_rsp_valid,   // memory ready
  output reg  [31:0] pc,
  output reg  [31:0] next_pc,
  output reg         if_req_valid
);
```

- [ ] **Step 1: Write the failing tests** — `tb/test_pc_gen.py`: `test_resets_to_reset_vector`, `test_increments_by_four`, `test_redirect_overrides_next_pc`, `test_stall_freezes_pc`, `test_predicted_take_uses_pred_pc`.
- [ ] **Step 2: Verify they fail** — `make test MODULE=test_pc_gen TOP=pc_gen` → FAIL, module not found.
- [ ] **Step 3: Implement** — priority arbiter: `redirect_valid` > `pred_taken` > `pc + 4`. `next_pc` is combinational; `pc` registers on the clock only when not stalled. Wire `pred_taken`/`pred_pc` as inputs so phase 5 is a drop-in (§4.1 decision 8). **Every redirect source in the whole core funnels through `redirect_valid`/`redirect_pc` here** (§4.1 decision 5) — add a comment marking it as such.
- [ ] **Step 4: Verify they pass** — `make test MODULE=test_pc_gen TOP=pc_gen` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add pc generator with unified redirect arbiter"`.

---

### Task 3: Register file

**Files:** Create `rtl/core/regfile.v` · Test `tb/test_regfile.py`

**Interfaces:**
- Consumes: `clk`, `rst_n`
- Produces:

```verilog
module regfile (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [4:0]  rs1_addr,
  input  wire [4:0]  rs2_addr,
  input  wire [4:0]  rd_addr,
  input  wire [31:0] rd_data,
  input  wire        rd_we,
  output wire [31:0] rs1_data,
  output wire [31:0] rs2_data
);
```

- [ ] **Step 1: Failing tests** — `test_reads_zero_by_default`, `test_write_then_read`, `test_two_read_ports_are_independent`, `test_write_to_x0_is_discarded`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_regfile TOP=regfile` → module not found.
- [ ] **Step 3: Implement** — `reg [31:0] regs [0:31]`, combinational read, synchronous write. **Force `rd_we` low when `rd_addr == 5'd0`** — this is Review Focus line 3; the `regs[0]` entry must also be hardwired to zero so the discard is enforced twice. Written in a style that infers 2R+1W BRAM on FPGA.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_regfile TOP=regfile` → all PASS, including the `x0` test.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add 32x32 two-read one-write register file"`.

---

### Task 4: RV32I decoder

**Files:** Create `rtl/core/decode.v`, `rtl/core/pipeline_regs.vh` · Test `tb/test_decode.py`

**Interfaces:**
- Produces:

```verilog
module decode (
  input  wire [31:0] instr,
  output reg         uses_rs1, uses_rs2, uses_rd,
  output reg         reg_write, mem_read, mem_write,
  output reg         alu_src_imm, is_branch, is_jal, is_jalr,
  output reg [3:0]   alu_op,
  output reg [2:0]   branch_funct3,
  output reg         is_illegal
);
```

`pipeline_regs.vh` defines `p_IF_ID_*`, `p_ID_EX_*`, `p_EX_MEM_*`, `p_MEM_WB_*` field offsets for every stage bundle. `alu_op` encodes add, sub, sll, slt, sltu, xor, srl, sra, or, and.

- [ ] **Step 1: Failing tests** — `test_all_rv32i_opcodes_decode`, `test_immediate_formats_are_selected`, `test_jal_sets_uses_rs1_and_uses_rd`, `test_unknown_opcode_is_illegal`, `test_jalr_and_branch_use_rs1_rs2`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_decode TOP=decode` → module not found.
- [ ] **Step 3: Implement** — decode on `instr[6:0]`, `instr[14:12]`, and `instr[31:25]`. **Default every output to illegal, not to a working ALU operation** — Review Focus line 5; set the control fields only after matching a valid encoding, and assert `is_illegal` for `0xFFFF_FFFF` and for the M/C encodings not yet implemented (phase 2).
- [ ] **Step 4: Verify pass** — `make test MODULE=test_decode TOP=decode` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add RV32I decoder and pipeline bundle offsets"`.

---

### Task 5: Immediate generator

**Files:** Create `rtl/core/imm_gen.v` · Test `tb/test_imm_gen.py`

**Interfaces:** Consumes the immediate format select from `decode`. Produces:

```verilog
module imm_gen (
  input  wire [31:0] instr,
  input  wire [2:0]  imm_sel,   // 0 = I, 1 = S, 2 = B, 3 = U, 4 = J
  output wire [31:0] imm
);
```

- [ ] **Step 1: Failing tests** — `test_i_type_sign_extends`, `test_s_type_is_concatenated`, `test_b_type_is_shifted_and_reversed`, `test_u_type_places_bits_31_to_12`, `test_j_type_sign_extends_from_bit_20`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_imm_gen TOP=imm_gen` → module not found.
- [ ] **Step 3: Implement** — the five RV32I formats. The B and J forms require the bit-reversal-and-shift, which is the one algorithm worth writing out: for B-type, `imm = {{19{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0}`; for J-type, `imm = {{11{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0}`.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_imm_gen TOP=imm_gen` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add immediate generator for all RV32I formats"`.

---

### Task 6: ALU

**Files:** Create `rtl/core/alu.v` · Test `tb/test_alu.py`

**Interfaces:** Produces:

```verilog
module alu (
  input  wire [31:0] a,
  input  wire [31:0] b,
  input  wire [3:0]  alu_op,
  output reg  [31:0] result
);
```

- [ ] **Step 1: Failing tests** — `test_add_and_sub`, `test_logic_ops`, `test_shifts_including_sra`, `test_slt_and_sltu_treat_x0_as_zero`, `test_shift_by_zero_and_by_31`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_alu TOP=alu` → module not found.
- [ ] **Step 3: Implement** — the nine `alu_op` cases. Use a registered-by-combinatorial structure only; **no memory inference**. Assert on `alu_op` values outside the nine.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_alu TOP=alu` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add ALU with add sub logic shift and compare"`.

---

### Task 7: Execute stage, branch comparison and resolution

**Files:** Create `rtl/core/ex_stage.v` · Test `tb/test_branch.py`

**Interfaces:**
- Consumes: `alu`, `decode`, `imm_gen`, `pc_gen`'s redirect port
- Produces:

```verilog
module ex_stage (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [31:0] ex_rs1_data,      // post-forwarding operand A
  input  wire [31:0] ex_rs2_data,      // post-forwarding operand B
  input  wire [31:0] ex_pc,
  input  wire [31:0] ex_imm,
  input  wire [3:0]  ex_alu_op,
  input  wire [2:0]  ex_branch_funct3,
  input  wire        ex_is_branch, ex_is_jal, ex_is_jalr,
  input  wire        stall,
  output wire        redirect_valid,
  output wire [31:0] redirect_pc,
  output wire [31:0] ex_alu_result,
  output wire        ex_reg_write, ex_mem_read, ex_mem_write
);
```

- [ ] **Step 1: Failing tests** — `test_beq_and_bne_take_and_fall_through`, `test_blt_and_bge_use_signed_compare`, `test_bltu_and_bgeu_use_unsigned_compare`, `test_jal_always_redirects_to_pc_plus_imm`, `test_jalr_clears_bit_zero`, `test_redirect_is_deasserted_for_non_branches`, `test_redirect_targets_are_aligned_or_raised_illegal`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_branch TOP=ex_stage` → module not found.
- [ ] **Step 3: Implement** — branch resolves **in EX** (§4.1 decision 1), so `redirect_valid` here produces a two-cycle flush. `jal` target is `pc + imm`; `jalr` target is `(rs1 + imm) & ~32'd1`. Because phase 1 has no `C`, a target with bit 1 set is an instruction-address-misaligned condition: drive `is_illegal` rather than redirecting somewhere wrong. Comment that phase 3 adds the trap arm to this same path.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_branch TOP=ex_stage` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add execute stage with branch resolution in ex"`.

---

### Task 8: LSU and memory stage

**Files:** Create `rtl/core/lsu.v` · Test `tb/test_lsu.py`

**Interfaces:** Produces:

```verilog
module lsu (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [31:0] addr,
  input  wire [31:0] wdata,
  input  wire [3:0]  wstrb,      // one bit per byte lane
  input  wire        mem_read, mem_write,
  input  wire        stall,
  output reg         mem_req_valid,
  output reg  [31:0] mem_req_addr,
  output reg  [31:0] mem_req_wdata,
  output reg         mem_req_we,
  input  wire [31:0] mem_rsp_rdata,
  input  wire        mem_rsp_valid,
  output reg  [31:0] lsu_rdata
);
```

- [ ] **Step 1: Failing tests** — `test_load_issues_a_read_request`, `test_store_issues_a_write_request_with_byte_strobes`, `test_misaligned_access_is_flagged_illegal`, `test_backpressure_holds_the_request_without_duplicating_it`, `test_randomised_stall_patterns_never_lose_or_corrupt_a_load`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_lsu TOP=lsu` → module not found.
- [ ] **Step 3: Implement** — assert `mem_req_valid` until `mem_rsp_valid` arrives, then deassert; latch `mem_rsp_rdata` for loads. Misaligned word and halfword addresses raise `is_illegal` (§4.3 requires a defined answer, never undefined behaviour). **The backpressure tests are Review Focus line 4** — drive randomised `mem_rsp_valid` gaps and confirm each write is read back correctly.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_lsu TOP=lsu` → all PASS, including both backpressure tests.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add lsu with stallable memory request interface"`.

---

### Task 9: Writeback stage

**Files:** Create `rtl/core/wb_stage.v` · Test `tb/test_wb.py`

**Interfaces:** Produces:

```verilog
module wb_stage (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [31:0] wb_value,
  input  wire [4:0]  wb_rd,
  input  wire        wb_reg_write,
  output wire [4:0]  fwd_rd_addr,
  output wire [31:0] fwd_rd_data,
  output wire        fwd_reg_write,
  output wire [31:0] wb_final_data     // mux of ALU result and load data
);
```

- [ ] **Step 1: Failing tests** — `test_alu_result_is_selected`, `test_load_data_is_selected`, `test_write_is_withheld_when_reg_write_is_clear`, `test_rd_zero_produces_no_forward`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_wb TOP=wb_stage` → module not found.
- [ ] **Step 3: Implement** — `wb_final_data` muxes on `mem_read`. The forward outputs must already reflect the write **including** the `rd == 0` discard, so gate `fwd_reg_write` with `wb_rd != 5'd0` here rather than relying only on the regfile — Review Focus line 3 again, enforced at both ends.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_wb TOP=wb_stage` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add writeback stage with forwarding outputs"`.

---

### Task 10: Hazard unit and forwarding network

**Files:** Create `rtl/core/hazard_unit.v`, `rtl/core/forwarding.v` · Test `tb/test_forwarding.py`

**Interfaces:**
- Consumes: `decode` control for IF/ID and ID/EX; the `ex_mem__*` pipeline register latched from Task 7's `ex_stage` outputs; the `wb_stage` forward outputs
- Produces:

```verilog
module hazard_unit (
  input  wire        id_uses_rs1, id_uses_rs2,
  input  wire [4:0]  id_rs1_addr, id_rs2_addr,
  input  wire        ex_reg_write, ex_mem_read,
  input  wire [4:0]  ex_rd,
  input  wire        mem_reg_write, mem_rd,
  output wire        id_stall,        // one bubble
  output wire        ex_stall_from_mem,
  output wire        wb_stall
);

module forwarding (
  // produces ex_rs1_data / ex_rs2_data after applying, in priority order:
  // EX/MEM result, then MEM/WB result, then the register file value
  input  wire [31:0] id_ex_rs1_data,
  input  wire [31:0] id_ex_rs2_data,
  input  wire [31:0] fwd_rd_data,
  input  wire [4:0]  fwd_rd_addr,
  input  wire        fwd_reg_write,
  input  wire [31:0] ex_mem_alu_result,
  input  wire [31:0] ex_mem_store_data,
  input  wire [4:0]  ex_mem_rd,
  input  wire        ex_mem_reg_write,
  output wire [31:0] ex_rs1_data,
  output wire [31:0] ex_rs2_data
);
```

- [ ] **Step 1: Failing tests** — `test_ex_to_ex_forwarding_for_dependent_alus`, `test_mem_to_ex_forwarding_across_a_stall`, `test_wb_to_id_bypass`, `test_load_use_stalls_exactly_one_cycle`, `test_store_data_forwarding`, `test_no_forwarding_when_destination_is_x0`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_forwarding TOP=forwarding` → module not found.
- [ ] **Step 3: Implement** — three-way priority: EX/MEM, then MEM/WB, then register file. The load-use interlock asserts `id_stall` for exactly one cycle when `id_uses_rs*` matches an `ex_*` that is `reg_write` **and** `mem_read`. **`test_load_use_stalls_exactly_one_cycle` is Review Focus line 2** — assert the stall count equals 1, not merely that the value is eventually correct, because an off-by-one here passes every value check.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_forwarding TOP=forwarding` → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(core): add hazard detection and three-way forwarding network"`.

---

### Task 11: Core integration

**Files:** Replace the `rtl/core/core.v` skeleton · Test `tb/test_core_reset.py`, `tb/test_core_program.py`

**Interfaces:**
- Consumes: every module above
- Produces: `module core (input wire clk, input wire rst_n)` — **port list unchanged from Task 1.** Internally exposes `mem_req_*` and accepts `mem_rsp_*` as hierarchical signals the testbench drives, plus a `sim_mem_*` bypass selected by a `SIM_ONLY` `define` for Tasks 1–11.

- [ ] **Step 1: Failing tests** — `test_no_stage_is_valid_after_reset`, `test_single_addi_produces_the_right_register_value`, `test_back_to_back_dependent_addis`, `test_taken_branch_redirects_and_flushes_two_cycles`, `test_untaken_branch_falls_through_with_no_flush`, `test_load_then_use_of_the_loaded_value`.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_core_reset TOP=core` → fails, the skeleton still shifts a counter.
- [ ] **Step 3: Implement** — instantiate all five stages; propagate `stall` forward through MEM→EX→ID→IF and `flush` backward from the redirect. **On reset, force every valid bit low — this is Review Focus line 1**, the single highest-value line in the task, because Verilator's 2-state model hides it. Add immediate assertions: no stage writes the register file while reset is asserted, and `x0` is never a write destination.
- [ ] **Step 4: Verify pass** — `make test MODULE=test_core_reset TOP=core && make test MODULE=test_core_program TOP=core` → all PASS.
- [ ] **Step 5: Re-run the gates** — `make lint TOP=core && make asic-check TOP=core` → both clean.
- [ ] **Step 6: Commit** — `git commit -m "feat(core): integrate five-stage pipeline with stall and flush"`.

---

### Task 12: Software, ISA suite, and area baseline

**Files:** Create `sw/linker/rv32.ld`, `sw/src/crt0.S`, `sw/src/main.c`, `tb/test_core_isa.py`, `scripts/build-sw.sh`, `scripts/fetch-arch-tests.sh` · Test `tb/test_core_isa.py`

**Interfaces:**
- Consumes: the finished `core`
- Produces: `make sw`, `make arch-test`, and a committed `docs/area/phase1-area.md` table from `make area`

- [ ] **Step 1: Failing test** — `tb/test_core_isa.py::test_rv32ui_suite_passes` loads each `rv32ui` ELF from `third_party/arch-test/`, feeds it into `core`'s memory, runs until `ecall` halts, and compares the 32 registers against the expected values encoded in the binary. Initially the binaries do not exist, so it fails on missing files.
- [ ] **Step 2: Verify fail** — `make test MODULE=test_core_isa TOP=core` → FAIL, no binaries found.
- [ ] **Step 3: Create the software** — `crt0.S` sets `sp`, copies `.data`, zeroes `.bss`, calls `main`, then loops on `wfi`. `main.c` computes a loop sum and a function-call result into globals. `rv32.ld` places `.text` at `0x0000_0000` with a reset-vector jump to `crt0`. `build-sw.sh` compiles with exactly `-march=rv32imac_zicsr -mabi=ilp32` and converts with `objcopy -O binary`.
- [ ] **Step 4: Create the fetch script** — `fetch-arch-tests.sh` clones riscv-arch-test and builds or pulls the Sail reference in a Linux Docker container, since Sail has no prebuilt Darwin/arm64 binary (§10.1 of the spec).
- [ ] **Step 5: Pass the bare-metal tests** — `make test MODULE=test_core_program TOP=core` → PASS, proving loops and function calls execute (the phase 1 hand-written gate).
- [ ] **Step 6: Pass the ISA suite** — `make arch-test` → all `rv32ui` tests PASS. If environment-specific privileged-mode tests misbehave, use the `rv32ui-p` subset and record why in the commit message.
- [ ] **Step 7: Establish the area baseline** — `make area` writes a per-module µm² table to `docs/area/phase1-area.md`, and `make asic-check TOP=core` passes. This is the first data point for the phase-10 silicon area budget and the only input that can replace the estimate.
- [ ] **Step 8: Commit** — `git commit -m "feat(phase1): add bare-metal software and pass the rv32i isa suite"`.

---

## Phase 1 Exit Criteria

- [ ] `make lint TOP=core` — zero warnings
- [ ] `make asic-check TOP=core` — synthesises, area table exists
- [ ] `make test MODULE=test_core_isa TOP=core` — `rv32ui` green
- [ ] `make test MODULE=test_core_program TOP=core` — loops and function calls correct
- [ ] Icarus cross-check: the same regression passes under Icarus (4-state) overnight, catching X-propagation that Verilator hides
- [ ] `docs/area/phase1-area.md` committed with the per-module table
- [ ] All eight Review Focus behaviours have a named passing test