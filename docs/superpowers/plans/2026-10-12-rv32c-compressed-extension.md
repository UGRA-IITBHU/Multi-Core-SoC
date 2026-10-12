# RV32C Compressed Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `C` extension to the five-stage core so that software compiled at `-march=rv32imac_zicsr` runs, matching the ISA the project already froze.

**Architecture:** The front end fetches the 4-byte-aligned word and selects either a halfword or the full word, computing the instruction length (2 or 4) from two bits with no feedback from decode. `pc_gen` gains a `pc_step` input; a 2-bit length is appended to three pipeline bundles so the JAL/JALR link address becomes `PC + len`. `decode` gains a combinational expander that rewrites a 16-bit encoding into its canonical 32-bit equivalent ahead of the unchanged 32-bit decode path.

**Tech Stack:** Pure Verilog-2001 · Verilator 5.052 (`--lint-only -Wall`) · Icarus Verilog (4-state) · cocotb · Yosys (`synth` + `stat -liberty`) · `riscv64-elf-gcc` at `-march=rv32imac_zicsr -mabi=ilp32`

**Spec:** `docs/superpowers/specs/2026-10-12-rv32c-compressed-extension-design.md` — read §3 (why this is tractable), §4.2 (the fetch table), §4.5 (expand-then-decode), §5 (the exact interface moves). The spec is the binding authority; this plan is its argument.

---

## Global Constraints

- **Pure Verilog-2001.** `` `default_nettype none `` opens every file, `` `default_nettype wire `` closes it. No `logic`, `bit`, `always_ff`, `always_comb`, `typedef`, `interface`. Immediate assertions (`assert (c) else $error(...)`) are expected.
- **File extension is `.v`**, never `.sv`.
- **Drop-in rule.** Every module lints and simulates from its own source file alone. `make lint TOP=<m>` and `make test MODULE=test_<m> TOP=<m>` must pass with only `<m>.v` plus the headers.
- **`-Wall` is a hard gate.** `make lint` reports zero warnings for every module. An unused new input port is a warning, so every port added here is used in the same commit that adds it.
- **Interface changes are atomic.** A port or bundle field moves in one commit together with (a) the RTL, (b) `docs/contracts/phase1-interfaces.md`, and (c) the `CONTRACT` table in `tb/test_stubs.py`. `make test-contracts` must be green at every commit. Any two of the three without the third is a broken tree.
- **Bundle fields are appended, never inserted.** `rtl/core/pipeline_regs.vh` grows new fields above each bundle's existing `VALID`, so no frozen offset moves.
- **Toolchain flags are exactly** `-march=rv32imac_zicsr -mabi=ilp32`. Never `rv32ima`.
- **Commit style:** lowercase conventional-commit prefix, imperative.
- **Two testbench facts to build every decode test on.** `await decode(dut, word)` returns a **dict** — read fields as `got["alu_op"]`, never `got.alu_op`. `await expect_illegal(dut, word, note)` returns `None` and asserts internally; call it bare. Compressed instruction words in tests are built with the file's existing `r_type`/`i_type`/`s_type`/`b_type`/`u_type`/`j_type` helpers and the RISC-V §16.7 encoding tables, not hard-coded magic numbers, so a typo in one vector cannot silently become the specification.
- Every task ends green: `make lint TOP=<m>`, `make test MODULE=test_<m> TOP=<m>`, and `make test-contracts` all pass before the commit.

## Review Focus

Failure modes the spec implies that no happy-path test catches. Each is pinned to the task that owns the code.

1. **`c.jal` / `c.jalr` link to PC+2, not PC+4.** A wrong link value is a silent 2-byte corruption of the return address that only shows up after the callee returns. → T7, T8
2. **A compressed instruction in the high halfword (`pc[1]==1`) is the instruction, not the low half.** Selecting the wrong half decodes a different instruction entirely. → T2
3. **A 32-bit opcode at `pc[1]==1` is misaligned, not executable.** The halfword bytes must come out illegal, not decode as the low half of some 32-bit instruction. → T2
4. **An RV64-only or F/D compressed encoding is illegal in RV32, not silently mapped.** `C.LD`, `C.SD`, `C.ADDIW`, `C.LDSP`, `C.SDSP`, `C.FLDSP`, `C.FSDSP`. → T4, T6
5. **A mixed 16/32-bit stream advances the PC by exactly the instruction's length.** Too small re-executes a halfword; too large skips one. → T1, T2, T9

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `rtl/core/pc_gen.v` | add `pc_step` input | step by the instruction's length |
| `rtl/core/if_stage.v` | add `instr_len` output; aligned fetch; halfword select | own "which bytes are this instruction, and how long is it" |
| `rtl/core/decode.v` | add `rvc_expand()` + pre-decode mux | expand compressed to canonical 32-bit before decoding |
| `rtl/core/ex_stage.v` | misalignment bit 1 → bit 0 | 2-byte alignment rule |
| `rtl/core/pipeline_regs.vh` | append `INSTR_LEN` to 3 bundles | carry the length to the link address |
| `rtl/core/core.v` | wire `pc_step`, `instr_len`, `em_instr_len` | bundle packing and the link value |
| `docs/contracts/phase1-interfaces.md` | port tables, bundle tables, misalignment note | the contract |
| `tb/test_stubs.py` | `CONTRACT` and bundle expectations | the mechanical guard |
| `tb/test_pc_gen.py`, `tb/test_if_stage.py`, `tb/test_decode.py`, `tb/test_branch.py`, `tb/test_core.py` | new and updated tests | the proof |

---

## Task 1: `pc_gen` variable step

**Files:**
- Modify: `rtl/core/pc_gen.v`
- Modify: `rtl/core/core.v` (the `pc_gen` instantiation)
- Modify: `docs/contracts/phase1-interfaces.md` (§1 port table)
- Modify: `tb/test_stubs.py` (`CONTRACT["pc_gen"]`)
- Test: `tb/test_pc_gen.py`

**Interfaces:**
- Produces: `pc_gen` input `pc_step [p_PC_W-1:0]`; `next_pc = redirect_valid ? redirect_pc : pred_taken ? pred_pc : (pc_q + pc_step)`.

- [ ] **Step 1: Update the contract doc and the guard**

In `docs/contracts/phase1-interfaces.md` §1, add `| pc_step | in | 32 | length of the instruction at `pc`, in bytes (2 or 4) |` to the `pc_gen` port table and change the `next_pc` guarantee wording from "`pc + 4`" to "`pc + pc_step`". In `tb/test_stubs.py`, append `("pc_step", "in", 32)` to `CONTRACT["pc_gen"]["ports"]`. Run `make test-contracts`. Expected: FAIL, because the RTL does not yet declare the port. That failure is the point of this step.

- [ ] **Step 2: Write the failing tests**

In `tb/test_pc_gen.py`, add `pc_step=4` to `idle()`'s parameters and drive it; give `PcGenModel.next_pc`/`step` a `pc_step` parameter and use it in place of the `PC_STEP` constant. Then add:

```python
@cocotb.test()
async def test_steps_by_pc_step(dut):
    """`pc` advances by `pc_step`, so a 2-byte compressed instruction steps 2."""
    await start(dut, pc_step=2)
    before = int(dut.pc.value)
    await settle()
    assert int(dut.next_pc.value) == (before + 2) & MASK
    await cycles(dut, 1)
    assert int(dut.pc.value) == (before + 2) & MASK


@cocotb.test()
async def test_pc_step_is_per_cycle(dut):
    """A step of 4 then 2 is applied in the cycle each is presented."""
    await start(dut, pc_step=4)
    assert int(dut.pc.value) == RESET_VEC + 4
    idle(dut, pc_step=2)
    await settle()
    await cycles(dut, 1)
    assert int(dut.pc.value) == RESET_VEC + 6
```

In the differential test, drive `pc_step=rng.choice((2, 4))` each cycle. The model must raise on `pc_step == 0`, because a zero step makes the differential test pass vacuously.

- [ ] **Step 3: Run to verify failure**

Run: `make test MODULE=test_pc_gen TOP=pc_gen`
Expected: FAIL — cocotb reports no `pc_step` handle on the DUT.

- [ ] **Step 4: Add the port and use it**

In `rtl/core/pc_gen.v`: add `input wire [`p_PC_W-1:0] pc_step` after `pred_pc`; delete the `p_PC_STEP` localparam; replace `(pc_q + p_PC_STEP)` with `(pc_q + pc_step)`; replace `pc + p_PC_STEP` in the third assertion with `pc + pc_step`; update the header's `+4` wording. In `rtl/core/core.v`, add `.pc_step (32'd4)` to the `pc_gen` instantiation, commented that T2 replaces the constant with `if_stage.instr_len`.

- [ ] **Step 5: Run to verify pass**

Run: `make test MODULE=test_pc_gen TOP=pc_gen && make lint TOP=pc_gen && make lint TOP=core && make test-contracts`
Expected: PASS, zero warnings, contracts green.

- [ ] **Step 6: Commit**

```bash
git add rtl/core/pc_gen.v rtl/core/core.v tb/test_pc_gen.py \
        docs/contracts/phase1-interfaces.md tb/test_stubs.py
git commit -m "feat(pc_gen): step the PC by the instruction length"
```

---

## Task 2: `if_stage` halfword selection and instruction length

**Files:**
- Modify: `rtl/core/if_stage.v`
- Modify: `rtl/core/core.v` (the `if_stage` instantiation and `pc_gen` wiring)
- Modify: `docs/contracts/phase1-interfaces.md` (§2 port table)
- Modify: `tb/test_stubs.py` (`CONTRACT["if_stage"]`)
- Test: `tb/test_if_stage.py`

**Interfaces:**
- Consumes: `pc_gen.pc_step`.
- Produces: `if_stage` output `instr_len [1:0]`; `if_req_addr = {pc[31:2], 2'b00}`.

- [ ] **Step 1: Update the contract doc and `CONTRACT["if_stage"]`**

Add `| instr_len | out | 2 | length of the instruction presented, in bytes (2 or 4); valid in ST_HOLD |` to §2's port table; state in the guarantee text that `if_req_addr` is the 4-byte-aligned word address. Add `("instr_len", "out", 2)` to `CONTRACT["if_stage"]["ports"]`. Run `make test-contracts`; expected FAIL on the missing port.

- [ ] **Step 2: Write the failing tests**

Add a module-level async helper `fetch_at(dut, pc, word)` to `tb/test_if_stage.py`, using the file's existing clock/reset helpers: start the clock, reset, drive `pc` and present `word` with `if_rsp_valid=1`, advance until `instr` is presented, and return `(int(dut.instr.value), int(dut.instr_len.value))`.

```python
@cocotb.test()
async def test_instr_is_the_low_halfword_when_compressed(dut):
    """pc[1]==0 and a compressed low half: instr is that halfword, len is 2."""
    instr, length = await fetch_at(dut, pc=0x0000_0100, word=0x0000_4081)
    assert instr == 0x0000_4081
    assert length == 2


@cocotb.test()
async def test_instr_is_the_high_halfword_when_pc_is_halfword_aligned(dut):
    """pc[1]==1: the instruction is the high half, len 2, low half ignored."""
    instr, length = await fetch_at(dut, pc=0x0000_0106, word=0x9782_0000)
    assert instr == 0x0000_9782
    assert length == 2


@cocotb.test()
async def test_instr_is_the_whole_word_when_32_bit(dut):
    """pc[1]==0 and low half == 2'b11: the full word is the instruction, len 4."""
    instr, length = await fetch_at(dut, pc=0x0000_0100, word=0x00C5_8533)
    assert instr == 0x00C5_8533
    assert length == 4


@cocotb.test()
async def test_high_half_with_a_32_bit_opcode_is_illegal(dut):
    """Review Focus 3: a 32-bit opcode at pc[1]==1 is misaligned, not decoded.

    The high half is 0x9F83 (low two bits 11).  Nothing may present it as the
    low half of a 32-bit instruction; the stage must present a word that
    decodes illegal, which here is all-zero.
    """
    instr, length = await fetch_at(dut, pc=0x0000_0106, word=0x9F83_0000)
    assert instr == 0x0000_0000
    assert length == 2


@cocotb.test()
async def test_fetch_address_is_word_aligned(dut):
    """A halfword-aligned pc presents a word-aligned request address."""
    # Drive pc = 0x0000_0106 and hold the request window; assert if_req_addr == 0x0000_0104.
    ...
```

For the last test, drive `pc` and, while `if_req_valid` is high, assert `int(dut.if_req_addr.value) == 0x0000_0104`.

- [ ] **Step 3: Run to verify failure**

Run: `make test MODULE=test_if_stage TOP=if_stage`
Expected: FAIL — no `instr_len` output, and `instr` is the raw word.

- [ ] **Step 4: Implement the selection and the length**

In `rtl/core/if_stage.v`: add `output wire [1:0] instr_len`; make `if_req_addr = {addr_source[31:2], 2'b00}` where `addr_source` is the existing `(state == ST_IDLE) ? pc : req_addr_q`; replace `assign instr = instr_q` with:

```verilog
wire at_high    = pc[1];                       // the instruction is the high half
wire high_is_32 = (instr_q[17:16] == 2'b11);   // the high half looks like an opcode
wire low_is_32  = (instr_q[1:0]   == 2'b11);   // the low  half looks like an opcode

// A 32-bit instruction is 4-byte aligned, so at pc[1]==1 only a compressed
// encoding is legal.  `high_is_32` is therefore a misaligned 32-bit opcode:
// present zero, which decodes illegal, rather than letting the high half be
// read as the low half of some unrelated 32-bit instruction (Review Focus 3).
assign instr     = at_high ? (high_is_32 ? {`p_INSTR_W{1'b0}} : {16'b0, instr_q[31:16]})
                           : (low_is_32  ? instr_q : {16'b0, instr_q[15:0]});
assign instr_len = (at_high || !low_is_32) ? 2'd2 : 2'd4;
```

`pc` is used directly because `pc_gen` is stalled whenever `if_req_valid` is high, so `pc` is stable from `ST_IDLE` through `ST_HOLD` and its low bit still names the instruction being presented. Delete the "instruction must be nonzero in `ST_HOLD`" assertion (compressed encodings mask the unused half to zero, so nonzero is no longer the invariant) and say so in a comment; the existing "no instruction before the response" check still covers the other direction. Change the `state != ST_IDLE || if_req_addr == pc` assertion to compare against `{pc[31:2], 2'b00}`. Update the header comment's `pc + 4` wording and its port list.

In `rtl/core/core.v`: change the `pc_gen` `.pc_step` connection from `32'd4` to `{30'b0, if_instr_len}` (declare `wire [1:0] if_instr_len` from the new `if_stage` output) and add `.instr_len (if_instr_len)` to the `if_stage` instantiation.

- [ ] **Step 5: Run to verify pass**

Run: `make test MODULE=test_if_stage TOP=if_stage && make test MODULE=test_pc_gen TOP=pc_gen && make lint TOP=if_stage && make lint TOP=core && make test-contracts`
Expected: PASS, zero warnings, contracts green.

- [ ] **Step 6: Commit**

```bash
git add rtl/core/if_stage.v rtl/core/core.v tb/test_if_stage.py \
        docs/contracts/phase1-interfaces.md tb/test_stubs.py
git commit -m "feat(if_stage): select the instruction halfword and report its length"
```

---

## Task 3: decode — expander routing

**Files:**
- Modify: `rtl/core/decode.v`
- Test: `tb/test_decode.py`

**Interfaces:**
- Produces: internal `wire [`p_INSTR_W-1:0] instr_eff`; `function [31:0] rvc_expand(input [15:0] h)`.

- [ ] **Step 1: Replace the "compressed is illegal" test with the routing test**

Delete `test_compressed_encodings_are_illegal`. Add:

```python
@cocotb.test()
async def test_compressed_and_32_bit_words_are_distinguished_by_instr_1_0(dut):
    """instr[1:0] != 2'b11 selects the expander; == 2'b11 selects the decoder."""
    got = await decode(dut, 0x0000_4081)      # c.lw -> a LOAD, not illegal
    assert got["mem_read"] == 1
    got = await decode(dut, 0x00C5_8533)      # add a0,a1,a2
    assert got["alu_op"] == ALU_ADD
```

Update `test_length_gate_is_not_redundant_in_phase_two`: the `not_32bit` gate no longer routes to illegal, so rename it `test_over_32_bit_forms_are_illegal` and keep only the `instr[4:2] == 3'b111` case.

- [ ] **Step 2: Run to verify failure**

Run: `make test MODULE=test_decode TOP=decode`
Expected: FAIL — `0x4081` decodes illegal today.

- [ ] **Step 3: Add the expander and the mux**

In `rtl/core/decode.v`, keep the `instr` input port and add:

```verilog
reg  [`p_INSTR_W-1:0] rvc_expand_word;
wire [`p_INSTR_W-1:0] instr_eff = (instr[1:0] == 2'b11) ? instr : rvc_expand_word;
```

and a function shell:

```verilog
function [`p_INSTR_W-1:0] rvc_expand;
  input [15:0] h;
  begin
    rvc_expand = 32'h0000_0000;   // legal encodings are added by quadrant in T4-T6
  end
endfunction
```

Call it combinationally (`always @(*) rvc_expand_word = rvc_expand(instr[15:0]);`), and rename the decode body's uses of `instr` to `instr_eff`. The routing test above passes only once T4 lands `c.lw`, so land T3 and T4 as one commit, or mark the routing test `@cocotb.test(skip=True)` now and un-skip it in T4.

- [ ] **Step 4: Run and verify**

Run: `make test MODULE=test_decode TOP=decode && make lint TOP=decode`
Expected: PASS once T4 supplies `c.lw`; zero warnings.

- [ ] **Step 5: Commit** (fold into T4 if the routing test is not yet green)

```bash
git add rtl/core/decode.v tb/test_decode.py
git commit -m "feat(decode): route compressed encodings through an expander"
```

---

## Tasks 4-6: decode expansion — one task per quadrant

The three expansion tasks share one shape; only the table and the tests differ.

**Files:** Modify `rtl/core/decode.v`, test in `tb/test_decode.py`.

**Interfaces:** each quadrant is `function [`p_INSTR_W-1:0] rvc_q<n>(input [15:0] h)`, dispatched from `rvc_expand` on `h[1:0]`, returning `32'h0000_0000` for any word that is not a legal encoding of that quadrant (which decodes illegal through the existing path — no separate flag).

**How to write each test:** encode the compressed form with the file's existing field helpers and the RISC-V §16.7 tables, then assert the expanded control fields with a *bare* `await decode(dut, word)` into a dict, or with `await expect_fields(dut, word, note, **{...})`. Wherever the whole bundle is known, prefer `await expect(dut, word, note, **bundle(...))`. For a compressed form that must be illegal, use `await expect_illegal(dut, word, note)` — called bare, it asserts the entire inert bundle.

---

### Task 4: quadrant 0 (`h[1:0] == 2'b00`)

| `h[15:13]` | Encoding | Expands to |
|-----------|----------|-----------|
| `000` | `C.ADDI4SPN` | `addi rd', x2, nzuimm`; `nzuimm == 0` is illegal |
| `010` | `C.LW` | `lw rd', offset(rs1')` |
| `011` | `C.LD` | **illegal in RV32** |
| `110` | `C.SW` | `sw rs2', offset(rs1')` |
| `111` | `C.SD` | **illegal in RV32** |

- [ ] **Step 1: Write the failing tests** — one per encoding above, asserting the *expanded* bundle (`C.ADDI4SPN` → `alu_op == ALU_ADD`, `op2_sel == OP2_IMM`, `rs1_addr == 2`, `imm == nzuimm`; `C.LW` → `mem_read`, `mem_size == MEM_WORD`, `rs1_addr`/`rd_addr`; `C.SW` → `mem_write`, `mem_size == MEM_WORD`, `rs1_addr`/`rs2_addr`), the `nzuimm == 0` illegal case, and the two RV64 forms via `expect_illegal` (Review Focus 4).
- [ ] **Step 2: Run to verify failure** — `make test MODULE=test_decode TOP=decode`.
- [ ] **Step 3: Implement `rvc_q0`** — build the equivalent 32-bit word with the file's own `i_type`/`s_type` layouts and return it.
- [ ] **Step 4: Run to verify pass** — `make test` and `make test-4state`, plus `make lint TOP=decode`.
- [ ] **Step 5: Commit** — `feat(decode): expand the quadrant 0 compressed encodings`.

---

### Task 5: quadrant 1 (`h[1:0] == 2'b01`)

| `h[15:13]` | Encoding | Expands to |
|-----------|----------|-----------|
| `000` | `C.NOP` / `C.ADDI` | `addi rd, rd, nzimm`; `rd==0`, `nzimm==0` is `C.NOP` |
| `001` | `C.JAL` | `jal x1, offset` |
| `010` | `C.LI` | `addi rd, x0, imm` (rd≠0) |
| `011` | `C.LUI` | `lui rd, nzimm` (rd≠0, rd≠2) |
| `011` | `C.ADDI16SP` | `addi x2, x2, nzimm` (rd==2) |
| `100` | `C.SRLI`/`C.SRAI`/`C.ANDI` | `srli`/`srai`/`andi`, selected by `h[11:10]` |
| `101` | `C.J` | `jal x0, offset` |
| `110` | `C.BEQZ` | `beq rs1', x0, offset` |
| `111` | `C.BNEZ` | `bne rs1', x0, offset` |

- [ ] **Step 1: Write the failing tests** — one per encoding, asserting the expanded bundle; plus `C.JAL` → `is_jal`, `rd_addr == 1` (Review Focus 1 depends on this decoding correctly); `C.NOP` → `reg_write == 0`; and a test that the same `C.LUI`/`C.ADDI16SP` funct3 splits on `rd == 2` (`c.addi16sp sp, 16` → `rd_addr == 2`, `rs1_addr == 2`).
- [ ] **Step 2: Run to verify failure**.
- [ ] **Step 3: Implement `rvc_q1`**.
- [ ] **Step 4: Run to verify pass** — `make test`, `make test-4state`, `make lint TOP=decode`.
- [ ] **Step 5: Commit** — `feat(decode): expand the quadrant 1 compressed encodings`.

---

### Task 6: quadrant 2 (`h[1:0] == 2'b10`)

| `h[15:13]` | Encoding | Expands to |
|-----------|----------|-----------|
| `000` | `C.SLLI` | `slli rd, rd, shamt` (rd≠0) |
| `001` | `C.FLDSP` | **illegal** (no `D` in this ISA) |
| `010` | `C.LWSP` | `lw rd, offset(x2)` (rd≠0) |
| `011` | `C.LDSP` | **illegal in RV32** |
| `100` | `C.JR`/`C.MV`/`C.EBREAK`/`C.JALR`/`C.ADD` | selected by `h[12]` and `rs2`, below |
| `101` | `C.FSDSP` | **illegal** |
| `110` | `C.SWSP` | `sw rs2, offset(x2)` |
| `111` | `C.SDSP` | **illegal in RV32** |

The `h[15:13]==100` group: `h[12]==0, rs2==0` → `C.JR rs1` → `jalr x0, 0(rs1)`, and `rs1==0` is reserved and illegal; `h[12]==0, rs2!=0` → `C.MV rd, rs2` → `add rd, x0, rs2`; `h[12]==1, rs2==0, rd==0` → `C.EBREAK` → the `EBREAK` word; `h[12]==1, rs2==0, rd!=0` → `C.JALR rs1` → `jalr x1, 0(rs1)`; `h[12]==1, rs2!=0` → `C.ADD rd, rd, rs2` → `add rd, rd, rs2`.

- [ ] **Step 1: Write the failing tests** — one per encoding. Two vectors whose encodings are already verified against the toolchain and are safe to hard-code as anchors: **`c.jr ra` is `0x8082`** (this is the `ret` the toolchain emits) and **`c.lwsp x5, 4(sp)` is `0x4284`**. Assert `c.jr ra` → `is_jalr == 1`, `rd_addr == 0`, `rs1_addr == 1`; `c.lwsp x5,4(sp)` → `mem_read == 1`, `rs1_addr == 2`, `rd_addr == 5`; `c.jalr ra` → `is_jalr == 1`, `rd_addr == 1`; `c.mv x5, x6` → `alu_op == ALU_ADD`, `rs1_addr == 0`, `rs2_addr == 6`; `c.add x5, x6` → `alu_op == ALU_ADD`, `rs1_addr == 5`, `rs2_addr == 6`; `c.ebreak` → `is_illegal == 1` and `reg_write == 0` (it must not perform an add); `c.jr x0` → illegal; and the four RV64/F/D forms (`C.LDSP`, `C.FLDSP`, `C.FSDSP`, `C.SDSP`) via `expect_illegal` (Review Focus 4).
- [ ] **Step 2: Run to verify failure**.
- [ ] **Step 3: Implement `rvc_q2` and the `h[15:13]==100` group**.
- [ ] **Step 4: Run to verify pass** — `make test`, `make test-4state`, `make lint TOP=decode`.
- [ ] **Step 5: Commit** — `feat(decode): expand the quadrant 2 compressed encodings`.

---

## Task 7: `ex_stage` — 2-byte alignment rule

**Files:**
- Modify: `rtl/core/ex_stage.v`
- Modify: `docs/contracts/phase1-interfaces.md` (the `ex_target_misaligned` description)
- Test: `tb/test_branch.py`

- [ ] **Step 1: Write the failing tests**

Add to `tb/test_branch.py`, driving a JAL whose target has bit 1 set and bit 0 clear, and one with bit 0 set:

```python
async def test_halfword_aligned_target_is_not_misaligned(dut):
    """A target of 0x...2 is 2-byte aligned and must not be flagged."""
    # drive pre-existing helper to present a jal with imm reaching 0x...2
    assert int(dut.ex_target_misaligned.value) == 0


async def test_odd_target_is_misaligned(dut):
    """A target with bit 0 set is not 2-byte aligned."""
    # present a target of 0x...3
    assert int(dut.ex_target_misaligned.value) == 1
```

Use the file's existing redirect-driving helpers rather than new ones.

- [ ] **Step 2: Run to verify failure**

Run: `make test MODULE=test_branch TOP=ex_stage`
Expected: FAIL — the first test fails because bit 1 is the current misalignment bit.

- [ ] **Step 3: Change the bit**

In `rtl/core/ex_stage.v` line 346, change `redirect_pc_r[1]` to `redirect_pc_r[0]`; update the port comment on line 43 from "not 4-byte aligned" to "not 2-byte aligned"; update the contract's `ex_target_misaligned` row the same way.

- [ ] **Step 4: Run to verify pass**

Run: `make test MODULE=test_branch TOP=ex_stage && make lint TOP=ex_stage && make test-contracts`
Expected: PASS, zero warnings.

- [ ] **Step 5: Commit**

```bash
git add rtl/core/ex_stage.v tb/test_branch.py docs/contracts/phase1-interfaces.md
git commit -m "fix(ex_stage): require 2-byte, not 4-byte, target alignment"
```

---

## Task 8: `core` — carry the length and fix the link address

**Files:**
- Modify: `rtl/core/pipeline_regs.vh`
- Modify: `rtl/core/core.v`
- Modify: `docs/contracts/phase1-interfaces.md` (bundle tables)
- Modify: `tb/test_stubs.py` (bundle-layout expectations)
- Test: `tb/test_core.py`

**Interfaces:**
- Consumes: `if_stage.instr_len`.
- Produces: `p_IF_ID__INSTR_LEN`, `p_ID_EX__INSTR_LEN`, `p_EX_MEM__INSTR_LEN` (2 bits each); `wb_value` for `WB_SEL == 2'd2` is `em_pc + em_instr_len`.

- [ ] **Step 1: Append the bundle fields and update the guard**

In `rtl/core/pipeline_regs.vh`, **append after each bundle's `VALID`** (so no frozen offset moves) and bump the bundle width: IF/ID `p_IF_ID__INSTR_LEN_LSB = 98`, `_W = 2`, `p_IF_ID_W = 100`; ID/EX `p_ID_EX__INSTR_LEN_LSB = 171`, `_W = 2`, `p_ID_EX_W = 173`; EX/MEM `p_EX_MEM__INSTR_LEN_LSB = 109`, `_W = 2`, `p_EX_MEM_W = 111`. Update the bundle tables in the contract doc and the layout expectations in `tb/test_stubs.py` (`test_pipeline_bundle_layouts_tile_exactly`). Run `make test-contracts`.

- [ ] **Step 2: Write the failing tests**

Add to `tb/test_core.py`:

```python
@cocotb.test()
async def test_compressed_jal_links_pc_plus_two(dut):
    """Review Focus 1: c.jal at 0x100 leaves PC+2 (0x102) in ra, not PC+4."""
    # c.jal +8 at 0x100 -> target 0x108; run and read x1
    assert <ra after the jump> == 0x102


@cocotb.test()
async def test_32_bit_jal_links_pc_plus_four(dut):
    """The same check for a 32-bit jal: ra is PC+4."""
    assert <ra after the jump> == <pc + 4>
```

Fill the angle-bracketed parts using the file's existing program-loading and register-read helpers.

- [ ] **Step 3: Run to verify failure**

Run: `make test MODULE=test_core TOP=core`
Expected: FAIL — the first test fails because `c.jal` links to PC+4.

- [ ] **Step 4: Wire the length and use it**

In `rtl/core/core.v`: pack `if_instr_len` into `if_id_d[p_IF_ID__INSTR_LEN_LSB +: 2]`; carry it into `id_ex_d[p_ID_EX__INSTR_LEN_LSB +: 2]` and `ex_mem_d[p_EX_MEM__INSTR_LEN_LSB +: 2]`; add `wire [1:0] em_instr_len = ex_mem_q[p_EX_MEM__INSTR_LEN_LSB +: 2];` and change the `wb_value` case `2'd2` from `em_pc + 32'd4` to `em_pc + em_instr_len`.

- [ ] **Step 5: Run to verify pass**

Run: `make test MODULE=test_core TOP=core && make lint TOP=core && make asic-check && make test-contracts`
Expected: PASS, zero warnings, synthesis clean.

- [ ] **Step 6: Commit**

```bash
git add rtl/core/pipeline_regs.vh rtl/core/core.v tb/test_core.py \
        docs/contracts/phase1-interfaces.md tb/test_stubs.py
git commit -m "feat(core): carry the instruction length and use it for the link address"
```

---

## Task 9: Integration — the compiled program runs

**Files:**
- Modify: `tb/test_core.py` (the fetch address masking, if needed)
- Test: `tb/test_core_program.py`

- [ ] **Step 1: Run the whole suite**

Run: `make test && make test-4state && make test-contracts && make area`
Expected: all module suites green, contracts green, area reported.

- [ ] **Step 2: Run the compiled program**

Run: `scripts/build-sw.sh && make test MODULE=test_core_program TOP=core`
Expected: PASS — the program writes `tohost` and the run ends. If it does not, this is a *new* bug, not this task's: find it with the bisect method used earlier (trace the PC, find the first instruction that does not do what its disassembly says) rather than assuming the C work is incomplete.

- [ ] **Step 3: Commit the software scaffolding with the green result**

The software tree (`sw/`, `scripts/build-sw.sh`, `tb/test_core_program.py`, the `tb/test_core.py` Memory additions) has been uncommitted while `test_core_program` was red. Commit it now, with the `MAX_CYCLES` value the run actually needs:

```bash
git add sw scripts/build-sw.sh tb/test_core_program.py tb/test_core.py
git commit -m "test: run a compiled rv32imac program to its tohost write"
```

- [ ] **Step 4: Refresh the area baseline**

Run `make area`, append the new numbers to `docs/area/phase1-area.md`, commit `docs: refresh the phase 1 area baseline for the compressed extension`.

---

## Task 10: Contract and spec closure

**Files:**
- Modify: `docs/contracts/phase1-interfaces.md`
- Modify: `docs/superpowers/specs/2026-10-12-rv32c-compressed-extension-design.md`

- [ ] **Step 1: Confirm the contract is fully current**

Read `docs/contracts/phase1-interfaces.md` end to end. Every port and bundle field added by T1, T2, T7 and T8 must be present, and the `decode` section's statement that compressed encodings are illegal must be gone. `make test-contracts` is the mechanical check; this step is the human one it cannot make.

- [ ] **Step 2: Mark the spec implemented**

Change the spec's **Status** line to "Implemented" and add a one-line pointer to the arch-test task as the outstanding acceptance gate.

- [ ] **Step 3: Commit**

```bash
git add docs/contracts/phase1-interfaces.md \
        docs/superpowers/specs/2026-10-12-rv32c-compressed-extension-design.md
git commit -m "docs: close out the compressed-extension contract"
```
