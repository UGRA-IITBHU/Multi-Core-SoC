# Phase 0 + Phase 1: Harness and Datapath Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze every module interface, stand up the harness, then build the complete RV32I 5-stage pipelined datapath as five independently-owned blocks — ending with the `rv32ui` ISA suite passing and bare-metal loops and function calls executing.

**Architecture:** Five pipeline stages IF / ID / EX / MEM / WB with flat stage-boundary register files named `<from>__<to>__<field>`. Full forwarding (EX→EX, MEM→EX, WB→ID) with a one-bubble load-use interlock. All control redirects — branch mispredict today, traps and interrupts from phase 3 — funnel through a single redirect mechanism declared in phase 1 and exercised by its branch arm only. The core is bus-agnostic: it drives `mem_req` / `mem_rsp`, which lets phases 7 and 10 swap in AXI and a real memory subsystem without touching the pipeline.

**Team model: 5 people, 5 blocks, one pipeline stage each.** See §Team Map. Phase A is serial and short. Phase B is fully parallel — one owner per block, no blocking between owners. Phase C is serial integration.

**Tech Stack:** Pure Verilog-2001 · Verilator 5.052 · Icarus Verilog (4-state nightly) · cocotb · Yosys (`synth` + `stat -liberty`) · SymbiYosys (later phases) · `riscv64-elf-gcc` with `-march=rv32imac_zicsr -mabi=ilp32` · riscv-arch-test + Sail in a Linux Docker container

**Spec:** `docs/superpowers/specs/2026-10-04-rv32imc-pipeline-soc-design.md` — read §3 (conventions), §4.1 (the eight architectural decisions), §4.3 (kernel boot contract; phase 1 owes only its misaligned-access and illegal-instruction rows), §5 (phases 0–1), §7 (verification), §9 (portability). The spec is the binding authority; the plan is its argument.

---

## Global Constraints

### Language

- **Pure Verilog-2001.** Every file opens with `` `default_nettype none `` and closes with `` `default_nettype wire ``. Never `logic`, `bit`, `int`, `always_ff`, `always_comb`, `enum`, `typedef struct`, `interface`, `modport`, `assert property`. Immediate assertions (`assert (c) else $error(...)`), `$error`, `$fatal` and `$clog2` are permitted and expected.
- **File extension is `.v`.** Never `.sv`.

### Drop-in contract (what "modular" means here, mechanically)

These are not aspirations. Each one is enforced by a command that fails.

1. **Every module compiles, lints, and simulates from its own source file alone.** `make lint TOP=<module>` and `make test MODULE=test_<module> TOP=<module>` must pass with only `<module>.v` plus `rtl/common/defs.vh` in the source list. Any hidden coupling to another owner's file is a build error, not an integration surprise.
2. **The Makefile enforces this structurally:** source list is `$(shell find rtl -name '$(TOP).v')`, so the file count for the build is decided by the module name, not by a glob.
3. **No hierarchical references across modules.** `dut.core.something` from inside another module's testbench is forbidden. Each testbench sees only its own module's ports.
4. **Port lists are frozen in Task 1.** They are committed before any RTL body is written. Changing one is a contract change: it requires the interface owner (P5) to sign off and the change is committed separately from any behavioural work.
5. **Every module file opens with a header comment** giving: module name, one-line purpose, port list with widths, the contract it guarantees, and a note that it is drop-in replaceable.
6. **No `defparam`, no hierarchical parameter overrides, no shared mutable state, no `initial` blocks in `rtl/`.**
7. **One module per file.** File name equals module name.

### Naming

Modules and files `snake_case`. Signals `snake_case`. Parameters and localparams `p_UPPER_SNAKE`. A signal crossing a stage boundary is `<from>__<to>__<field>`, e.g. `if_id__pc`, `id_ex__rs1_val`. Field offsets for every stage bundle live in `rtl/core/pipeline_regs.vh` as `localparam`s; slices are never written with literal bit ranges.

### Clock, reset, portability

- **Every leaf module's ports are exactly** `input wire clk`, `input wire rst_n` (active-low). One clock, one reset. **Gated clocks are forbidden** — `assign clk_g = clk & en;` will not pass review.
- **No vendor primitives in `rtl/`** — no `RAMB36E1`, `DSP48E1`, `BUFG`, `MMCME2_BASE`, `IBUF`, `ODDR`. `FPGA/` may hold them; `rtl/` may not.
- **Toolchain flags are exactly** `-march=rv32imac_zicsr -mabi=ilp32`. Soft ABI, no `F`, never `ilp32d`. Encoded in the Makefile and linker script.
- **Architectural decisions already made** (spec §4.1) — do not relitigate: branch resolves in EX; MEM stage exists from the start; one unified redirect path; regfile writes in WB with a WB→ID bypass; predictor interface present but tied to constants.

### Process

- **Lint is a gate.** `make lint` runs Verilator `--lint-only -Wall` and must report zero warnings.
- **`make asic-check` is a gate.** Yosys `synth` must succeed from Task 2 onward.
- Every task ends with a commit: lowercase, imperative, conventional-commit prefix.
- **Merge discipline:** Phase B branches merge to `main` only after that block's own suite is green on its own source alone.

---

## Review Focus

Failure modes the spec implies, that no task's happy-path tests would catch. Each is pinned to the task that owns the code.

1. **Pipeline valid bits are never cleared by reset.** Verilator is 2-state and reads X as 0, so an unreset valid bit passes every functional test and then boots nondeterministically on silicon. *Expected:* after reset deasserts, no stage holds `valid = 1`. → T8 (P5)
2. **Load-use hazard is exactly one bubble.** Off-by-one here is the most common 5-stage bug; it passes straight-line tests and corrupts only dependent back-to-back code. *Expected:* `lw a0,0(a1)` then `add a2,a0,a3` stalls one cycle and yields the right sum. → T7 (P5)
3. **A write to `x0` is discarded.** `rd = 0` must never reach the register file write port. *Expected:* after `addi x0,x0,1`, `x0` is still 0. → T3 (P2), reinforced in T5 (P4)
4. **Memory backpressure loses nothing and duplicates nothing.** *Expected:* with randomised `mem_rsp_valid` stalls, every load returns what was written. → T5 (P4)
5. **An unrecognised opcode raises `is_illegal`** rather than falling through to a default ALU op. *Expected:* `0xFFFF_FFFF` decodes illegal and no add is performed. → T3 (P2)

---

## Team Map

| Owner | Block | Modules | Responsibility |
|---|---|---|---|
| **P1** | **Fetch (IF)** | `pc_gen`, `if_stage` | PC, next-PC, the unified redirect arbiter, predictor stub. Sole owner of control redirect generation. |
| **P2** | **Decode (ID)** | `regfile`, `decode`, `imm_gen` | Register file, RV32I decode — **producer of the control bundle** — and all immediate formats. |
| **P3** | **Execute (EX)** | `alu`, `ex_stage` | ALU, branch comparison and resolution, and the `muldiv` slot that phase 2 fills. |
| **P4** | **Memory + retire (MEM/WB)** | `lsu`, `mem_stage`, `wb_stage` | Address generation, the memory interface, writeback and forward-source generation. |
| **P5** | **Hazards + integration + verification** | `hazard_unit`, `forwarding`, `core.v`, all cross-module tests | Interface freeze owner, the glue, and the test suite. Consumes every other block's control signals. |

**Why P5 owns integration:** hazard detection and forwarding are the only units that read *every* other owner's control outputs. Giving them to the integration owner means the cross-module contract is enforced by the person who also has to wire it. P5 also owns the ISA harness and the area baseline.

**Phase B is parallel with no inter-owner blocking.** P5's Tasks 6 and 7 develop against the frozen contracts from Task 1 and merge independently; only T8 wiring waits on the others.

---

## Phase A — Serial (one owner: P5)

### Task 1: Interface freeze and stubs

**Files:**
- Create: `docs/contracts/phase1-interfaces.md`, `rtl/core/pipeline_regs.vh`, `rtl/core/ctrl_fields.vh`, `rtl/common/defs.vh`
- Create stubs (exact frozen port lists, empty bodies, lint-clean): `rtl/core/pc_gen.v`, `if_stage.v`, `regfile.v`, `decode.v`, `imm_gen.v`, `alu.v`, `ex_stage.v`, `lsu.v`, `mem_stage.v`, `wb_stage.v`, `hazard_unit.v`, `forwarding.v`, `core.v`
- Test: `tb/test_stubs.py`

**Interfaces:**
- Produces the contract every later task codes against. `defs.vh`: `p_XLEN = 32`, `p_PC_W = 32`, `p_INSTR_W = 32`, `p_REG_W = 32`, `p_ADDR_W = 32`, `p_DATA_W = 32`, `p_RESET_VEC = 32'h0000_0000`. `pipeline_regs.vh`: `p_IF_ID_*`, `p_ID_EX_*`, `p_EX_MEM_*`, `p_MEM_WB_*` offsets. `ctrl_fields.vh`: control-bundle field names and widths.
- Every stub declares its **final** port list, an input for every output, and an immediate assertion per output that fires until implemented. Stubs must pass `-Wall`.

- [ ] **Step 1: Write the failing stub test** — `tb/test_stubs.py` instantiates each of the 13 modules, drives every input, and asserts each stub's not-implemented assertion fires. Fails now because the modules do not exist.
- [ ] **Step 2: Verify it fails** — `make test MODULE=test_stubs TOP=core` → FAIL, module not found.
- [ ] **Step 3: Write `docs/contracts/phase1-interfaces.md`** — for each of the 13 modules: purpose, full port list with direction and width, and the one-sentence guarantee it provides to its consumer. Include a signal-provenance table naming which owner produces each stage-bundle field.
- [ ] **Step 4: Write the three `.vh` files** — all widths and offsets from the spec, no magic numbers elsewhere.
- [ ] **Step 5: Write the 13 stubs** — exact port lists from the contract, empty bodies, `assert (0) else $error("not implemented: <module>.<signal>")` on each output. Every stub carries the five-part header comment the drop-in contract requires.
- [ ] **Step 6: Verify each stub lints standalone** — `for m in $(ls rtl/core/*.v | xargs -n1 basename | sed 's/.v$//'); do make lint TOP=$m || echo "FAIL $m"; done` → zero warnings for all 13. This is the check that proves no stub reaches outside its own file.
- [ ] **Step 7: Verify the stub test passes** — `make test MODULE=test_stubs TOP=core` → PASS, all assertions firing as expected.
- [ ] **Step 8: Commit** — `git commit -m "feat(core): freeze phase 1 module interfaces and lint-clean stubs"`

**Contract-change rule, effective now:** from this commit until T8, a change to any port list requires P5's sign-off and lands in its own commit with no behavioural change alongside it.

---

### Task 2: Build and verification harness

**Files:** Create `Makefile`, `.gitattributes`, `rtl/common/reset_sync.v`, `tb/conftest.py`, `scripts/asic-area.sh`, `scripts/fetch-liberty.sh`

**Interfaces:**
- Consumes: `defs.vh`, the 13 stubs
- Produces: `module reset_sync (input wire clk, input wire arst_n, output wire srst_n)`; Makefile targets `lint`, `asic-check`, `area`, `test`, `test-4state`, `sw`, `arch-test`

- [ ] **Step 1: Failing test** — extend `tb/conftest.py` with a `reset(dut, cycles)` helper and a clock driver; `tb/test_stubs.py` gains `test_reset_helper_deasserts_rst_n`, which fails because `reset_sync` does not exist.
- [ ] **Step 2: Verify it fails** — `make test MODULE=test_stubs TOP=core` → FAIL, `reset_sync` not found.
- [ ] **Step 3: Create `reset_sync.v`** — 2-flop synchroniser, asynchronous assertion, synchronous deassertion:

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

- [ ] **Step 4: Create the Makefile** — `TOP` defaults to `core`. Source list is `$(shell find rtl -name '$(TOP).v')` so a build can only ever contain the one module named by `TOP` — this is what enforces drop-in constraint 1.

| Target | Command |
|---|---|
| `lint` | `verilator --lint-only -Wall --top-module $(TOP) $(SRCS)` |
| `asic-check` | `yosys -p "read_verilog -sv $(SRCS); synth -top $(TOP); stat -liberty $(LIBERTY)"` |
| `area` | `scripts/asic-area.sh` |
| `test` | Verilator `--x-assign unique --x-initial unique --assert --cc --exe` plus cocotb with `MODULE=$(MODULE) TOPLEVEL=$(TOP)` |
| `test-4state` | same cocotb regression under Icarus Verilog |
| `sw` | `scripts/build-sw.sh` (T9) |
| `arch-test` | `scripts/fetch-arch-tests.sh` then the suite (T9) |

`-Wall` warnings fail the target. No `**` globs anywhere: `make` invokes `/bin/sh`, which on macOS has no globstar, so `**` would silently match nothing and lint would pass on zero files.

- [ ] **Step 5: Create `tb/conftest.py`** — `Clock` at the simulator's clock period, a `reset(dut, cycles=10)` helper holding `rst_n` low across `cycles` rising edges then releasing it, and a `cycles(dut, n)` helper that advances `n` clocks. Every later testbench uses these three and nothing else.
- [ ] **Step 6: Create `scripts/asic-area.sh` and `scripts/fetch-liberty.sh`** — `asic-area.sh` loops each module in `rtl/core`, runs Yosys `synth -flatten` then `stat -liberty`, and prints a module → µm² table. `LIBERTY` defaults to `third_party/sky130_fd_sc_hd__tt_025C_1v80.lib`; `fetch-liberty.sh` downloads the sky130 liberty set into `third_party/`. `third_party/` is gitignored.
- [ ] **Step 7: Run all gates** — `make lint TOP=core && make asic-check TOP=core && make test MODULE=test_stubs TOP=core` → zero warnings, a cell count, all stub assertions firing.
- [ ] **Step 8: Verify standalone linting still works** — rerun the Task 1 Step 6 loop → all 13 modules lint clean in isolation.
- [ ] **Step 9: Commit** — `git commit -m "build: add verilator, cocotb and yosys harness with standalone-module targets"`

---

## Phase B — Parallel (5 owners, no inter-owner blocking)

### Task 3 [P2]: Register file, decoder, immediate generator

**Files:** `rtl/core/regfile.v`, `decode.v`, `imm_gen.v` · Test: `tb/test_regfile.py`, `tb/test_decode.py`, `tb/test_imm_gen.py`

**Interfaces:**
- Consumes: `defs.vh`, `ctrl_fields.vh`, the frozen stubs
- Produces: `regfile` (`rs1_addr`/`rs2_addr`/`rd_addr`/`rd_data`/`rd_we` → `rs1_data`/`rs2_data`); `decode` (`instr` → `uses_rs1`/`uses_rs2`/`uses_rd`/`reg_write`/`mem_read`/`mem_write`/`alu_src_imm`/`is_branch`/`is_jal`/`is_jalr`/`alu_op[3:0]`/`branch_funct3[2:0]`/`imm_sel[2:0]`/`is_illegal`); `imm_gen` (`instr`, `imm_sel` → `imm`)

`imm_sel` encoding: 0 = I, 1 = S, 2 = B, 3 = U, 4 = J. `alu_op` encodes add, sub, sll, slt, sltu, xor, srl, sra, or, and.

- [ ] **Step 1: Failing tests** — regfile: `test_reads_zero_by_default`, `test_write_then_read`, `test_two_read_ports_are_independent`, `test_write_to_x0_is_discarded`. decode: `test_all_rv32i_opcodes_decode`, `test_immediate_formats_are_selected`, `test_jal_sets_uses_rs1_and_uses_rd`, `test_unknown_opcode_is_illegal`, `test_jalr_and_branch_use_rs1_rs2`. imm_gen: one test per format (`i`, `s`, `b`, `u`, `j`) including sign extension of bit 31.
- [ ] **Step 2: Verify they fail** — each `make test MODULE=test_<m> TOP=<m>` → FAIL, not-implemented assertion fires.
- [ ] **Step 3: Implement `regfile`** — `reg [31:0] regs [0:31]`, combinational reads, synchronous write. **Force `rd_we` low when `rd_addr == 5'd0` and hardwire `regs[0]` to zero**, enforcing Review Focus 3 at both ends. Write in a style that infers 2R+1W BRAM on FPGA.
- [ ] **Step 4: Implement `decode`** — decode on `instr[6:0]`, `instr[14:12]`, `instr[31:25]`. **Default every control output to illegal, not to a working operation** — Review Focus 5. Set control fields only after matching a valid encoding; assert `is_illegal` for `0xFFFF_FFFF` and for the M and C encodings phase 2 adds.
- [ ] **Step 5: Implement `imm_gen`** — the five formats. B and J need the bit-reversal, the one algorithm worth writing out: `b` is `{{19{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0}`; `j` is `{{11{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0}`.
- [ ] **Step 6: Verify each module passes standalone** — `make test MODULE=test_regfile TOP=regfile`, `... TOP=decode`, `... TOP=imm_gen` → all PASS, each compiling only its own source.
- [ ] **Step 7: Lint and synthesise each standalone** — `make lint TOP=<m> && make asic-check TOP=<m>` for all three → clean.
- [ ] **Step 8: Commit** — `git commit -m "feat(id): add register file, rv32i decoder and immediate generator"`

---

### Task 4 [P1]: PC generator, redirect arbiter, fetch stage

**Files:** `rtl/core/pc_gen.v`, `if_stage.v` · Test: `tb/test_pc_gen.py`, `tb/test_if_stage.py`

**Interfaces:**
- Consumes: `p_RESET_VEC`, `if_id__*` offsets from `pipeline_regs.vh`
- Produces: `pc_gen` (`clk`, `rst_n`, `stall`, `redirect_valid`, `redirect_pc`, `pred_taken`, `pred_pc` → `pc`, `next_pc`); `if_stage` (`clk`, `rst_n`, `pc`, `if_rsp_rdata`, `if_rsp_valid`, `stall`, `flush` → `if_id__pc`, `if_id__instr`, `if_id__valid`, `if_req_valid`, `if_req_addr`)

**Two memory ports, not one** (spec §6.3). Instruction fetch and load/store each own a port over one unified address space. Phase 4 adds separate L1 I$ and D$ that need independent bandwidth, so splitting now avoids redesigning fetch later — and avoids IF stalling whenever the LSU is active.

- [ ] **Step 1: Failing tests** — pc_gen: `test_resets_to_reset_vector`, `test_increments_by_four`, `test_redirect_overrides_next_pc`, `test_stall_freezes_pc`, `test_predicted_take_uses_pred_pc`. if_stage: `test_latches_pc_and_instr`, `test_holds_when_stalled`, `test_clears_valid_on_flush`, `test_valid_low_after_reset`, `test_issues_fetch_request_for_pc`, `test_latches_fetch_response_into_if_id`, `test_holds_fetch_valid_until_response`.
- [ ] **Step 2: Verify they fail** — both FAIL, not-implemented assertions fire.
- [ ] **Step 3: Implement `pc_gen`** — priority arbiter: `redirect_valid` > `pred_taken` > `pc + 4`. `next_pc` combinational; `pc` registers only when not stalled. Wire `pred_taken`/`pred_pc` as inputs tied to constants until phase 5 (§4.1 decision 8). **This module is the single point where every redirect in the core converges** (§4.1 decision 5) — comment it as the funnel so phase 3 adds its trap arm here without redesign.
- [ ] **Step 4: Implement `if_stage`** — drive `if_req_valid` with `if_req_addr` from the current `pc`, hold them until `if_rsp_valid`, then latch `if_rsp_rdata` into `if_id__instr` alongside `if_id__pc` using the offsets from `pipeline_regs.vh`. Assert `flush` forces `if_id__valid` low regardless of `if_rsp_rdata`.
- [ ] **Step 5: Verify both pass standalone** — `make test MODULE=test_pc_gen TOP=pc_gen && make test MODULE=test_if_stage TOP=if_stage` → all PASS.
- [ ] **Step 6: Lint and synthesise both standalone** — clean.
- [ ] **Step 7: Commit** — `git commit -m "feat(if): add pc generator, redirect arbiter and fetch stage"`

---

### Task 5 [P4]: LSU, memory stage, writeback

**Files:** `rtl/core/lsu.v`, `mem_stage.v`, `wb_stage.v` · Test: `tb/test_lsu.py`, `tb/test_mem_stage.py`, `tb/test_wb.py`

**Interfaces:**
- Consumes: `pipeline_regs.vh` `p_EX_MEM_*`, `p_MEM_WB_*`
- Produces: `lsu` (`clk`, `rst_n`, `addr`, `wdata`, `wstrb`, `mem_read`, `mem_write`, `stall` → `mem_req_valid`, `mem_req_addr`, `mem_req_wdata`, `mem_req_we`, `lsu_rdata`, `is_illegal`; inputs `mem_rsp_rdata`, `mem_rsp_valid`); `wb_stage` (`wb_value`, `wb_rd`, `wb_reg_write` → `wb_final_data`, `fwd_rd_addr`, `fwd_rd_data`, `fwd_reg_write`)

- [ ] **Step 1: Failing tests** — lsu: `test_load_issues_a_read_request`, `test_store_issues_a_write_request_with_byte_strobes`, `test_misaligned_access_is_flagged_illegal`, `test_backpressure_holds_the_request_without_duplicating_it`, `test_randomised_stall_patterns_never_lose_or_corrupt_a_load`. mem_stage: `test_latches_alu_result_and_store_data`, `test_holds_when_memory_is_outstanding`. wb_stage: `test_alu_result_is_selected`, `test_load_data_is_selected`, `test_write_is_withheld_when_reg_write_is_clear`, `test_rd_zero_produces_no_forward`.
- [ ] **Step 2: Verify they fail** — all three FAIL, not-implemented assertions fire.
- [ ] **Step 3: Implement `lsu`** — hold `mem_req_valid` until `mem_rsp_valid`, then deassert; latch `mem_rsp_rdata` for loads. Misaligned word and halfword addresses raise `is_illegal`, because §4.3 requires a defined answer rather than undefined behaviour. **The two backpressure tests are Review Focus 4** — drive randomised `mem_rsp_valid` gaps and confirm every write reads back correctly.
- [ ] **Step 4: Implement `mem_stage`** — latch into the `ex_mem__*` and `mem_wb__*` bundles using `pipeline_regs.vh` offsets; hold while an `lsu` request is outstanding.
- [ ] **Step 5: Implement `wb_stage`** — `wb_final_data` muxes on the load flag. **Gate `fwd_reg_write` with `wb_rd != 5'd0` here as well as at the register file** — Review Focus 3, enforced at both ends.
- [ ] **Step 6: Verify all three pass standalone** — `make test MODULE=test_lsu TOP=lsu`, `... TOP=mem_stage`, `... TOP=wb_stage` → all PASS.
- [ ] **Step 7: Lint and synthesise each standalone** — clean.
- [ ] **Step 8: Commit** — `git commit -m "feat(memory): add lsu, memory stage and writeback"`

---

### Task 6 [P3]: ALU and execute stage

**Files:** `rtl/core/alu.v`, `ex_stage.v` · Test: `tb/test_alu.py`, `tb/test_branch.py`

**Interfaces:**
- Consumes: post-forwarding operands `ex_rs1_data`/`ex_rs2_data` from P5's T7
- Produces: `alu` (`a`, `b`, `alu_op` → `result`); `ex_stage` (`clk`, `rst_n`, `ex_rs1_data`, `ex_rs2_data`, `ex_pc`, `ex_imm`, `ex_alu_op`, `ex_branch_funct3`, `ex_is_branch`, `ex_is_jal`, `ex_is_jalr`, `stall` → `redirect_valid`, `redirect_pc`, `ex_alu_result`, `ex_reg_write`, `ex_mem_read`, `ex_mem_write`, `ex_rd`)

- [ ] **Step 1: Failing tests** — alu: `test_add_and_sub`, `test_logic_ops`, `test_shifts_including_sra`, `test_slt_and_sltu_treat_x0_as_zero`, `test_shift_by_zero_and_by_31`. ex_stage: `test_beq_and_bne_take_and_fall_through`, `test_blt_and_bge_use_signed_compare`, `test_bltu_and_bgeu_use_unsigned_compare`, `test_jal_always_redirects_to_pc_plus_imm`, `test_jalr_clears_bit_zero`, `test_redirect_is_deasserted_for_non_branches`, `test_misaligned_target_raises_illegal_not_a_bad_redirect`.
- [ ] **Step 2: Verify they fail** — both FAIL, not-implemented assertions fire.
- [ ] **Step 3: Implement `alu`** — the nine `alu_op` cases. Combinational only; no memory inference. Immediate-assert on `alu_op` values outside the nine.
- [ ] **Step 4: Implement `ex_stage`** — branch resolves **in EX** (§4.1 decision 1), so `redirect_valid` here causes a two-cycle flush. `jal` target is `pc + imm`; `jalr` target is `(rs1 + imm) & ~32'd1`. Phase 1 has no `C`, so a target with bit 1 set is instruction-address-misaligned: raise `is_illegal` rather than redirecting somewhere wrong. Comment that phase 3 adds the trap arm to this same path.
- [ ] **Step 5: Verify both pass standalone** — `make test MODULE=test_alu TOP=alu && make test MODULE=test_branch TOP=ex_stage` → all PASS.
- [ ] **Step 6: Lint and synthesise both standalone** — clean.
- [ ] **Step 7: Commit** — `git commit -m "feat(ex): add alu and execute stage with branch resolution in ex"`

---

### Task 7 [P5]: Hazard detection and forwarding

**Files:** `rtl/core/hazard_unit.v`, `forwarding.v` · Test: `tb/test_forwarding.py`

**Interfaces:**
- Consumes: control from P2's `decode` via the `id_ex__*` and `if_id__*` bundles; forward sources from P4's `wb_stage`; latched EX/MEM values from P3's `ex_stage`
- Produces: `hazard_unit` (`id_uses_rs1`, `id_uses_rs2`, `id_rs1_addr`, `id_rs2_addr`, `ex_reg_write`, `ex_mem_read`, `ex_rd`, `mem_reg_write`, `mem_rd` → `id_stall`, `ex_stall_from_mem`); `forwarding` (`id_ex_rs1_data`, `id_ex_rs2_data`, `fwd_rd_addr`, `fwd_rd_data`, `fwd_reg_write`, `ex_mem_alu_result`, `ex_mem_store_data`, `ex_mem_rd`, `ex_mem_reg_write` → `ex_rs1_data`, `ex_rs2_data`)

- [ ] **Step 1: Failing tests** — `test_ex_to_ex_forwarding_for_dependent_alus`, `test_mem_to_ex_forwarding_across_a_stall`, `test_wb_to_id_bypass`, `test_load_use_stalls_exactly_one_cycle`, `test_store_data_forwarding`, `test_no_forwarding_when_destination_is_x0`.
- [ ] **Step 2: Verify they fail** — both FAIL, not-implemented assertions fire.
- [ ] **Step 3: Implement `forwarding`** — three-way priority: EX/MEM result, then MEM/WB, then the register file value.
- [ ] **Step 4: Implement `hazard_unit`** — assert `id_stall` for exactly one cycle when `id_uses_rs*` matches an EX-stage `reg_write` **and** `mem_read`. **`test_load_use_stalls_exactly_one_cycle` is Review Focus 2** — assert the stall *count* equals 1, not merely that the value is eventually correct, because an off-by-one passes every value check.
- [ ] **Step 5: Verify both pass standalone** — `make test MODULE=test_forwarding TOP=forwarding && make test MODULE=test_forwarding TOP=hazard_unit` → all PASS.
- [ ] **Step 6: Lint and synthesise both standalone** — clean.
- [ ] **Step 7: Commit** — `git commit -m "feat(core): add hazard detection and three-way forwarding network"`

---

## Phase C — Serial integration (P5)

### Task 8: Core integration

**Files:** Replace the `rtl/core/core.v` stub · Test: `tb/test_core_reset.py`, `tb/test_core_program.py`, **and update `tb/test_smoke.py`**

**Interfaces:**
- Consumes: all 12 completed modules and the frozen contract
- Produces: `core (input wire clk, input wire rst_n)` **plus both memory interfaces as real top-level ports**, not hierarchical signals — later phases hang AXI masters off these:
  - instruction fetch — outputs `if_req_valid`, `if_req_addr`; inputs `if_rsp_rdata`, `if_rsp_valid` (from P1's `if_stage`)
  - load/store — outputs `mem_req_valid`, `mem_req_addr`, `mem_req_wdata`, `mem_req_we`; inputs `mem_rsp_rdata`, `mem_rsp_valid` (from P4's `lsu`)

- [ ] **Step 1: Failing tests** — `test_no_stage_is_valid_after_reset`, `test_single_addi_produces_the_right_register_value`, `test_back_to_back_dependent_addis`, `test_taken_branch_redirects_and_flushes_two_cycles`, `test_untaken_branch_falls_through_with_no_flush`, `test_load_then_use_of_the_loaded_value`, and `test_x0_write_is_discarded_end_to_end`.
- [ ] **Step 2: Verify they fail** — `make test MODULE=test_core_reset TOP=core` → FAIL, still a stub.
- [ ] **Step 3: Instantiate all five stages** and the pipeline registers from `pipeline_regs.vh`. Propagate `stall` forward MEM→EX→ID→IF and `flush` backward from `redirect_valid`. Wire `hazard_unit`'s `id_stall` and `ex_stall_from_mem` into that chain.
- [ ] **Step 4: Force every valid bit low on reset** — **this is Review Focus 1 and the highest-value line in the task**, because Verilator's 2-state model hides it. Add immediate assertions that no stage writes the register file while reset is asserted and that `x0` is never a write destination.
- [ ] **Step 5: Update `tb/test_smoke.py`** — it currently asserts on a skeleton signal that no longer exists. Repoint it at the real core: it must confirm `rst_n` deassertion propagates and no stage comes up valid.
- [ ] **Step 6: Verify the whole core suite passes** — `make test MODULE=test_core_reset TOP=core && make test MODULE=test_core_program TOP=core && make test MODULE=test_smoke TOP=core` → all PASS.
- [ ] **Step 7: Re-run all per-module standalone suites** — every one of the 13 must still pass from its own source alone. A regression here means someone introduced cross-module coupling.
- [ ] **Step 8: Lint and synthesise the full core** — `make lint TOP=core && make asic-check TOP=core` → clean.
- [ ] **Step 9: Commit** — `git commit -m "feat(core): integrate five-stage pipeline with stall and flush"`

---

### Task 9 [P5]: Software, ISA suite, area baseline

**Files:** `sw/linker/rv32.ld`, `sw/src/crt0.S`, `sw/src/main.c`, `tb/test_core_isa.py`, `scripts/build-sw.sh`, `scripts/fetch-arch-tests.sh` · Test: `tb/test_core_isa.py`

**Interfaces:**
- Consumes: the finished `core`
- Produces: `make sw`, `make arch-test`, and a committed `docs/area/phase1-area.md`

- [ ] **Step 1: Failing test** — `tb/test_core_isa.py::test_rv32ui_suite_passes` loads each `rv32ui` ELF from `third_party/arch-test/` into the memory model, runs it, and fails unless the test's own self-check writes the pass signature. Fails now because no binaries exist.
- [ ] **Step 2: Verify it fails** — `make test MODULE=test_core_isa TOP=core` → FAIL, no binaries found.
- [ ] **Step 3: Create the software** — `crt0.S` sets `sp`, copies `.data`, zeroes `.bss`, calls `main`, then ends in a **plain `j .` spin loop** (not `wfi` — phase 1 has no privilege modes or wait-state support). `main.c` computes a loop sum and a function-call result into globals. `rv32.ld` places `.text` at `0x0000_0000`. `build-sw.sh` compiles with exactly `-march=rv32imac_zicsr -mabi=ilp32` and converts with `objcopy -O binary`.
- [ ] **Step 4: Create `scripts/fetch-arch-tests.sh`** — clones riscv-arch-test and builds or pulls the Sail reference inside a Linux Docker container, since Sail has no prebuilt Darwin/arm64 binary.
- [ ] **Step 5: Establish test termination** — termination is a **write to a magic `tohost` address** implemented in the simulation memory model, which is the riscv-tests convention. Phase 1 has no trap or CSR support (that is phase 3), so `ecall` cannot halt anything and the phase gate is the test's own signature, not host-side register comparison — riscv-arch-test does not encode expected register values in the binary.
- [ ] **Step 6: Pass the bare-metal tests** — `make test MODULE=test_core_program TOP=core` → PASS, proving loops and function calls execute.
- [ ] **Step 7: Pass the ISA suite** — `make arch-test` → all `rv32ui` tests PASS. If environment-specific privileged-mode tests misbehave, use the `rv32ui-p` subset and record why in the commit message.
- [ ] **Step 8: Establish the area baseline** — `make area` writes a per-module µm² table to `docs/area/phase1-area.md`; `make asic-check TOP=core` passes. This is the first real data point for the phase-10 silicon area budget and the only thing that can replace an estimate.
- [ ] **Step 9: Run the 4-state cross-check** — `make test-4state TOP=core` on the full suite, catching X-propagation Verilator hides.
- [ ] **Step 10: Commit** — `git commit -m "feat(phase1): add bare-metal software and pass the rv32i isa suite"`

---

## Phase 1 Exit Criteria

- [ ] `make lint TOP=core` — zero warnings
- [ ] `make asic-check TOP=core` — synthesises; area table exists
- [ ] `make arch-test` — `rv32ui` green
- [ ] `make test MODULE=test_core_program TOP=core` — loops and function calls correct
- [ ] Every one of the 13 modules still passes its own suite standalone (drop-in constraint 1)
- [ ] `make test-4state` clean on the full suite
- [ ] `docs/area/phase1-area.md` committed with the per-module table
- [ ] All five Review Focus behaviours have a named passing test
- [ ] Every module file carries its five-part header comment