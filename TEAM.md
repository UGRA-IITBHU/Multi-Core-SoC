# M Extension Implementation — Team Task Division

**Target:** Add RV32M (Multiply/Divide) extension to the RV32IMAC+Zicsr core
**Instructions:** 8 total — MUL, MULH, MULHSU, MULHU, DIV, DIVU, REM, REMU
**Approach:** Single-cycle multiplier, iterative divider (~32 cycles), pipeline-friendly stall/valid interface

---

## Person 1 — ALU Core & Control Fields
**Owner:** @person1
**Files:** `rtl/core/ctrl_fields.vh`, `rtl/core/alu.v`

### Deliverables
1. **`ctrl_fields.vh`** — Extend ALU_OP encoding
   - Widen `p_ALU_OP_W` from 4 → 5 bits
   - Add localparams:
     ```
     ALU_MUL   = 5'd10
     ALU_MULH  = 5'd11
     ALU_MULHSU = 5'd12
     ALU_MULHU = 5'd13
     ALU_DIV   = 5'd14
     ALU_DIVU  = 5'd15
     ALU_REM   = 5'd16
     ALU_REMU  = 5'd17
     ```

2. **`alu.v`** — Implement MUL/DIV unit
   - **Multiplier** (combinational, 1 cycle):
     - 32×32→64 signed/unsigned multiply
     - Output low 32 bits for MUL, high 32 for MULH/MULHU/MULHSU
   - **Divider** (iterative, ~32 cycles):
     - Restoring or non-restoring division algorithm
     - Interface: `div_start`, `div_busy`, `div_done`, `div_quotient`, `div_remainder`
     - Handle DIV/DIVU/REM/REMU
   - **Pipeline interface**:
     - Inputs: `alu_op`, `op_a`, `op_b`, `div_start` (asserted for DIV* ops)
     - Outputs: `result`, `mul_valid`, `div_busy`, `div_done`, `div_quotient`, `div_remainder`
   - **LINT**: Must pass `make lint` with zero warnings

### Acceptance Criteria
- `make test TOP=alu MODULE=test_alu` passes all MUL/DIV tests
- Synthesis reports reasonable area/timing for multiplier
- Divider completes in ≤34 cycles for all inputs

---

## Person 2 — Decode & Instruction Expansion
**Owner:** @person2
**Files:** `rtl/core/decode.v`

### Deliverables
1. **Decode OP_OP arms for M extension** (inside `!not_32bit && !longer_than_32` block)
   - Match `funct7 == 7'b0000001` (0x01) with `funct3` 0x0–0x7
   - Set per-instruction:
     | Instruction | funct3 | alu_op      | uses_rs1 | uses_rs2 | uses_rd | reg_write | wb_sel |
     |-------------|--------|-------------|----------|----------|---------|-----------|--------|
     | MUL         | 0x0    | ALU_MUL     | 1        | 1        | 1       | 1         | WB_ALU |
     | MULH        | 0x1    | ALU_MULH    | 1        | 1        | 1       | 1         | WB_ALU |
     | MULHSU      | 0x2    | ALU_MULHSU  | 1        | 1        | 1       | 1         | WB_ALU |
     | MULHU       | 0x3    | ALU_MULHU   | 1        | 1        | 1       | 1         | WB_ALU |
     | DIV         | 0x4    | ALU_DIV     | 1        | 1        | 1       | 1         | WB_ALU |
     | DIVU        | 0x5    | ALU_DIVU    | 1        | 1        | 1       | 1         | WB_ALU |
     | REM         | 0x6    | ALU_REM     | 1        | 1        | 1       | 1         | WB_ALU |
     | REMU        | 0x7    | ALU_REMU    | 1        | 1        | 1       | 1         | WB_ALU |

2. **No compressed forms** — M extension has no C-encodings in RV32

### Acceptance Criteria
- `make test TOP=decode MODULE=test_decode` passes all 8 new decode tests
- `make lint` clean

---

## Person 3 — EX Stage & Hazard Unit (Pipeline Control)
**Owner:** @person3
**Files:** `rtl/core/ex_stage.v`, `rtl/core/hazard_unit.v`

### Deliverables
1. **`ex_stage.v`** — Multi-cycle MUL/DIV handling
   - Accept ALU's `div_busy` / `div_done` / `mul_valid`
   - When `div_busy`: hold `ex_valid`, stall pipeline (drive `ex_stall=1`)
   - MUL: result available same cycle (`mul_valid` combinational)
   - DIV: result available when `div_done` asserted
   - Pass through `ex_alu_result` for MUL; hold for DIV until done
   - Maintain `ex_redirect_valid/pc` logic unchanged

2. **`hazard_unit.v`** — M extension RAW hazards
   - Detect: EX has pending MUL/DIV (div_busy or mul_valid pending) AND ID needs rd
   - Stall ID stage (like load-use hazard but for multi-cycle ALU ops)
   - Track `ex_muldiv_valid`, `ex_muldiv_rd` from EX stage
   - Forwarding bypass for MUL (EX→EX) and DIV (MEM→EX when done)

### Acceptance Criteria
- `make test TOP=ex_stage MODULE=test_branch` passes
- `make test TOP=hazard_unit MODULE=test_hazard_unit` passes new M hazard tests
- No deadlock: DIV followed by dependent instruction stalls correctly then proceeds

---

## Person 4 — Forwarding & Core Integration
**Owner:** @person4
**Files:** `rtl/core/forwarding.v`, `rtl/core/core.v`, `rtl/core/pipeline_regs.vh` (if needed)

### Deliverables
1. **`forwarding.v`** — M result forwarding
   - Add `ex_muldiv_valid`, `ex_muldiv_rd`, `ex_muldiv_result` from EX stage
   - Add `mem_muldiv_valid`, `mem_muldiv_rd`, `mem_muldiv_result` from MEM stage
   - Forward MUL result from EX (combinational, same cycle)
   - Forward DIV result from MEM (when `div_done` in prior cycle)
   - Priority: MUL/DIV forward > ALU forward > MEM forward > WB forward

2. **`core.v`** — Top-level wiring
   - Connect ALU `div_busy`/`div_done` → EX stage
   - Connect EX `ex_stall` → `pc_gen.stall` and IF/ID hold
   - Wire forwarding MUL/DIV signals through pipeline regs
   - Ensure `pipeline_regs.vh` has space for muldiv fields if needed

3. **Pipeline register updates** (if needed)
   - Add `muldiv_valid`, `muldiv_rd`, `muldiv_result` to ID/EX, EX/MEM bundles

### Acceptance Criteria
- `make test TOP=forwarding MODULE=test_forwarding` passes
- `make test TOP=core MODULE=test_core` passes all integration tests
- `make test TOP=core MODULE=test_core_program` passes with M instructions in program

---

## Person 5 — Test Suite (All Tests)
**Owner:** @person5
**Files:** `tb/test_alu.py`, `tb/test_decode.py`, `tb/test_hazard_unit.py`, `tb/test_core.py`, `tb/test_core_program.py`

### Deliverables
1. **`test_alu.py`** — ALU MUL/DIV exhaustive tests
   - MUL: corner cases (0, -1, max, min, sign combinations)
   - MULH/MULHU/MULHSU: verify high 32 bits against reference model
   - DIV/DIVU: divide by 0 (defined behavior: all 1s), divide by 1, max/min
   - REM/REMU: remainder properties (a = (a/b)*b + a%b)
   - Multi-cycle divider timing: verify div_busy/div_done sequence

2. **`test_decode.py`** — Decode tests for 8 M instructions
   - Verify all control signals for each (uses_rs1/rs2/rd, reg_write, wb_sel, alu_op)
   - Verify funct7=0x01 with funct3=0..7 maps correctly
   - Verify illegal funct7/funct3 combinations still mark illegal

3. **`test_hazard_unit.py`** — M extension hazard tests
   - RAW: MUL/DIV in EX, dependent instruction in ID → stall 1 cycle (MUL) or N cycles (DIV)
   - Forwarding: MUL result forwarded EX→EX, DIV result MEM→EX
   - No hazard when rd=x0
   - Mixed with load-use hazards

4. **`test_core.py`** — Integration tests
   - Simple MUL/DIV sequences with dependencies
   - Back-to-back MULs, DIVs, mixed
   - Branch after MUL/DIV

5. **`test_core_program.py`** — Update `isa_test.S` / `main.c`
   - Add M extension test group to `main.c`
   - Verify program still reaches `tohost` with success

### Acceptance Criteria
- All test modules pass: `make test` (all TOPs) → 0 failures
- Code coverage: M instructions exercised in simulation

---

## Coordination Protocol

### Interface Contracts (agree before coding)
| Signal | Owner | Consumers |
|--------|-------|-----------|
| `p_ALU_OP_W`, new ALU_* localparams | P1 | P2, P3, P4 |
| ALU `div_busy`, `div_done`, `mul_valid` | P1 | P3, P4 |
| EX `ex_stall`, `ex_muldiv_*` | P3 | P1, P4 |
| Hazard `id_stall` for muldiv | P3 | P4 |
| Forward `ex_muldiv_*`, `mem_muldiv_*` | P4 | P3 |

### Sync Points
1. **Day 0**: Agree on ALU interface (signals, timing) — P1 publishes, P3/P4 review
2. **Day 1**: P1 delivers ALU stub with interface; P2/P3/P4 start against stub
3. **Day 2**: P1 delivers working multiplier; P3 integrates EX stall logic
4. **Day 3**: P1 delivers working divider; P3/P4 complete pipeline integration
5. **Day 4**: P5 writes tests against running implementation; all integrate
6. **Day 5**: Full regression (`make test`), lint, synthesis check

### Branch Strategy
- Each person works on `feature/m-ext-<name>` branch
- Daily rebase onto `main` (which has only I+C)
- PRs merged in order: P1 → P2 → P3 → P4 → P5 (tests last)
- `main` must stay green at all times

---

## Definition of Done
- [ ] All 289 existing tests still pass
- [ ] New tests: ≥40 test cases covering all 8 M instructions
- [ ] `make lint` clean
- [ ] `make test` (all modules) 100% pass
- [ ] `test_core_program` passes with M instructions in the binary
- [ ] Synthesis runs without error (Yosys + Verilator)
- [ ] Area/timing reported for multiplier and divider

---

## References
- RISC-V Spec Vol. 1, Ch. 7 (M Extension)
- `docs/superpowers/specs/2026-10-12-rv32c-compressed-extension-design.md` §4.1
- `docs/contracts/phase1-interfaces.md` — pipeline register layouts
- `rtl/core/alu.v:54-77` — current ALU_OP encoding
- `rtl/core/decode.v:580-650` — OP_OP decode pattern to follow