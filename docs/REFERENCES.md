# References — ISA specification and datapath diagrams

Reading material for the people building each block. Nothing here is a substitute for
`docs/contracts/phase1-interfaces.md` — that file is authoritative for *our* interfaces. These
are the references for *the RISC-V ISA* and for *how a 5-stage pipeline works in general*.

---

## 1. The RISC-V ISA specification

Free, no registration, no licence click-through. Use these to settle any question about what an
instruction does.

### Primary

| Resource | Use it for |
|---|---|
| **[Volume I: Unprivileged Architecture](https://docs.riscv.org/reference/isa/v20260120/unpriv/unpriv-index.html)** | The main reference — every instruction you implement. Index page listing all 37 chapters. |
| **[ISA manual source and ratified PDFs](https://github.com/riscv/riscv-isa-manual)** | The ratified PDFs, newest at the top of the releases page. |
| **[Specifications portal](https://docs.riscv.org/)** | Privileged spec, platform spec, extension database, and the version selector. |

Links below are pinned to ratified version **20260120** so they stay stable. To read a newer
version, swap `v20260120` in the URL for the version you want — the portal lists the available
ones.

### The chapters you actually need for phase 1

| Chapter | Contents | Who needs it |
|---|---|---|
| [Ch 1 — RV32I base integer ISA](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv32.html) | `LUI`, `AUIPC`, `JAL`, `JALR`, branches, loads/stores, OP-IMM, OP, `FENCE`, `ECALL`, `EBREAK` | **Everyone.** This is the core. |
| [Ch 5 — Zicsr](https://docs.riscv.org/reference/isa/v20260120/unpriv/zicsr.html) | The CSR instructions themselves | Phase 3 |
| [Ch 11 — M extension](https://docs.riscv.org/reference/isa/v20260120/unpriv/m-st-ext.html) | `MUL`, `MULH`, `MULHSU`, `MULHU`, `DIV`, `DIVU`, `REM`, `REMU`, **and their specified corner cases** | P3, and it is the single nastiest corner-case set in the ISA |
| [Ch 27 — C extension](https://docs.riscv.org/reference/isa/v20260120/unpriv/c-st-ext.html) | The 16-bit encodings, including which ones are reserved | Phase 2 |
| [Ch 35 — RV32/64G instruction listing](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv-32-64g.html) | Every `G`-set instruction on one page, with encodings | Useful as a lookup table while decoding |
| [Vol II — Privileged Architecture](https://docs.riscv.org/reference/isa/v20260120/priv/priv-index.html) | Index of the privileged volume | Phase 3 |
| [Vol II Ch 1 — CSR listings](https://docs.riscv.org/reference/isa/v20260120/priv/priv-csrs.html) | Every CSR, its address, and its fields | Phase 3 |
| [Vol II Ch 2 — Machine-level ISA](https://docs.riscv.org/reference/isa/v20260120/priv/machine.html) | `mstatus`, `misa`, `medeleg`, `mideleg`, trap behaviour | Phase 3 |
| [Vol II Ch 11 — Supervisor-level ISA](https://docs.riscv.org/reference/isa/v20260120/priv/supervisor.html) | `sstatus`, `stvec`, `sepc`, `scause`, `satp`, `sret` | Phase 3, and `satp` is why NuttX is reachable without an MMU |

### Two things that catch people out

- **`MUL`/`DIV` corner cases.** The spec defines exact behaviour for divisor zero, signed
  overflow on `INT_MIN / -1`, and signed remainder with a negative dividend. These are specified,
  not left to the implementation. Read that section properly — it is where an "obviously correct"
  divider usually isn't.
- **`Zicsr`.** In the current spec CSR access is a separate extension, so the ISA string is
  `rv32imac_zicsr`, not `rv32imac`. This matters from day one because `misa` and `satp` appear in
  phase 3.

### Executable semantics

Reading prose is slower than running code.

| Resource | Use it for |
|---|---|
| **[riscv-arch-test](https://github.com/riscv/riscv-arch-test)** | The official compliance suite. Every instruction has a test; this is the ground truth our phase-1 gate uses. |
| **[riscv-tests](https://github.com/riscv-software-src/riscv-tests)** | The older, simpler suite. Handy as a first cross-check. |
| **[riscv-opcodes](https://github.com/riscv/riscv-opcodes)** | Machine-readable encoding table. Useful when writing the decoder — settles any bit-field question. |

---

## 2. Datapath and control-signal diagrams

Reference material only — none of these diagrams is *our* design. Ours differs in several
places; §4 lists the differences so nobody copies the wrong thing.

### The most useful one

**[CS 61C (Berkeley) — The RISC-V 5-Stage Pipeline](https://notes.cs61c.org/content/pipeline/five-stage-pipeline/)**

This is the best single reference for this project. It has:

- **Figure 1** — the five-stage datapath with `IF/ID`, `ID/EX`, `EX/MEM`, `MEM/WB` pipeline
  registers drawn in. The register names match ours exactly, which is why our bundles are called
  `if_id__*`, `id_ex__*`, and so on.
- **Figure 4** — the same datapath **annotated with every control signal**, which is what you
  want when working out what `decode` must produce.
- **Figure 6** — datapath and control combined.
- **A table of which control signal is generated in which stage**: `ImmSel` (ID), `BrUn`, `ASel`,
  `BSel`, `ALUSel` (EX), `MemRW` (MEM), `PCSel` (MEM), `WBSel` and `RegWEn` (WB).

That last table is worth internalising, because it explains an otherwise puzzling fact about our
design: `PCSel` is generated in MEM in Berkeley's organisation but our `decode` produces branch
control in ID and `ex_stage` resolves it in EX. We resolve one stage earlier — see §4.

### Also useful

| Resource | What it gives you |
|---|---|
| [Cornell CS 3410 — The 5 Classic CPU Stages](https://www.cs.cornell.edu/courses/cs3410/2025sp/notes/cpu_stages.html) | A single-cycle datapath annotated with the five stages colour-coded. Good for understanding *why* the stages fall where they do. |
| [Cornell CS 3410 — CPU notes (slides)](https://www.cs.cornell.edu/courses/cs3410/2019sp/schedule/slides/06-cpu-notes.pdf) | The same diagram walked through stage by stage. |
| [CUHK CENG3420 Lecture 9 — Pipeline](https://www.cse.cuhk.edu.hk/~byu/CENG3420/2024Spring/slides/Lec09-pipeline.pdf) | A slide deck with the four pipeline registers and their fields drawn explicitly. Slide 13 is the useful one. |
| [Illinois CS 433 — Pipelining appendix](https://courses.grainger.illinois.edu/cs433/fa2022/slides/appendixC-pre-lecture.pdf) | Very clear on hazards specifically: structural, data (RAW/WAR/WAW), control, and the stall-vs-bypass tradeoff. Directly relevant to P5. |
| [EcrioniX — RISC-V from Scratch, day 17](https://ecrionix.org/riscv-from-scratch/day-17-5-stage-pipeline) | A worked Verilog build of the 5-stage pipeline. Useful as a sanity check on structure; note it is plain-Verilog-2005-ish and does not follow our interface rules. |

---

## 3. Where to start, per block

| Person | Read first |
|---|---|
| **P1** Fetch | CS 61C Figure 1, then the ISA's `JAL`/`JALR`/branch entries |
| **P2** Decode | [riscv-opcodes](https://github.com/riscv/riscv-opcodes) alongside the RV32I chapter — decoding is field extraction, and the opcode table settles every question. Then CS 61C Figure 4 for which signals come out of decode. |
| **P3** Execute | RV32I ALU operations, then **the `M` extension corner cases in full**. Then CS 61C on the branch comparator. |
| **P4** Memory | RV32I load/store, paying attention to `LBU`/`LHU`/`SB`/`SH` sign and zero extension — that is what `mem_size` and `mem_unsigned` exist for. |
| **P5** Hazards | Illinois CS 433 on hazards, then CS 61C on forwarding paths. The load-use interlock is the one thing you must get exactly right. |

---

## 4. How our design differs from the diagrams

The diagrams above are generic. Ours deviates deliberately. Knowing the differences prevents
copying the wrong thing.

| Topic | Textbook | Ours | Why |
|---|---|---|---|
| **Branch resolution** | Resolved in **MEM**; `PCSel` is a MEM-stage signal | Resolved in **EX**; `ex_redirect_valid` / `ex_redirect_pc` | In a 5-stage in-order core, resolving in EX costs a 2-cycle flush instead of 3, and the branch outcome arrives a cycle sooner. See spec §4.1 decision 1. |
| **Redirects** | `PCSel` selects between `PC+4` and a branch target | **One** redirect funnel: `redirect_valid` > `pred_taken` > `pc + 4` | Traps and interrupts arrive from a *different stage* than branches. One path means phase 3 adds an arm instead of a second flush mechanism. See spec §4.1 decision 5. |
| **Instruction memory** | Usually a separate IMEM with its own port | Separate **fetch port pair** (`if_req_*` / `if_rsp_*`) alongside the load/store pair | Phase 4 adds separate L1 I$ and D$ needing independent bandwidth. Two ports now avoids splitting the fetch path later. See spec §6.3. |
| **Bundle packing** | Each stage register owns its own fields | `core` owns **all four bundles** and every `valid` bit; stage modules produce values only | Keeps the five blocks independently testable and replaceable. |
| **Register file** | Often a 2R+1W or 3R file | 2R+1W, and **`x0` is discarded at both ends** — write port gated and `x0` hardwired | `addi x0, x0, 1` must not corrupt the ISA. |
| **Load-use interlock** | Commonly one or two stall cycles | **Exactly one** | One is sufficient because `MEM→EX` forwarding covers the rest. See `docs/TEAM.md`. |
| **Operand selects** | `ALUSrc` — a single immediate-select bit | `op1_sel` / `op2_sel` — two independent selects | More general, and it keeps the ALU free of special cases. |
| **Writeback select** | `MemToReg` — one bit choosing ALU or memory | `wb_sel` — an explicit select including **PC+4** | The `JAL`/`JALR` link register is a third source, so a one-bit select is not enough. |
| **FP / M extension** | Usually present | **Not in phase 1** | `M` lands in phase 2. `F` is out entirely — see spec §2.2. |

---

## 5. If something is ambiguous

Order of precedence:

1. **`docs/contracts/phase1-interfaces.md`** — what our interfaces actually are. Always wins
   for our own signal names and widths.
2. **The ISA specification** — what the hardware must do. Wins for instruction semantics.
3. **The design spec** (`docs/superpowers/specs/`) — why we made the architectural choices.
4. **The diagrams in §2** — background only. Never authoritative for us.

If the ISA spec and our contract appear to disagree, the contract does not get to change the
architecture — raise it instead. That is a contract change and needs the integrator, because
four other people are building against the same list.