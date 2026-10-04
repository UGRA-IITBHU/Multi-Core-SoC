# Phase 1 interface contract — RV32IMAC 5-stage pipelined SoC

**Status:** frozen. This document and the 13 `.v` files in `rtl/core/` it
describes are the contract that Tasks 3–9 code against.

**Contract-change rule (in force from the commit that introduces this file
until Task 8 completes):** changing any port list in this document or in any
`rtl/core/*.v` file requires the controller's sign-off, and lands in its own
commit with no behavioural change alongside it.

**Include form.** Every module includes its shared widths with a bare
`` `include "defs.vh" `` — no relative path. The `+incdir` / `-I` path is
supplied by the Makefile (Task 2). The three shared headers are:

| Header | Contents |
|---|---|
| `rtl/common/defs.vh` | global datapath widths (`p_XLEN`, `p_PC_W`, `p_INSTR_W`, `p_REG_W`, `p_ADDR_W`, `p_DATA_W`, `p_RESET_VEC`, `p_REG_ADDR_W`) |
| `rtl/core/ctrl_fields.vh` | widths and names of the decode/execute control fields |
| `rtl/core/pipeline_regs.vh` | bit offsets of every field in the four stage bundles |

No width, offset or reset value is written as a literal number anywhere else.

**The drop-in rule.** Every module compiles and lints from its own source file
alone, with only the shared headers on the include path, and no module may
reference another module. `core` is the sole exception: it is the one file
allowed to instantiate the other twelve. Each stub is drop-in replaceable —
swapping the body must not change the port list and must not require any other
module to change.

**Assertion form.** Each stub carries an immediate assertion per output that
reports `not implemented: <module>.<signal>`. Modules with a clock assert on
`posedge clk`; purely combinational modules assert in an `initial` block at
time zero.

**Lint.** `verilator --lint-only -Wall` must report zero warnings for each
module on its own. The stubs suppress exactly two warning classes, and only
around the port list: `UNUSEDSIGNAL` and `UNDRIVEN`, which are unavoidable
while a body is empty.

---

## Stage overview

```
                     if_req_* / if_rsp_*  (top level)
                                │
pc_gen ──► if_stage ───────────┴─► [IF/ID] ──► regfile ──► decode ──► imm_gen
                                │                          │
                                └────────── [ID/EX] ◄──────┘
                                                │
                    forwarding ──► ex_stage ──► alu
                                                │
                            [EX/MEM] ◄──────────┘
                                                │
                    hazard_unit ────────────────┤
                                                ▼
                                              lsu ──► mem_req_*/mem_rsp_*  (top level)
                                                │
                            [MEM/WB] ◄───────────┘
                                                │
                                            mem_stage
                                                │
                                            wb_stage ──► regfile write port
                                                │
                                            fwd_rd_* ──► forwarding
```

---

## 1. `pc_gen` — fetch address generator

**Purpose.** Hold the address of the instruction being fetched, apply fetch
stalls, and apply the single redirect funnel that overrides the static next-PC
prediction.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | rising-edge clock |
| `rst_n` | in | 1 | active-low synchronous reset to `p_RESET_VEC` |
| `stall` | in | 1 | hold `pc`; this is how a fetch stall arrives |
| `redirect_valid` | in | 1 | take `redirect_pc` this cycle |
| `redirect_pc` | in | 32 | resolved redirect target |
| `pred_taken` | in | 1 | static prediction says the next PC is `pred_pc` |
| `pred_pc` | in | 32 | predicted next PC |
| `pc` | out | 32 | address of the instruction being fetched |
| `next_pc` | out | 32 | combinational next address after the arbiter |

**Guarantee to `if_stage`.** `pc` always holds the address of the instruction
currently being fetched; while `stall` is high `pc` does not advance, and
`redirect_valid` takes priority over both `pred_taken` and the sequential +4
step in the same cycle it is presented.

**Guarantee to `core`.** `next_pc` is the combinational result of that same
priority arbiter — `redirect_valid` > `pred_taken` > `pc + 4` — and is valid in
the same cycle as `pc`, so the arbiter's decision is observable without waiting a
cycle for `pc` to register. `pc` and `next_pc` never disagree about which source
won.

**Note.** `pc_gen` has no memory-response port. The instruction-fetch handshake
belongs to `if_stage` and the load/store handshake to `lsu`, so a fetch stall
reaches this module only through `stall`.

## 2. `if_stage` — instruction fetch

**Purpose.** Turn the address from `pc_gen` into an instruction word over the
instruction-fetch memory port, and publish the static next-PC prediction that
`pc_gen` consumes. This module owns the instruction-fetch port pair.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | rising-edge clock |
| `rst_n` | in | 1 | active-low synchronous reset |
| `stall` | in | 1 | hold the fetched instruction |
| `flush` | in | 1 | discard the fetched instruction (wrong path) |
| `pc` | in | 32 | address from `pc_gen` |
| `if_rsp_rdata` | in | 32 | instruction word returned by fetch memory |
| `if_rsp_valid` | in | 1 | fetch memory has returned an instruction |
| `if_req_valid` | out | 1 | request is being presented to fetch memory |
| `if_req_addr` | out | 32 | request address |
| `instr` | out | 32 | instruction word handed to decode |
| `pred_taken` | out | 1 | static prediction is a taken branch |
| `pred_pc` | out | 32 | predicted next PC |

**Guarantee to `decode` / `regfile` / `imm_gen`.** While `stall` and `flush`
are both low, `instr` is the instruction at `pc`; when `flush` is high the
instruction in flight is squashed so the following stage sees no stale
instruction. `pred_taken` and `pred_pc` are the only prediction state.

**Guarantee to fetch memory.** `if_req_valid` stays high from the cycle the
request is presented until `if_rsp_valid` is seen, and `if_req_addr` remains
stable for the whole of that window, so fetch memory may accept the request at
its own pace.

**Note — two ports, one address space.** Instruction fetch has its own port
pair (`if_req_*` / `if_rsp_*`) rather than sharing `mem_req_*` / `mem_rsp_*` with
`lsu`, even though both address the same unified memory. Phase 4 gives the core
separate L1 I$ and D$ that need independent bandwidth; a single arbitrated port
would force the fetch path to be redesigned then, and would stall instruction
fetch whenever the load/store unit is active. The data memory port therefore
has **two owners**: `if_stage` for fetch and `lsu` for load/store. The same pair
is exposed at the top level by `core`.

**Note.** `if_req_*` and `if_rsp_*` are also the top-level port names of `core`.
Renaming them requires changing `core` in the same commit.

## 3. `regfile` — 32×32 register file

**Purpose.** Supply the two decode-stage operand read ports and absorb the
single writeback port.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | rising-edge clock |
| `rst_n` | in | 1 | active-low synchronous reset to all-zero |
| `rs1_addr` | in | 5 | first source register index |
| `rs2_addr` | in | 5 | second source register index |
| `rs1_used` | in | 1 | instruction reads rs1; when low the read is forced to 0 |
| `rs2_used` | in | 1 | instruction reads rs2; when low the read is forced to 0 |
| `wb_we` | in | 1 | commit the writeback port this cycle |
| `wb_waddr` | in | 5 | writeback destination index |
| `wb_wdata` | in | 32 | writeback data |
| `rs1_data` | out | 32 | rs1 value after writeback bypass |
| `rs2_data` | out | 32 | rs2 value after writeback bypass |

**Guarantee to `ex_stage` via `core`.** Reads are combinational and bypass the
writeback port in the same cycle, so a load-use distance of one needs no
hazard stall. `rs1_data` / `rs2_data` are exactly `0` when the corresponding
`*_used` is low, and reading `x0` always yields `0`. Writes to `x0` are
discarded here as well as at `wb_stage`, so the discard is enforced at both
ends of the writeback path.

## 4. `decode` — RV32IMAC instruction decoder

**Purpose.** Turn one instruction word into the control bundle that drives
`imm_gen`, `ex_stage`, `lsu`, `mem_stage` and `wb_stage`. Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `instr` | in | 32 | instruction word from `if_stage` |
| `alu_op` | out | 4 | ALU operation select; encoding owned by `alu` / `ex_stage` |
| `op1_sel` | out | 2 | 0 = rs1, 1 = pc, 2 = zero |
| `op2_sel` | out | 3 | 0 = rs2, 1 = imm, 2 = 4, 3 = pc |
| `imm_sel` | out | 3 | immediate format for `imm_gen` |
| `branch_funct3` | out | 3 | funct3 for branch comparison in `ex_stage` |
| `is_branch` | out | 1 | conditional branch (BEQ/BNE/BLT/BGE/BLTU/BGEU) |
| `is_jal` | out | 1 | JAL |
| `is_jalr` | out | 1 | JALR |
| `is_illegal` | out | 1 | opcode or funct encoding not implemented |
| `uses_rs1` | out | 1 | instruction reads rs1 |
| `uses_rs2` | out | 1 | instruction reads rs2 |
| `uses_rd` | out | 1 | the rd field is meaningful |
| `mem_read` | out | 1 | instruction is a load |
| `mem_write` | out | 1 | instruction is a store |
| `mem_size` | out | 2 | 0 = byte, 1 = half, 2 = word |
| `mem_unsigned` | out | 1 | load is unsigned (LBU / LHU) |
| `reg_write` | out | 1 | instruction writes rd |
| `wb_sel` | out | 2 | 0 = alu, 1 = mem, 2 = pc+4 |

**Guarantee to `imm_gen` and `ex_stage`.** Every output describes exactly one
instruction, combinationally and with no pipeline state, so `core` can pack
them into ID/EX in the same cycle the instruction is decoded. `imm_sel`
encoding is **0 = I, 1 = S, 2 = B, 3 = U, 4 = J**. `mem_size` is meaningful
only when `mem_read` or `mem_write` is high and is `0` otherwise.

`is_branch`, `is_jal` and `is_jalr` are **mutually exclusive**: at most one is
high for any instruction, so `ex_stage` resolves a branch or jump from them plus
`branch_funct3` without re-decoding the opcode. `is_illegal` is **independent**
of them — an unimplemented encoding sets `is_illegal` and none of the three.

`uses_rd` is separate from `reg_write`: `reg_write` says the instruction updates
rd, `uses_rd` says the rd field carries a meaningful index, and the two differ
for instructions that merely mention rd. Downstream, `uses_rd` is what stops a
meaningless rd field from producing a false register-index match.

**Note — `is_illegal` is a decode verdict, not a trap.** Carrying it to a trap or
to writeback suppression is `core`'s job, because `core` owns the bundles. The
frozen contract carries `is_illegal` in ID/EX only; which further bundle, if
any, must also carry it is listed under *Known future contract changes*.
Misaligned *data* accesses are a separate condition, reported by
`lsu.is_illegal`.

## 5. `imm_gen` — immediate generator

**Purpose.** Produce the sign-extended 32-bit immediate selected by `decode`.
Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `instr` | in | 32 | instruction word |
| `imm_sel` | in | 3 | format select from `decode`: 0 = I, 1 = S, 2 = B, 3 = U, 4 = J |
| `imm` | out | 32 | sign-extended immediate, ready for `ex_stage` |

**Guarantee to `ex_stage`.** `imm` is fully sign-extended to `p_XLEN` and is
derived combinationally from `instr` and `imm_sel` alone, so `core` can
register it into ID/EX in the decode cycle. Formats 0–4 produce the standard
RV32 I/S/B/U/J immediate; any other `imm_sel` value must drive `imm` to zero
rather than to undefined bits.

## 6. `alu` — 32-bit integer ALU

**Purpose.** Perform the arithmetic, logic, shift and compare operation
selected by `decode`, and expose the comparison results branch resolution
needs. Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `op_a` | in | 32 | first operand, already selected by `ex_stage` |
| `op_b` | in | 32 | second operand, already selected by `ex_stage` |
| `alu_op` | in | 4 | operation select from `decode` |
| `result` | out | 32 | operation result |
| `zero` | out | 1 | result is zero |
| `slt` | out | 1 | signed less-than |
| `sltu` | out | 1 | unsigned less-than |

**Guarantee to `ex_stage`.** All four outputs are consistent with each other in
the same cycle, so branch resolution needs one ALU instance and no second
comparison pass.

**Note.** The `alu_op` encoding is internal to the execute block, which is
built by a single owner (`alu` and `ex_stage` are the same task), and is
therefore not enumerated here.

## 7. `ex_stage` — execute stage

**Purpose.** Consume the ID/EX operands, produce the memory address, store data
and destination register, and raise the single redirect that steers fetch.
Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `id_pc` | in | 32 | PC of the instruction in this stage |
| `id_imm` | in | 32 | immediate from `imm_gen`, registered |
| `id_rs1_addr` | in | 5 | rs1 index from decode |
| `id_rs2_addr` | in | 5 | rs2 index from decode |
| `id_rd_addr` | in | 5 | rd index from decode |
| `id_alu_op` | in | 4 | ALU operation select |
| `id_op1_sel` | in | 2 | first-operand select |
| `id_op2_sel` | in | 3 | second-operand select |
| `id_branch_funct3` | in | 3 | branch funct3 |
| `id_is_branch` | in | 1 | conditional branch (BEQ/BNE/BLT/BGE/BLTU/BGEU) |
| `id_is_jal` | in | 1 | JAL |
| `id_is_jalr` | in | 1 | JALR |
| `id_uses_rs1` | in | 1 | instruction reads rs1 |
| `id_uses_rs2` | in | 1 | instruction reads rs2 |
| `id_uses_rd` | in | 1 | the rd field is meaningful |
| `id_mem_read` | in | 1 | instruction is a load |
| `id_mem_write` | in | 1 | instruction is a store |
| `id_mem_size` | in | 2 | 0 = byte, 1 = half, 2 = word |
| `id_mem_unsigned` | in | 1 | load is unsigned |
| `id_reg_write` | in | 1 | instruction writes rd |
| `id_wb_sel` | in | 2 | writeback source select |
| `ex_rs1_data` | in | 32 | rs1 operand after hazard resolution, from `forwarding` |
| `ex_rs2_data` | in | 32 | rs2 operand after hazard resolution, from `forwarding` |
| `ex_alu_result` | out | 32 | ALU result; also the effective load/store address |
| `ex_store_data` | out | 32 | value to write on a store |
| `ex_rd_addr` | out | 5 | destination register index |
| `ex_reg_write` | out | 1 | this instruction writes rd |
| `ex_wb_sel` | out | 2 | writeback source select, forwarded to memory |
| `ex_mem_read` | out | 1 | this instruction is a load |
| `ex_mem_write` | out | 1 | this instruction is a store |
| `ex_mem_size` | out | 2 | access size |
| `ex_mem_unsigned` | out | 1 | load is unsigned |
| `ex_redirect_valid` | out | 1 | fetch must redirect this cycle |
| `ex_redirect_pc` | out | 32 | redirect target |

**Guarantee to `core`, `lsu` and `pc_gen`.** `ex_redirect_valid` is the only
redirect source in the pipeline, resolved in this stage in the cycle the branch
or jump is in EX, so `pc_gen` has exactly one funnel to obey.

Branch and jump resolution needs nothing beyond this port list:
`id_is_branch` / `id_is_jal` / `id_is_jalr` identify the instruction class,
`id_branch_funct3` selects the comparison, `id_pc` gives the sequential and
`pc + 4` target, `id_imm` gives the branch and JAL displacement, `id_alu_op`
with `id_op1_sel` / `id_op2_sel` gives the address arithmetic, and `ex_rs1_data`
/ `ex_rs2_data` are the already-forwarded operands. `ex_alu_result`
is the effective address for both loads and stores, so `lsu` needs no separate
address computation. When `id_uses_rs1` or `id_uses_rs2` is low the
corresponding operand is forced to zero here, so an unforwarded operand never
propagates stale data.

## 8. `lsu` — load/store unit, owner of the data memory interface

**Purpose.** Turn an EX/MEM access into a memory request, hold it until it is
granted, capture the returned data, and flag misaligned accesses.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | rising-edge clock |
| `rst_n` | in | 1 | active-low synchronous reset |
| `stall` | in | 1 | hold the outstanding request |
| `ex_mem_addr` | in | 32 | effective address from `ex_stage` |
| `ex_store_data` | in | 32 | value to write on a store |
| `ex_mem_read` | in | 1 | access is a load |
| `ex_mem_write` | in | 1 | access is a store |
| `ex_mem_size` | in | 2 | 0 = byte, 1 = half, 2 = word |
| `ex_mem_unsigned` | in | 1 | load is unsigned |
| `ex_rd_addr` | in | 5 | destination register index |
| `ex_reg_write` | in | 1 | access writes rd |
| `ex_wb_sel` | in | 2 | writeback source select for a load |
| `mem_rsp_rdata` | in | 32 | data returned by memory |
| `mem_rsp_valid` | in | 1 | memory has returned data |
| `mem_req_valid` | out | 1 | request is being presented to memory |
| `mem_req_addr` | out | 32 | request address |
| `mem_req_wdata` | out | 32 | request write data |
| `mem_req_we` | out | 1 | request is a write |
| `is_illegal` | out | 1 | misaligned word or halfword access |
| `mem_rd_addr` | out | 5 | destination register index for MEM/WB |
| `mem_reg_write` | out | 1 | MEM/WB writes rd |
| `mem_wb_sel` | out | 2 | MEM/WB writeback source select |

**Guarantee to `core` and `mem_stage`.** `mem_req_valid` stays high from the
cycle the request is presented until `mem_rsp_valid` is seen, and
`mem_req_addr`, `mem_req_wdata` and `mem_req_we` remain stable for the whole
of that window, so memory may accept the request at its own pace.
`mem_rsp_rdata` is passed straight through to `mem_stage`. This module owns the
load/store port pair only: instruction fetch has its own pair, `if_req_*` /
`if_rsp_*`, owned by `if_stage`. `is_illegal` is raised for a misaligned word or
halfword access rather than silently performing the access.

**Note.** `mem_req_*` and `mem_rsp_*` are also the top-level port names of
`core`. Renaming them requires changing `core` in the same commit.

## 9. `mem_stage` — memory stage, owner of the MEM/WB register

**Purpose.** Take the single-cycle data-memory response, select the value that
will be written back, suppress writeback of an illegal access, and register the
result into MEM/WB.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | rising-edge clock |
| `rst_n` | in | 1 | active-low synchronous reset |
| `stall` | in | 1 | hold the MEM/WB register |
| `mem_alu_result` | in | 32 | effective address / ALU result from EX/MEM |
| `mem_pc` | in | 32 | PC from EX/MEM, needed for the pc+4 writeback source |
| `mem_rsp_rdata` | in | 32 | data returned by `lsu` |
| `mem_rd_addr` | in | 5 | destination register index |
| `mem_reg_write` | in | 1 | the access writes rd |
| `mem_wb_sel` | in | 2 | 0 = alu, 1 = mem, 2 = pc+4 |
| `is_illegal` | in | 1 | misaligned access reported by `lsu` |
| `mem_rd_data` | out | 32 | value written back to rd |
| `mem_illegal` | out | 1 | an illegal access reached the memory stage |

**Guarantee to `wb_stage` and `forwarding`.** `mem_rd_data` is the single
already-selected writeback value for this instruction, so `wb_stage` needs no
multiplexer of its own; and `mem_reg_write` is forced low whenever
`is_illegal` is high, so a misaligned access never commits a register write.
`mem_illegal` is the same condition forwarded unchanged.

**Note for `core` (Task 8).** `core` must consume `mem_illegal`; leaving the
signal unread will trip `-Wall` in `core.v` and, more importantly, silently
drops the condition.

## 10. `wb_stage` — writeback stage

**Purpose.** Present the writeback value to `regfile` and publish the youngest
architectural result so `forwarding` can select it with the highest priority.
Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `mem_rd_data` | in | 32 | writeback value from `mem_stage` |
| `mem_rd_addr` | in | 5 | destination register index |
| `mem_reg_write` | in | 1 | the instruction writes rd |
| `mem_illegal` | in | 1 | an illegal access reached the memory stage |
| `wb_we` | out | 1 | commit the register write this cycle |
| `wb_wdata` | out | 32 | data to write |
| `wb_waddr` | out | 5 | register to write |
| `fwd_rd_addr` | out | 5 | destination of the WB-stage forwarding value |
| `fwd_rd_data` | out | 32 | WB-stage forwarding value |
| `fwd_reg_write` | out | 1 | WB-stage forwarding value is valid |

**Guarantee to `regfile` and `forwarding`.** `wb_we` is the single write enable
for the whole pipeline and is low whenever `mem_reg_write` is low, whenever
`mem_illegal` is high, or whenever `mem_rd_addr` is `x0`, so writes to `x0` are
discarded. `fwd_reg_write` carries that same `x0` exclusion, so `forwarding`
can never forward `x0` as an architectural value; `regfile` discards `x0`
writes independently, so the discard is enforced at both ends of the writeback
path.

**Note.** Purely combinational in phase 1: the MEM/WB pipeline register lives
in `mem_stage`, which owns the memory-stage timing.

## 11. `hazard_unit` — hazard detector

**Purpose.** Report the decode-stage stall needed for a load-use hazard and the
execute-stage stall needed while the memory stage is busy. Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `id_uses_rs1` | in | 1 | decode instruction reads rs1 |
| `id_uses_rs2` | in | 1 | decode instruction reads rs2 |
| `id_rs1_addr` | in | 5 | rs1 index of the decode instruction |
| `id_rs2_addr` | in | 5 | rs2 index of the decode instruction |
| `ex_mem_read` | in | 1 | EX/MEM instruction is a load |
| `ex_mem_write` | in | 1 | EX/MEM instruction is a store |
| `ex_rd_addr` | in | 5 | rd of the EX/MEM instruction |
| `mem_rsp_valid` | in | 1 | memory has not yet returned the outstanding data |
| `id_stall` | out | 1 | hold the decode stage this cycle |
| `ex_stall_from_mem` | out | 1 | hold the execute stage this cycle |

**Guarantee to `core`.** `id_stall` is asserted for exactly one cycle per
load-use dependency and covers every non-forwardable case;
`ex_stall_from_mem` is asserted for exactly as long as the memory stage holds
an outstanding data access, so a single-cycle memory response produces no stall
at all. Both outputs are combinational over the listed inputs only; there is
no hidden pipeline state.

**Note.** There is deliberately **no `wb_stall` output**. In phase 1 the
memory stage is a single-cycle pass-through, so nothing downstream of writeback
could consume such a signal. Adding it later is a contract change under the
gate above.

## 12. `forwarding` — operand forwarding network

**Purpose.** Supply `ex_stage` with the newest architectural value for each
operand, selecting between the MEM-stage and the WB-stage producer.
Combinational.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `ex_rs1_addr` | in | 5 | rs1 index of the instruction in execute |
| `ex_rs2_addr` | in | 5 | rs2 index of the instruction in execute |
| `id_rs1_addr` | in | 5 | rs1 index of the instruction in decode |
| `id_rs2_addr` | in | 5 | rs2 index of the instruction in decode |
| `id_uses_rs1` | in | 1 | the decode instruction reads rs1 |
| `id_uses_rs2` | in | 1 | the decode instruction reads rs2 |
| `mem_rd_addr` | in | 5 | destination of the MEM-stage value |
| `mem_rd_data` | in | 32 | MEM-stage value |
| `mem_reg_write` | in | 1 | the MEM-stage value is valid |
| `fwd_rd_addr` | in | 5 | destination of the WB-stage value |
| `fwd_rd_data` | in | 32 | WB-stage value |
| `fwd_reg_write` | in | 1 | the WB-stage value is valid |
| `fwd_rs1_valid` | out | 1 | forward into `ex_rs1_data` |
| `fwd_rs1_data` | out | 32 | forwarded rs1 operand |
| `fwd_rs2_valid` | out | 1 | forward into `ex_rs2_data` |
| `fwd_rs2_data` | out | 32 | forwarded rs2 operand |

**Guarantee to `ex_stage`.** When `fwd_rs1_valid` is high, `fwd_rs1_data` is
the newest value written to `ex_rs1_addr` by any earlier instruction, and
`fwd_rs1_valid` is low when no forwarding is needed. Where both the MEM and
the WB stage can supply the operand, the MEM stage wins because it is the
younger value. `x0` is never forwarded: `mem_reg_write` and `fwd_reg_write`
already exclude `x0` at their producers. The decode-stage `id_rs1_addr` /
`id_rs2_addr` inputs are present so that a hazard which cannot be forwarded is
reported to `core` rather than silently mis-resolved.

## 13. `core` — top level

**Purpose.** Instantiate and connect the whole pipeline, own the four pipeline
registers, and expose both memory port pairs to the outside world.

| Port | Dir | Width | Meaning |
|---|---|---|---|
| `clk` | in | 1 | rising-edge clock |
| `rst_n` | in | 1 | active-low synchronous reset |
| `if_rsp_rdata` | in | 32 | instruction returned by fetch memory |
| `if_rsp_valid` | in | 1 | fetch memory has returned an instruction |
| `mem_rsp_rdata` | in | 32 | data returned by memory |
| `mem_rsp_valid` | in | 1 | memory has returned data |
| `if_req_valid` | out | 1 | fetch request is being presented to memory |
| `if_req_addr` | out | 32 | fetch request address |
| `mem_req_valid` | out | 1 | request is being presented to memory |
| `mem_req_addr` | out | 32 | request address |
| `mem_req_wdata` | out | 32 | request write data |
| `mem_req_we` | out | 1 | request is a write |

**Guarantee to the surrounding system.** Both memory interfaces are exposed at
the top level under exactly the names their owners use for them — the fetch pair
exactly as `if_stage` names it, the load/store pair exactly as `lsu` names it —
so a memory subsystem or an AXI bridge attaches without any hierarchical
reference into this design.

**Note — two ports, one address space.** See the note on `if_stage`. The top
level exposes a fetch pair and a load/store pair rather than one arbitrated
memory port.

**Note.** This is the one module that instantiates the other twelve, and the
one module that owns all bundle packing.

---

## Signal provenance — who produces each stage-bundle field

**Stage modules produce values; `core` owns bundle packing.** No stage module
packs a stage bundle. `pc_gen`, `if_stage`, `decode`, `imm_gen`, `regfile`,
`ex_stage`, `lsu`, `mem_stage` and `wb_stage` each produce discrete signals on
their own ports; `core` is the only module that assembles those signals into the
`if_id__*`, `id_ex__*`, `ex_mem__*` and `mem_wb_*` bundles, using the offsets in
`pipeline_regs.vh`. A stage module's port list therefore never contains a
`p_<BUNDLE>__<field>` signal.

The tables below name which owner produces each field so that no stage-module
owner assumes they are also packing a bundle. `id_ex__*` in particular is
assembled by `core` from `decode` control fields, `regfile` read data and
`imm_gen` output.

**`core` also owns the per-bundle `valid` bits.** Because `core` packs the
bundles, the `if_id__valid`, `id_ex__valid`, `ex_mem__valid` and `mem_wb__valid`
bits are internal wires of `core`. No stage module has a `valid` port, and
`core` forces all four low while `rst_n` is asserted. Task 8's reset-validity
work and `test_no_stage_is_valid_after_reset` both depend on this, and it needs
no port-list change.

### Top-level memory ports — who owns which pair

Two port pairs over one unified address space. `core` exposes both at the top
level under the same names their owners use, and `core` wires each pair straight
through to its owner with no arbitration between them.

| Signal | Dir | Width | Owner | Feeds |
|---|---|---|---|---|
| `if_req_valid` | out | 1 | `if_stage` | top-level `if_req_valid` |
| `if_req_addr` | out | 32 | `if_stage` | top-level `if_req_addr` |
| `if_rsp_rdata` | in | 32 | fetch memory, consumed by `if_stage` | top-level `if_rsp_rdata` |
| `if_rsp_valid` | in | 1 | fetch memory, consumed by `if_stage` | top-level `if_rsp_valid` |
| `mem_req_valid` | out | 1 | `lsu` | top-level `mem_req_valid` |
| `mem_req_addr` | out | 32 | `lsu` | top-level `mem_req_addr` |
| `mem_req_wdata` | out | 32 | `lsu` | top-level `mem_req_wdata` |
| `mem_req_we` | out | 1 | `lsu` | top-level `mem_req_we` |
| `mem_rsp_rdata` | in | 32 | memory, consumed by `lsu` | top-level `mem_rsp_rdata` |
| `mem_rsp_valid` | in | 1 | memory, consumed by `lsu` | top-level `mem_rsp_valid` |

### IF/ID (width 97) — packed by `core` from `pc_gen` + `if_stage`

| Field | Width | Offset | Produced by |
|---|---|---|---|
| `pred_taken` | 1 | 0 | `if_stage` |
| `pc` | 32 | 1 | `pc_gen` |
| `pred_pc` | 32 | 33 | `if_stage` |
| `instr` | 32 | 65 | `if_stage` |

### ID/EX (width 170) — packed by `core`

| Field | Width | Offset | Produced by |
|---|---|---|---|
| `reg_write` | 1 | 0 | `decode` |
| `mem_unsigned` | 1 | 1 | `decode` |
| `mem_write` | 1 | 2 | `decode` |
| `mem_read` | 1 | 3 | `decode` |
| `wb_sel` | 2 | 4 | `decode` |
| `mem_size` | 2 | 6 | `decode` |
| `uses_rs2` | 1 | 8 | `decode` |
| `uses_rs1` | 1 | 9 | `decode` |
| `branch_funct3` | 3 | 10 | `decode` |
| `op2_sel` | 3 | 13 | `decode` |
| `op1_sel` | 2 | 16 | `decode` |
| `alu_op` | 4 | 18 | `decode` |
| `rd_addr` | 5 | 22 | `decode` (instruction bits) |
| `rs2_addr` | 5 | 27 | `decode` (instruction bits) |
| `rs1_addr` | 5 | 32 | `decode` (instruction bits) |
| `imm` | 32 | 37 | `imm_gen` |
| `rs2_data` | 32 | 69 | `regfile` |
| `rs1_data` | 32 | 101 | `regfile` |
| `pc` | 32 | 133 | `pc_gen` (via IF/ID) |
| `is_branch` | 1 | 165 | `decode` |
| `is_jal` | 1 | 166 | `decode` |
| `is_jalr` | 1 | 167 | `decode` |
| `is_illegal` | 1 | 168 | `decode` |
| `uses_rd` | 1 | 169 | `decode` |

The five fields above `pc` were added after the rest of the bundle was frozen,
so they sit at the top of ID/EX and **no previously frozen offset moves**. All
five are produced by `decode` and routed into the bundle by `core`.
`is_branch` / `is_jal` / `is_jalr` reach `ex_stage` as `id_is_branch` /
`id_is_jal` / `id_is_jalr`; `uses_rd` reaches it as `id_uses_rd`; `is_illegal` is
read by `core` out of the bundle it owns.

### EX/MEM (width 108) — packed by `core` from `ex_stage` + `lsu`

| Field | Width | Offset | Produced by |
|---|---|---|---|
| `reg_write` | 1 | 0 | `ex_stage` |
| `mem_write` | 1 | 1 | `ex_stage` |
| `mem_read` | 1 | 2 | `ex_stage` |
| `wb_sel` | 2 | 3 | `ex_stage` |
| `mem_size` | 2 | 5 | `ex_stage` |
| `rd_addr` | 5 | 7 | `ex_stage` |
| `store_data` | 32 | 12 | `ex_stage` |
| `alu_result` | 32 | 44 | `ex_stage` |
| `pc` | 32 | 76 | `ex_stage` (`id_pc`, registered) |

### MEM/WB (width 70) — packed by `core` from `mem_stage`

| Field | Width | Offset | Produced by |
|---|---|---|---|
| `reg_write` | 1 | 0 | `mem_stage` (`mem_reg_write`, with `is_illegal` gating) |
| `rd_addr` | 5 | 1 | `mem_stage` (`mem_rd_addr`) |
| `rd_data` | 32 | 6 | `mem_stage` (`mem_rd_data`) |
| `pc` | 32 | 38 | `mem_stage` (`mem_pc`) |

---

## Module ownership

| Module | Owner |
|---|---|
| `pc_gen`, `if_stage` | fetch block |
| `regfile`, `decode`, `imm_gen` | decode block |
| `alu`, `ex_stage` | execute block |
| `lsu`, `mem_stage`, `wb_stage` | memory / writeback block |
| `hazard_unit`, `forwarding` | hazards / forwarding block |
| `core` | controller (integration) |

## Known future contract changes

These are deliberately *not* in the frozen port lists. Each will need a
contract change under the gate above when its phase lands.

- **`decode.is_illegal` is now present** as of the second contract change; it is
  a frozen `decode` output and rides in ID/EX. What remains genuinely future is
  the *consumption* side: whether `is_illegal` must also ride in EX/MEM or
  MEM/WB so that an unimplemented instruction can be prevented from writing the
  register file, and whatever top-level trap signalling a phase needs. Today
  `lsu.is_illegal` and `mem_stage.mem_illegal` still cover *misaligned data
  accesses* only.
- **`wb_stall`.** Only meaningful once the memory stage is no longer a
  single-cycle pass-through.
- **Program loading.** A top-level path for getting a program into the design.
  The fetch port pair carries instruction *reads* only.
