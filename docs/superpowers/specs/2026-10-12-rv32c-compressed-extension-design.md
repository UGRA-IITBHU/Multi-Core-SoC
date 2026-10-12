# RV32C Compressed Extension — Design Spec

**Date:** 2026-10-12
**Status:** Draft for review
**Scope:** Add the `C` extension to the five-stage core so the implementation matches the
frozen ISA `rv32imac_zicsr`.
**Parent spec:** `docs/superpowers/specs/2026-10-04-rv32imc-pipeline-soc-design.md`
**Contract amended:** `docs/contracts/phase1-interfaces.md`
**Language:** Pure Verilog-2001

---

## 1. Context

The core was specified as **RV32IMAC + Zicsr** and the software is built with
`-march=rv32imac_zicsr -mabi=ilp32`. The implementation, however, never gained a
compressed-instruction path. `rtl/core/decode.v:126` states the position plainly:

> *A 16-bit (compressed) instruction has `instr[1:0] != 11`... **Neither exists in phase 1**.*

GCC emits compressed encodings by default for `rv32imac`: `ret`, `j`, `li`, `mv`, `addi`,
`lw`, `sw`, and most ABI idioms. Running real compiler output was therefore the first
evidence of the gap. With a normally-compiled program the core falls through the compressed
encodings, walks off the end of `.text` into `.data`, and never reaches its `tohost` write.

Hand-written module tests never exercised this, because every one of them was assembled by
hand into 32-bit encodings.

## 2. Goal and acceptance

**Goal.** The core executes the full RV32C integer compressed set correctly, so that
software compiled at `-march=rv32imac_zicsr` runs unmodified.

**Acceptance criteria:**

1. Every RV32C integer encoding decodes to the same architectural effect as its 32-bit
   equivalent, proven by unit tests on the expansion.
2. `make test MODULE=test_core_program TOP=core` passes: the compiled ISA program reaches
   its `tohost` write. (This is a plausibility check, not proof.)
3. `make test MODULE=test_core` stays 8/8 and `make test` stays green across all modules.
4. The rv32ui and rv32uc suites of riscv-arch-test pass. **This is the real acceptance
   criterion**; it is executed by the following task (Docker-based arch-test harness) and
   is listed here as the gate this work feeds.

## 3. What makes this tractable

Three properties of the architecture keep the change contained:

1. **The ISA aligns instructions to 2 bytes when C is present.** A compressed instruction
   is halfword aligned; a 32-bit instruction is 4-byte aligned *in the base ISA* but, once
   the C extension is enabled, RISC-V allows a 32-bit instruction to begin on **any 16-bit
   boundary**, so it may start at `pc[1]==1` and straddle two 4-byte fetch words. A single
   4-byte-aligned fetch, plus the low PC bit, still selects the instruction and determines
   its length; when the selection is a 32-bit instruction at `pc[1]==1`, the front end
   performs a second read of the next word to obtain the instruction's high half.
2. **The length is decodable at fetch time.** `instr[1:0] != 2'b11` distinguishes compressed
   from 32-bit without any decode-stage information, so the front end needs no feedback path
   from decode to compute the next PC.
3. **Compressed encodings expand to existing operations.** Every RV32C encoding is
   equivalent to an existing 32-bit instruction, so the expansion reuses the whole decode
   and execution path rather than adding a second one.

## 4. Design

### 4.1 Scope of encodings

The complete RV32C integer set is implemented — quadrant 0, 1 and 2:

`C.ADDI4SPN`, `C.LW`, `C.SW`, `C.NOP`, `C.ADDI`, `C.JAL`, `C.LI`, `C.ADDI16SP`, `C.LUI`,
`C.SRLI`, `C.SRAI`, `C.ANDI`, `C.SUB`, `C.XOR`, `C.OR`, `C.AND`, `C.J`, `C.BEQZ`,
`C.BNEZ`, `C.SLLI`, `C.LWSP`, `C.JR`, `C.MV`, `C.EBREAK`, `C.JALR`, `C.ADD`, `C.SWSP`.

The RV64-only forms (`C.LD`, `C.SD`, `C.ADDIW`, `C.LDSP`, `C.SDSP`) are illegal in RV32.
Reserved and invalid encodings set `is_illegal`, exactly as the 32-bit decoder already
does: recognised encodings clear the flag on their way past, and an illegal encoding
produces no writeback and no side effect. Trapping on illegal instructions belongs to
phase 3 and is not added here.

`C.EBREAK` expands to `EBREAK`, which the base decoder already marks illegal, so it
inherits the correct no-side-effect behaviour with no special case.

### 4.2 Front end — variable-length fetch

**`pc_gen`.** The hard-coded `p_PC_STEP` (line 80) is replaced by a `pc_step` input of
width `p_PC_W`:

```
next_pc = redirect_valid ? redirect_pc : pred_taken ? pred_pc : (pc_q + pc_step);
```

The redirect arm is unchanged — redirect targets are absolute and do not depend on the
length of the instruction that raised them.

**`if_stage`.** The fetch returns the 4-byte-aligned word containing `pc`
(`req_addr = {pc[31:2], 2'b00}`), and the stage selects the instruction and its length.
`pc[1]==0` is always complete in one fetch:

| `pc[1]` | selected half | presented `instr` | `instr_len` | fetches |
|---------|---------------|-------------------|-------------|---------|
| 0       | low `!= 2'b11` | `{16'b0, word0[15:0]}` | 2 | 1 |
| 0       | low `== 2'b11` | `word0`          | 4 | 1 |
| 1       | high `!= 2'b11` | `{16'b0, word0[31:16]}` | 2 | 1 |
| 1       | high `== 2'b11` | `{word1[15:0], word0[31:16]}` | 4 | 2 |

When `pc[1]==1` and the fetched word's high half has low two bits `2'b11`, the encoding is
a **32-bit** instruction that began at the halfword offset: its low half is `word0[31:16]`
and its high half is `word1[15:0]` from the next word. That case is legal and the front end
issues a second read (`req_addr = {pc[31:2], 2'b00} + 4`) to obtain `word1`, then presents
the assembled word with `instr_len == 4`. A compressed instruction at `pc[1]==1` is
complete in the high half and needs no second read. Because assembly may span two
responses, the presented `instr` is a registered value, not a combinational slice of
`if_rsp_rdata`.

In every case the presented `instr` carries the encoding to be decoded in its low 16 bits
for compressed forms — the unused half is masked to zero — and the full word for 32-bit
forms, so decode can distinguish them by the same `instr[1:0]` test throughout.

`if_stage` gains an `instr_len` output, carrying the table's fourth column. It is only
meaningful in `ST_HOLD`, which is the one fetch state in which `pc_gen` is not stalled by
`if_req_valid`: that is the cycle the instruction is consumed and the cycle the step is
applied, so the length and the step always refer to the same instruction. Its existing
assertion that the presented instruction is nonzero in `ST_HOLD` must be replaced with a
check against an explicit valid bit: with compressed encodings the unused half is masked
to zero, so a nonzero word is no longer the right invariant.

### 4.3 Pipeline bundles

`pipeline_regs.vh` gains a 3-bit instruction length in three bundles (3 bits, because the
byte value 4 does not fit in 2):
`p_IF_ID__INSTR_LEN`, `p_ID_EX__INSTR_LEN`, `p_EX_MEM__INSTR_LEN`. It is appended after
each bundle's `VALID` field rather than inserted before it, so no existing `LSB` moves and
the packing churn stays local to the new fields. It has exactly one consumer.

### 4.4 Link address

`core.v:598` computes the JAL/JALR link value as `em_pc + 32'd4` under `wb_sel == 2'd2`.
That is correct only for 32-bit instructions; `c.jal` and `c.jalr` link to **PC+2**. It
becomes:

```
2'd2: wb_value = em_pc + em_instr_len;
```

JAL/JALR **targets** are unaffected: they are `id_pc + id_imm` and `id_rs1_data + id_imm`,
which do not involve the instruction length.

### 4.5 Decode — expand, then decode

`decode.v` gains a combinational expander. When `instr[1:0] != 2'b11`, the low 16 bits are
rewritten into the canonical 32-bit equivalent, and the existing 32-bit decode runs
unchanged on the result. This is chosen over decoding compressed forms natively because it
keeps one control-generation path: the compressed forms cannot drift from their 32-bit
equivalents, and each encoding is unit-testable by asserting on its expansion.

Expansion does not alter `id_pc` or `instr_len`; those describe the instruction's position
and size, not its operation.

### 4.6 Misalignment

`ex_stage.v:346` flags a target as misaligned when `redirect_pc_r[1]` is set, which is the
4-byte-alignment rule for a 32-bit-only core. With C, instructions and targets need only
2-byte alignment, so the test becomes `redirect_pc_r[0]`. Legal branch and jump immediates
are multiples of 2 and JALR clears bit 0, so a misaligned target cannot arise from a legal
instruction; the check is retained because it is the invariant a trap would key on.

A 32-bit instruction fetched while `pc[1]==1` is **not** misaligned: the C extension
permits it to start on a halfword boundary, and the front end assembles it from two words
(§4.2). There is no instruction-address-misalignment condition for 32-bit instructions
under RV32C beyond the base requirement that the address be 2-byte aligned, which every
compressed instruction step and every legal branch/jump target already satisfies.

## 5. Interfaces changed

| Artifact | Change |
|----------|--------|
| `rtl/core/pc_gen.v` | add input `pc_step [p_PC_W-1:0]`; drop `p_PC_STEP` |
| `rtl/core/if_stage.v` | add output `instr_len [2:0]`; aligned fetch address; halfword select; second-read assembly of a 32-bit instruction at `pc[1]==1`; registered `instr`; relaxed `ST_HOLD` assertion |
| `rtl/core/pipeline_regs.vh` | add `p_IF_ID__INSTR_LEN`, `p_ID_EX__INSTR_LEN`, `p_EX_MEM__INSTR_LEN` (3 bits each); renumber `LSB`s above them |
| `rtl/core/decode.v` | add the RVC expander ahead of the 32-bit decode; remove the "compressed does not exist" position |
| `rtl/core/ex_stage.v` | target misalignment bit 1 → bit 0 |
| `rtl/core/core.v` | wire `instr_len` through the three bundles; `wb_value` link uses `em_instr_len` |
| `docs/contracts/phase1-interfaces.md` | all of the above |

## 6. Testing

Test-driven: the test for an encoding is written before its expansion.

- **decode** — one test per compressed encoding, asserting the expanded 32-bit fields
  (opcode, `funct3`, `rd`, `rs1`, `rs2`, immediate). Illegal RV64-only and reserved
  encodings assert `is_illegal`.
- **pc_gen** — `pc_step` of 2 and 4 both step correctly; a redirect still outranks the step.
- **if_stage** — halfword selection and length for all three rows of the §4.2 table.
- **ex_stage** — a target with bit 1 set and bit 0 clear is *not* misaligned; bit 0 set is.
- **core** — `test_core` stays 8/8; `test_core_program` reaches `tohost`.
- **arch-test** — rv32ui and rv32uc, via the Docker harness built by the following task.

## 7. Risks and caveats

- This is the largest change to the frozen interface since integration. The bundles and two
  module port lists move; every owner re-reads `phase1-interfaces.md`.
- `test_core_program` passing is a plausibility check only. The program touches a fraction of
  the compressed set, so it can go green while an encoding is still wrong. The arch-test
  suites are the acceptance gate.
- The current hang at `0x45c` is expected to be this same defect; if `test_core_program`
  still fails after the change, that is a distinct bug and is investigated separately rather
  than assumed fixed.

## 8. Out of scope

- Trap and exception handling for illegal instructions (phase 3). Illegal encodings mark
  `is_illegal` and do nothing, as today.
- The `F`/`D` extensions and any compressed floating-point form.
- Performance: the core remains single-issue, one instruction in flight at the front end.
