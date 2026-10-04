# Single-Core Pipelined RISC-V SoC — Design Spec

**Date:** 2026-10-04
**Status:** Draft for review
**ISA:** RV32IMAC + Zicsr, ilp32 ABI, no `F` extension
**Target OS:** Apache NuttX (RISC-V, M-mode flat / S-mode)
**Endpoint:** Real silicon. FPGA is a confirmatory verification vehicle, not a deliverable.
**Language:** Pure Verilog-2001 (no SystemVerilog)

> **Goal hierarchy.** The deliverable is a pipelined SoC, on fabricated silicon, that boots
> its own image and runs something substantial. The FPGA step exists to confirm the design
> before committing it to a mask; it is not the finish line. Every decision below is
> filtered by §2.4.

---

## 1. Context and Goals

### 1.1 What this is

A single-core, 5-stage in-order pipelined RISC-V SoC, written in pure Verilog-2001,
built incrementally so that every phase is correct in simulation before the next phase
begins. The core targets **RV32IMAC + Zicsr** and boots **Apache NuttX** as a hard
deliverable.

NuttX runs on RISC-V in **M-mode with flat addressing** — no MMU is required, which is
what makes this scope achievable. See §2.3 for why a real Linux kernel is not the target.

### 1.2 Sequence of work

**Silicon is the goal. RTL first, FPGA second, silicon last.**

The FPGA step is **confirmatory**: it de-risks the design before mask commitment. A green
FPGA build is necessary but not sufficient — a taped-out part has stricter requirements
(§6.7): it must come up on power-on without a debugger, survive a real power rail, and fit
a real die area budget.

1. **Phases 0–8 — write and verify the RTL, then boot NuttX.** Simulation is the entire
   feedback loop. Every phase gate is a passing test suite in simulation. No FPGA, no
   board, no device selection is required or assumed anywhere in this span.
2. **Phase 9 — FPGA confirmation.** The device is chosen from area data accumulated during
   phases 0–8, then synthesized, brought up on a board, and required to boot the same
   NuttX image. This **confirms** the design; it does not complete it.
3. **Phase 10 — ASIC physical design. This is the deliverable.** The same portable RTL
   flows through LibreLane / OpenROAD to a signed-off GDSII, then to fabrication.

The FPGA stage exists because sim-versus-hardware divergence must be resolved *before*
mask commitment, and because it keeps the RTL portable. It is a checkpoint, not an
outcome.

### 1.2.1 What "something substantial" means

Vague goals fail, so the silicon is accepted when it:

1. Powers up and **self-boots from serial flash with no debugger attached**.
2. Reaches an interactive shell prompt.
3. Runs **multiple processes with working preemptive scheduling** (timer-driven context
   switches, signals, `pthreads`).
4. Mounts a filesystem and reads and writes real files.
5. Runs a small demonstration application of the team's choosing.

Networking is explicitly excluded (§2.4).

**Synthesis does not require a board.** Vivado synthesis may be run against any target
device at any point to obtain a second utilization and timing opinion without any
hardware. This keeps a synthesis feedback loop available throughout phases 0–8 without
committing to a device or board.

### 1.3 Board and device independence

The design targets **an FPGA generically**, not a specific board or device. Any Xilinx
family is acceptable (7-series, UltraScale+, Zynq). Consequences:

- No board-specific pin names, clock frequencies, or LED polarity appear anywhere in
  `rtl/`.
- Board-specific material lives only in the device wrapper and constraint files, which
  are added in phase 9 and are excluded from ASIC synthesis.
- Cache and memory depths are **parameters**, because BRAM budget varies by an order of
  magnitude across families. No default is committed until phase 9; until then the
  smallest plausible budget is assumed so that the design stays valid on any device.

### 1.4 Success criteria

- The RTL passes the official RISC-V ISA compliance suite, including privileged tests.
- The RTL passes ASIC synthesis from phase 1 onward, continuously.
- **Apache NuttX boots to a shell prompt on the core** — first in simulation, then on
  real hardware, from the same image.
- A bare-metal C program runs correctly in simulation from phase 1 and subsequently
  boots on real hardware over UART.
- The plan is **time-agnostic**: work may stop at any phase gate and leave a working,
  demonstrable project with a green regression suite.

---

## 2. Scope

### 2.1 In scope

**ISA: RV32IMAC + Zicsr.** 32-bit, ilp32 ABI, **no `F` extension.**

- 5-stage in-order pipeline: IF, ID, EX, MEM, WB
- RV32I base integer, RV32M multiply/divide, RV32C compressed
- Full hazard detection and forwarding
- Branch prediction: BTB, 2-bit saturating counter or gshare, RAS
- L1 instruction and data caches, store buffer
- **Complete M-mode and S-mode privileged architecture** — not a subset. This is the
  gating requirement for the OS, see §4.2.
- PMP, trap/exception handling, interrupt controller and timer input
- Debug module interface and JTAG transport
- SoC level: interconnect, CLINT, UART, GPIO, SPI flash, boot ROM, RAM
- AXI4 master port on the core
- **Boot Apache NuttX** on the core, as a hard deliverable (§6.6)

### 2.2 Explicitly deferred (deliberate omissions, not oversights)

| Deferred | Reason | Revisit when |
|---|---|---|
| **MMU / TLB / Sv39** | NuttX runs on RISC-V in **M-mode with flat addressing** — its Kconfig states most RISC-V targets do so, and `ARCH_MMU_TYPE_SV39` defaults to `n`. The MMU is not required by the OS. | Never, unless a Linux kernel becomes a requirement. |
| **PLIC** | Routes interrupts across *multiple* harts. One hart plus CLINT is sufficient for NuttX. | A second core is added. |
| **`F` extension / FP** | Nothing requires FP. Omitted to save area, to avoid a whole pipeline stage, and to avoid IEEE-754 verification effort that exceeds everything else in this design combined. ABI is `ilp32`. If FP is ever needed, `Zfinx` is the far cheaper route. | Software requires FP. |
| **DDR / external DRAM** | A DDR PHY is **licensed analog hard IP** from the foundry. It cannot be synthesized, and open PDKs such as sky130 do not contain one. Incompatible with a self-contained open tape-out flow. Main memory is compiled SRAM instead (§2.4). | Never, under an open flow. |
| **Ethernet / `lwIP` networking** | An Ethernet **PHY** is the same licensed-analog wall as a DDR PHY. No open PDK provides one. | Never, under an open flow. |
| **DMA** | No consumer until a peripheral needs it. | A DMA-capable peripheral exists. |
| **Real Linux kernel** | Would require an MMU, a boot chain (OpenSBI), external DRAM, and ~4 MB of RAM. See §2.3. | Never, unless externally required. |
| **Multi-core** | Out of scope by title. The interconnect is designed multi-master capable so retrofitting is cheap. | Phase 7 completes. |

### 2.3 Real Linux: why not, and what it would cost

Recorded because it was considered and rejected, not overlooked.

A real Linux kernel with `CONFIG_MMU=n` is possible in principle — that is what
uClinux was, before it was merged into mainline as the `NOMMU` option. It is not the
target here for three reasons:

1. **Lineage and maintenance.** The standalone uClinux project is dormant: its site is
   archived and several original architectures were dropped upstream. What remains is
   mainline Linux `NOMMU`, which is heavily exercised on ARM and barely at all on RISC-V.
2. **Memory.** A Linux kernel plus initramfs needs roughly 2–4 MB. NuttX needs under
   500 KB. That difference dictates the device in §8.1, or demands external DRAM — which §2.4 excludes.
3. **Boot chain.** Linux expects OpenSBI or an equivalent M-mode monitor, plus a
   bootloader and filesystem — a separate subsystem that is not in this block list.

NuttX is a live Apache project with broad RISC-V board support, and it provides the
POSIX API, filesystems and a shell that the goal actually requires. **NuttX also satisfies
the RTOS requirement**, since it is a preemptive RTOS with a POSIX subsystem; a second OS
such as FreeRTOS remains a cheap optional demonstration. Networking (`lwIP`) is excluded
for the PHY reason in §2.2.

### 2.4 Silicon-first design rule

**The deliverable is a taped-out part. This is the filter every future decision passes
through.**

> **Rule 1 — Silicon decides.** A feature is in scope only if it can be realized on
> fabricated silicon through a self-contained, open, foundry-independent flow. Anything
> requiring licensed analog PHY IP, or licensed IP of any kind, is out.
>
> **Rule 2 — No FPGA-only justification.** No design decision may be justified solely by
> FPGA convenience. If a choice is convenient on FPGA and wrong on silicon, it is wrong.
> FPGA-specific material is quarantined under `FPGA/` and excluded from the ASIC netlist.
>
> **Rule 3 — Area is a design input, not a postscript.** Die area, I/O pin count and SRAM
> capacity constrain the architecture from the first commit, not after the RTL is written.

Rule 1 is what excludes DDR and Ethernet (§2.2). Rule 2 is what quarantines primitives
(§9.1). Rule 3 is what makes §6.7 a design requirement rather than a later concern.

**What Rule 1 excludes, explicitly.** Any PHY: DDR/LPDDR, Ethernet, USB, SATA, MIPI, HDMI,
SD. All are licensed analog. Consequently the SoC has **no high-speed external interfaces** —
its I/O is UART, SPI NOR flash, GPIO and JTAG only. This is a genuine constraint, accepted
deliberately.

---

## 3. Language and Coding Conventions

### 3.1 Pure Verilog-2001

The RTL is Verilog-2001. This is the maximal common denominator across Vivado, Yosys,
LibreLane, Verilator and Icarus, and it removes packed-struct layout discrepancies
between those tools. Because Yosys is the front end for the ASIC flow, staying in
Verilog removes an entire class of tool-version risk.

### 3.2 Ruleset

Every file:

```verilog
`default_nettype none
// ... module body ...
`default_nettype wire
```

| Use | Never |
|---|---|
| `` `default_nettype none `` in every file | `logic`, `bit`, `byte`, `int` |
| `always @(posedge clk)` / `always @(*)` | `always_ff` / `always_comb` |
| `localparam` for opcodes, states, field offsets | `enum`, `typedef struct` |
| explicit `input` / `output` port lists | `interface`, `modport` |
| immediate assertions: `assert (c) else $error(...)`, `$fatal` | concurrent SVA (`assert property`) |
| `$clog2` (available in Verilog-2001) | — |
| file extension `.v` | — |

### 3.3 Naming conventions

Pure Verilog has no `struct`, so pipeline bundles are flat signals with **stage-boundary
prefixes**. Every signal crossing a stage boundary is named `<from>__<to>__<field>`:

```
if_id__pc       if_id__instr      if_id__valid
id_ex__pc       id_ex__rs1_val    id_ex__op        id_ex__reg_write
ex_mem__alu_out ex_mem__store_data
mem_wb__wb_data mem_wb__reg_write
```

Benefit: greppable, and Verilator `-Wall` flags any signal that does not correspond to a
real port. This replaces much of what the SystemVerilog type system would have caught.

Bundle field offsets live in `rtl/core/pipeline_regs.vh` as `localparam`s so slices are
named rather than magic numbers.

### 3.4 What the loss of concurrent SVA costs, and the mitigation

Immediate assertions are Verilog-2001 and are used directly:

```verilog
always @(posedge clk)
  if (rst_n) assert (!valid_pipe) else $error("valid stuck high during reset");
```

For the "$this implies $past(that)" class of property, `rtl/verify/pipe_checker.v`
implements a checker module holding explicit `prev_*` registers and sampling them. This
is the conventional Verilog-2001 approach and preserves the coverage.

Cocotb carries the heavy lifting, which is the better tool at this scale regardless: in
Python you can assert over a window of cycles, diff the DUT against a reference model,
and produce readable failure output far more cheaply than in Verilog.

---

## 4. Architecture Overview

```
                     ┌──────────────────────────────────────────────┐
   PC ──▶ IF ──▶ ID ──▶ EX ──▶ MEM ──▶ WB ──▶ writeback
         fetch  decode execute l/s     retire
         └────────┴────────┴────────┴──▶ single unified redirect/flush
                                    (branch mispredict, exception, trap,
                                     interrupt — one mechanism)
```

### 4.1 Microarchitecture decisions

| # | Decision | Rationale | Rejected alternative |
|---|---|---|---|
| 1 | Branch resolves in **EX**, predicted in IF | 2-cycle mispredict flush. In a 5-stage in-order core this is the sweet spot. | Resolve in MEM (+1 cycle penalty, no benefit at depth 5) |
| 2 | Multiplier written **behaviorally**, tool maps to DSP48E1 / ASIC array | Portable, fast to simulate, no primitive instantiation | Hand-built DSP array (ASIC-portable later, far more work now) |
| 3 | Divider **iterative, stalls the pipeline** (~34 cycles) | Div is rare in compiled code. Stalling everything keeps forwarding uniform — no special DIV-result bypass. | Background divider + scoreboard (needs a commit slot) |
| 4 | **C extension: always fetch 32 bits, expand in ID, gate on `PC[1]`** | The alternative (fetch 16, discover length, refetch) infects IF and PC logic with variable-length timing bugs. This version is slower but far easier to verify. | True 16-bit fetch with length disambiguation |
| 5 | **One unified redirect mechanism** for branch mispredict, exception, trap, interrupt | Traps redirect from a different stage than branches. Two flush paths bolted together produce a bug class that is miserable to find. Build one path in phase 1; use only the branch arm until phase 3. | Separate flush logic per cause |
| 6 | Regfile writes in **WB**, with WB→ID bypass | Matches the forwarding set. BRAM provides the 2R+1W port shape for free. | Write-first regfile (needs a specific BRAM mode) |
| 7 | **MEM stage exists from phase 1** | Pass-through to simple memory with no cache. Fixing the stage count now prevents later phases renumbering pipeline registers. | Fewer stages until a cache exists |
| 8 | Branch predictor **interface stubbed in phase 1** | IF receives `predict_taken` / `predict_pc`, tied to constants. Phase 5 becomes a drop-in, not a refactor. | Add the interface in phase 5 |

### 4.2 Timing and memory behaviour

- Stalls, never kills, on memory wait. The LSU returns `mem_rsp_valid`; MEM holds the
  stage and propagates a stall upstream. The same plumbing later absorbs cache misses and
  the divider.
- Boot from a BRAM ROM at `0x0000_0000`; the reset vector lives there.
- Forwarding set: EX→EX, MEM→EX, WB→ID. Load-use hazard costs one bubble.

### 4.3 Kernel boot contract (gating requirement for phase 3)

This is the requirement list that decides whether phase 3 is actually complete. A
Linux-family kernel — and NuttX is one — reads and writes a specific set of CSRs and
instructions during early boot. **A missing or incorrect one produces a silent hang, not
an error message**, so these are verified explicitly rather than discovered.

| Requirement | Notes |
|---|---|
| `misa` | Read at boot. Must report the implemented extensions correctly, or userspace and libc misbehave. |
| `satp` | **Must be readable and return a sane value even though there is no MMU.** The kernel reads it unconditionally. A stub that traps or returns X here is a boot failure. |
| `stvec` | Must support **vectored** trap mode; the kernel selects it. Direct mode alone is insufficient. |
| `sepc`, `scause`, `stval`, `sscratch` | Trap entry state. |
| `sstatus`, `sie`, `sip` | Interrupt gating, delegation, and status bits. |
| `medeleg`, `mideleg` | Trap and interrupt delegation to S-mode. |
| `mstatus`, `mie`, `mip` | M-mode equivalents. |
| `mret` / `sret` | Return from traps. |
| `ecall` from S-mode | The syscall path. |
| `mcause`, `mepc`, `mtvec`, `mcounteren` | M-mode trap state and counter access. |
| `time`, `cycle`, `instret` | Read at boot; **must be monotonic**. The kernel's wall clock depends on this. |
| `wfi`, `sfence.vma` | Must **not trap**. Implementations may be no-ops. |
| `mvendorid`, `marchid`, `mimpid` | Read-only; returning zero is correct and expected. |
| Misaligned load/store | Either handled in hardware or delivered as a clean trap. Must be explicit, never undefined. |
| Timer interrupt | CLINT `mtime` plus correct interrupt delivery. **`mtime` frequency must be calibrated** — with no RTC, a wrong tick rate yields a kernel that boots and then slowly dies. |
| `misa` extension gating | CSR read/write behaviour for unimplemented CSRs must be defined, not undefined. |

Phase 3 does not exit until every row above has an explicit, tested behaviour.

---

## 5. Phased Plan

Each phase ends at a **test-based gate**. Stopping at any gate leaves a working project.

**Phases 0–7 are simulation-only.** No FPGA, board, or device selection is assumed. All
gates are passing test suites in simulation. Phase 9 is where hardware enters.

| Phase | Contents | Exit criterion (simulation) |
|---|---|---|
| **0. Harness** | Verilator + cocotb + Yosys working on macOS. Module skeletons, lint clean, `make asic-check` synthesizes, one cocotb test green. A 5-register shift pipeline as a clocking smoke test | Lint clean; Yosys synthesizes; cocotb green |
| **1. Datapath** | PC/next-PC, regfile, RV32I decode, imm-gen, ALU, branch comparator + resolution, hazard detection, forwarding, LSU pass-through | rv32ui subset green; hand-written loop/call tests; lint clean |
| **2. M + C** | Pipelined multiplier, iterative divider, C-extension decode | rv32um + rv32uc green |
| **3. Privileged** | Complete M-mode **and** S-mode: full CSR file, trap/exception logic, delegation, timer counters, PMP, interrupt input | Privileged + PMP **negative** tests; **every row of §4.3** verified; `riscv-arch-test` privileged suite green |
| **4. Memory hierarchy** | LSU/AGU, store buffer, L1 I$, L1 D$ | Cache torture: random access patterns, all replacement paths, vs reference model |
| **5. Branch prediction** | BTB, 2-bit counter or gshare, RAS | **Measured** CPI improvement over phase 4, not an assumed one |
| **6. Debug** | Core debug hooks, Debug Module, JTAG protocol | JTAG protocol and register access verified against a model |
| **7. SoC** | AXI4 master, interconnect, CLINT, UART, GPIO, SPI flash, boot ROM, RAM, self-test ROM | Full SoC; interrupts live; reference software running in simulation |
| **8. NuttX** | NuttX `qemu-rv` board config adapted to this memory map; kernel + `initramfs` + BusyBox-style shell; filesystem | **NuttX boots to a shell prompt under Verilator** — no FPGA involved |
| **9. FPGA confirmation** | Device selection from phase 0–8 area data; Vivado synthesis, place, route, timing closure; device wrapper and constraints; board bring-up | Design fits and meets timing; **the same NuttX image boots on hardware**; self-test passes. Confirms the design; does not complete it (§1.2). |
| **10. Silicon — the deliverable** | OpenRAM SRAM macros; portable RTL through LibreLane / OpenROAD to GDSII; post-layout verification; tape-out | **DRC clean, LVS clean, timing closed, post-layout simulation passes, GDSII released.** §6.7 requirements discharged by analysis and PDK documentation. |

**Why NuttX boots before hardware (phase 8 before 9).** NuttX ships a supported
`qemu-rv` RV32 board configuration against a standard SiFive-style memory map. The
project configures NuttX for that target, then swaps the ROM for this core and SoC under
Verilator. The entire operating-system bring-up therefore happens in simulation on
macOS, with no FPGA, no board and no device selection. This closes most of the
sim-versus-hardware blind spot that phases 0–8 otherwise carry, and it means phase 9
starts with a known-good software image rather than a blank board.

The same NuttX image then runs unchanged on real hardware.

Two checks run at every phase gate during phases 0–9, neither requiring hardware:
`make asic-check` (Yosys, on macOS) and a Vivado synthesis against an arbitrary target
device (on Windows) for a second utilization and timing opinion.

### 5.1 Block-to-phase traceability

Nothing in the original block list is dropped.

| Original block | Phase |
|---|---|
| IF / ID / EX / MEM / WB skeleton | 1 |
| PC + next-PC logic | 1 |
| Instruction decoder (RV32I) / (RV32M, RV32C) | 1 / 2 / 2 |
| Register file (32×32, 2R+1W) | 1 |
| Immediate generator | 1 |
| Hazard detection unit | 1 |
| Forwarding muxes (EX→EX, MEM→EX, WB→ID) | 1 |
| ALU | 1 |
| Branch comparator / resolution logic | 1 |
| Pipelined multiplier | 2 |
| Iterative divider | 2 |
| CSR file | 2 (counters) / 3 (full) |
| L1 I$ | 4 |
| L1 D$ | 4 |
| LSU | 4 |
| AGU | 4 |
| Store buffer | 4 |
| BTB | 5 |
| Branch predictor | 5 |
| RAS | 5 |
| Trap / exception handling | 3 |
| PMP | 3 |
| Interrupt input pins | 3 |
| Debug module interface | 6 |
| AXI4 master port | 7 |
| CLINT, interconnect, UART, SPI flash, boot ROM, RAM | 7 |

### 5.2 Ordering rationale

Cache precedes predictor deliberately: a cache makes the benchmark number meaningful,
and a predictor without a cache optimizes the wrong thing. Once a device is selected in
phase 9, BRAM rather than LUTs is the binding budget line — which is why cache and RAM
depths remain parameters until then.

---

## 6. SoC Level

### 6.1 Memory map

SiFive-FE310-like, so existing RISC-V test environments work unmodified. Locked in
`rtl/common/memmap.vh`.

| Range | Target | Size |
|---|---|---|
| `0x0000_0000` | Boot ROM (BRAM) | 16 KB |
| `0x0200_0000` | Main RAM (BRAM) | 64 KB |
| `0x1000_0000` | UART0 | 4 KB |
| `0x1100_0000` | SPI flash (QSPI) | — |
| `0x1200_0000` | GPIO (LEDs, switches, buttons) | 4 KB |
| `0x2000_0000` | CLINT (`msip`, `mtimecmp`, `mtime`) | 4 KB |

**Addresses are fixed; the sizes below are provisional defaults, not commitments.** They
assume the smallest plausible BRAM budget so the design stays valid on any device. Actual
cache and RAM depths are parameters, chosen in phase 4 and finalized against the device
selected in phase 9. The *address map* never changes — only the depths behind it.

The map is deliberately SiFive-like so that NuttX's `qemu-rv` configuration (§6.6) can be
adapted to it with a constants change rather than a redesign.

**Main memory is compiled SRAM, and it is the binding die-area constraint.** On FPGA main
memory is inferred BRAM; on silicon it becomes an **OpenRAM-generated SRAM macro** (§9.3).
Because no external DRAM is permitted (§2.2), SRAM area comes directly out of the tape-out
budget, and it competes directly with the caches for that budget. RAM depth is therefore
not a free parameter — it must be sized against real OpenRAM output, and it bounds the
NuttX configuration. Working figure: **512 KB main RAM**, which fits a minimal NuttX build
with a small `initramfs` and a filesystem. Drop `lwIP` from any memory estimate (§2.2).

### 6.2 Peripherals

| Peripheral | Phase | Notes |
|---|---|---|
| GPIO | 1 | First peripheral built. The board is alive only when an LED changes. |
| UART | 1 | The only visible output without JTAG. 115200, TX + RX. Non-negotiable. |
| Boot ROM + main RAM | 1 | BRAM arrays behind `rtl/mem/sram_*.v` |
| CLINT | 3 | `msip` for software interrupts, `mtimecmp` for timer. No separate timer. |
| SPI flash reader | 7 | **Also the silicon boot path** (§1.2.1): the part must self-boot from serial flash with no debugger. |
| Debug Module | 6 | Core hooks are portable; the **transport is not** — see §6.7. |
| ~~Ethernet MAC + PHY~~ | **Excluded** | PHY is licensed analog IP (§2.4 Rule 1). |
| ~~DDR / external DRAM~~ | **Excluded** | Same reason. Compiled SRAM instead. |

### 6.3 Bus hierarchy

- **Phases 1–6:** internal `mem_req` / `mem_rsp` — valid/ready, addr, wdata, we, rdata —
  shaped deliberately as an **AXI4-legal subset** so the phase-7 shim is mechanical.
- **Phase 7:** AXI4 master on the core and any DMA-capable path; **AXI4-Lite crossbar** to
  register peripherals; full AXI4 only where bursts are genuinely required. The
  interconnect is **multi-master capable** from the start, so adding a second core later
  is cheap.

### 6.4 Boot flow

Reset → `PC = 0x0000_0000` (boot ROM). Boot ROM is ~50 lines of assembly: set SP, copy
`.data`, zero `.bss`, call `main`. Then jump to the application, or to a monitor once
phase 3 lands.

### 6.5 Hardware watchdog

A counter resets the SoC if `mtime` stops advancing. Without it, a hung program and a
dead board are indistinguishable over UART. This is what makes development on real
hardware tolerable.

### 6.6 Silicon-only requirements

These do not matter on FPGA and matter enormously on silicon. They are in scope from the
start (Rule 3), not deferred to phase 10.

| Requirement | Why it only shows up on silicon |
|---|---|
| **Power-on reset** | A real part must acquire a defined state from an uncontrolled ramp. Needs an explicit POR, not just a reset pin. FPGA BRAM comes up initialized for free; a gate does not. |
| **Reset strategy across power domains** | Reset deassertion must be synchronized per domain, and asserted assertively (§9.2). Brownout behaviour must not leave state undefined. |
| **I/O pin budget** | Every pad costs die area and adds routing. A shuttlestyle die cannot afford many. Keep to UART, a narrow SPI NOR flash bus, a few GPIO, and JTAG. Prefer a narrow boot-flash interface over quad-SPI where the bandwidth allows. |
| **Voltage domains** | Open PDKs do not generally ship low-voltage SRAM. In sky130 the 6T SRAM bitcell is **1.8 V** while low-power logic cells are 0.9 V, so logic and SRAM do not share a domain for free. Either run logic at the SRAM voltage, budget level shifters, or isolate main memory behind its own domain. **Confirm against the PDK and OpenRAM output before committing.** |
| **No internal high-speed oscillator** | Internal oscillators and PLLs consume real area on a shuttle die. Prefer an external clock pin with the simplest possible divider chain. |
| **Self-boot from serial flash** | §1.2.1 item 1. The part must come up unattended, so the boot path is part of the functional spec, not a convenience. |
| **No uninitialized state anywhere** | Every flop and every SRAM word must have defined power-up content, or the part boots nondeterministically. This is stricter than the simulation-side requirement in §7.4. |

**What the FPGA step cannot check.** None of the above. FPGA BRAM powers up initialized,
FPGA I/O is plentiful and cheap, and there is no power rail to misbehave. Phase 9 therefore
confirms *functional* correctness only; the requirements in this table are discharged by
analysis, PDK documentation, and post-layout simulation (phase 10).

### 6.7 NuttX bring-up

The OS target. NuttX is built with its own `configure` / `make` flow and its own board
configuration, not integrated into this repository's `Makefile`.

- **Board configuration.** Start from NuttX's `qemu-rv` RV32 configuration, which targets
  a standard SiFive-style memory map (CLINT, a 16550-style UART, flat RAM). Adapt
  NuttX's `include/board.h` and memory map constants to match §6.1 rather than changing
  §6.1 — the address map stays stable so both bare-metal and OS software can rely on it.
- **Boot modes.** Two images are supported and selected by what the boot ROM finds:
  - **Bare-metal / RTOS**: the small ROM loader described in §6.4.
  - **NuttX**: a kernel image plus a built-in `initramfs`, loaded into RAM. Both are
    binary blobs (`ELF` converted with `objcopy`) and are not committed — `scripts/`
    fetches and builds them.
- **Console.** UART is the kernel console; the bring-up milestone is a shell prompt with
  `uname`, working `ls`, and a `startup` message from the initramfs.
- **Clock.** `mtime` frequency must be configured in NuttX to match the actual core
  clock, and verified — see §4.3.
- **In-simulation first.** The whole bring-up runs under Verilator on macOS before any
  hardware is involved (§5, phase 8).
- **Toolchain.** NuttX requires an RV32 toolchain configured for its own target. `nxstyle`
  formats NuttX sources; it is not applied to this project's RTL.

NuttX is a preemptive RTOS with a POSIX subsystem, so it satisfies both the RTOS and the
Linux-API requirement. A second OS such as FreeRTOS is a cheap optional demonstration
built on the same boot ROM.

---

## 7. Verification

### 7.1 The ladder

Cheap layers run constantly; expensive ones run nightly. Layers 0–6 are the entire
feedback loop for phases 0–8 and require no hardware.

| # | Layer | Tool | Host | Gate |
|---|---|---|---|---|
| 0 | Lint **+ ASIC portability** | Verilator `-Wall --lint-only`; Yosys `synth` | macOS | Every commit. Doubles as the portability check — one command, two jobs. |
| 1 | Module unit tests | cocotb | macOS | Every commit |
| 2 | Directed instruction tests | Hand-written assembly | macOS | Every commit, written test-first |
| 3 | **ISA compliance** | riscv-arch-test + Sail (Docker) | Docker | Per phase — the conformance gate |
| 4 | Golden-model diff | Python RV32IMC model in cocotb | macOS | Every commit |
| 5 | Random / torture streams | Python model | macOS | Nightly |
| 6 | **Formal** | riscv-formal (SymbiYosys, RVFI, immediate assertions) | macOS | Phase 4+ |
| 6b | **Synthesis-only check** | Vivado `synth_design` against an arbitrary target device | Windows | Per phase. Yields utilization and timing without any hardware or board. |
| 7 | Post-synthesis netlist sim | Vivado-exported netlist → same cocotb regression | macOS | Phase 9+, before each FPGA build |
| 8 | On-board self-test | Test ROM → UART PASS/FAIL | board | Phase 9+, after each FPGA build |
| 9 | **OS integration: boot NuttX** | NuttX kernel + initramfs under Verilator | macOS | Phase 8+, every commit after the core boots |
| 10 | **Post-layout simulation** | Gate-level netlist from the final routed DEF, against the same regression and the NuttX image | Linux | **Phase 10 only.** The only check that sees real timing, real fanout and real power-up state. Non-negotiable before release. |

Layers 7 and 8 are where sim-versus-hardware divergence is finally resolved. They are
deferred to phase 9, which is a known and accepted blind spot for phases 0–8 — §7.4
describes the mitigations that stand in for hardware in the meantime.

NuttX is not a self-check — it is an *independent* implementation that only runs if the
core is genuinely correct, which makes layer 9 the strongest single integration test in the
project. A shell prompt over UART means traps, CSRs, interrupts, the timer, caches and the
boot chain all work together.

### 7.2 Two independent oracles

A single golden model is a trap: if written by the same author, it can share a
misreading of the spec, and the bug verifies against itself.

- **Sail** (via riscv-arch-test) is authoritative on *what the ISA requires*. Pass/fail
  only; on failure it reveals almost nothing about where.
- **The Python model** in cocotb answers *where* the divergence occurred, cycle by
  cycle, with readable output.

Sail decides *whether* the design is correct. Python finds out *why*. Python alone never
justifies a compliance claim.

Note: riscv-arch-test's ACT4 branch uses Sail as its golden reference and expects a
`sail-riscv-$(uname)-$arch` binary plus a locally built `riscv-gnu-toolchain`. Prebuilt
Sail binaries for Darwin/arm64 are unlikely, so **this suite runs inside a Linux Docker
container**.

### 7.3 Test-driven development

For each module: write the cocotb test first, watch it fail for the right reason, then
implement. A module is not "done" until a test that would have caught its bug exists.

### 7.4 Hardware-versus-simulation divergence

A design that is fully green in Verilator and dead on the board is the normal failure
mode, not bad luck. Phases 0–7 have no hardware, so these defenses are the only ones
available until phase 9 — the first two are the load-bearing ones during RTL work.

| Cause | Defense | Available in |
|---|---|---|
| X-propagation differences | Verilator is 2-state. Run with **`--x-assign unique --x-initial unique`** so X becomes randomized, surfacing uninitialized state instead of silently reading as 0. Nightly, run the suite under **Icarus** (4-state) to catch real X issues. | 0–7 |
| Uninitialized memories | `$readmemh` behind a `MEM_INIT_FILE` parameter, always pointing at a defined file. Never rely on power-up X. | 0–7 |
| Synthesis differs from RTL intent | **Layer 6b** during phases 0–8 — Vivado synthesis on Windows against an arbitrary device catches synthesis-time failures without hardware. **Layer 7** from phase 9 — export the post-synthesis netlist and run the identical cocotb regression against it, the only way to separate "my RTL is wrong" from "synthesis surprised me." | 0–8 (partial), 9+ (full) |
| Design is correct but board disagrees | **Layer 8** — the self-test ROM runs the phase regression on the board and reports PASS/FAIL over UART. | 8+ |

### 7.5 Coverage

A plain Python coverage tracker, not Verilog functional coverage, keyed on the
dimensions that matter for a core: every opcode executed, every branch direction, every
exception cause, every hazard interlock, every cache state transition, every predictor
outcome. When it reports 0% on BTB aliasing, the untested path is known.

### 7.6 Waveform debugging

`gtkwave` requires `gtk+3` (`brew install --cask gtkwave`). **Surfer**, shipped with the
OSS CAD Suite, is faster and is the default choice.

---

## 8. FPGA Selection and Bring-Up (Phase 9)

### 8.1 Device selection

The device is chosen from data accumulated during phases 0–8, not by guesswork. Inputs:

- **Yosys cell counts and sky130 area estimates per module**, recorded every phase
  (§9.5). This is the primary evidence.
- **Vivado synthesis reports** against candidate devices (layer 6b): LUT, FF, BRAM, DSP
  usage, and achieved Fmax.
- The BRAM budget implied by the cache and RAM parameters, which stay symbolic until now.

Selection criteria: the design fits with meaningful headroom (target ≤ ~70% BRAM, so a
larger cache or a second core remains possible), timing closes at a comfortable target
frequency, and the device is obtainable.

### 8.2 Bring-up ladder

Principle: **never build five things before looking at an LED or a serial port.**

1. Empty top + one blinking LED. Vivado works, board works, JTAG works. **Record the
   build time** — that number governs the iteration loop.
2. Add BRAM ROM + trivial UART TX. Text appears on the serial port. This is the real
   "hello world" gate.
3. Run the self-test ROM: the phase's regression executes on the board and reports
   PASS/FAIL over UART.
4. Run the RISC-V compliance suite on hardware.
5. Run an RTOS with interrupts live.

Steps 3–5 are the resolution of the sim-versus-hardware blind spot carried through
phases 0–8. Expect the first hardware run to find real bugs that no simulation caught;
that is the point of the phase, not a setback.

### 8.3 Board independence rules

These apply from the first line of RTL, not from phase 9 — they are what makes the
phase-8 wrapper trivial.

- `soc_top` exposes **one clock and one reset**. No PLL, no oscillator, no pin, no
  LED polarity anywhere in `rtl/`.
- Clock generation and pin constraints live in the device wrapper under `FPGA/`, added
  in phase 9, and excluded from ASIC synthesis.
- LED polarity, switch polarity and clock frequency are board-level parameters resolved
  in the wrapper.
- Development boards commonly provide a 100 MHz oscillator; the wrapper maps it to
  `soc_top`'s clock. Naming a target frequency explicitly keeps timing analysis
  meaningful and matches what sky130 will do easily at the PD stage.

---

## 9. ASIC Portability Constraints

These constrain how every line is written. They are active from phase 1, not deferred
to the end.

### 9.1 Zero vendor primitives in `rtl/`

Never instantiate `RAMB36E1`, `DSP48E1`, `BUFG`, `MMCME2_BASE`, `IBUF`, `ODDR`. Write
behaviorally and let each tool infer.

The single exception is the device wrapper under `FPGA/`, which may be FPGA-specific and
is **excluded from the ASIC synthesis file list**. This is what keeps `rtl/` portable.

### 9.2 Clock and reset discipline

| Do | Do not |
|---|---|
| Clock enables — `if (en)` inside `always @(posedge clk)` | **Gated clocks** — `assign clk_g = clk & en`. FPGA tools accept it; ASIC gives skew and glitches. This is the primary portability bug. |
| Asynchronous assert, **synchronized deassert** via a 2-flop reset synchronizer | Asynchronous reset released asynchronously |
| Explicit reset on every state element | Relying on `initial` blocks for functional state |
| `MEM_INIT_FILE` parameter for `$readmemh` | `initial` memory init inside `rtl/` |

### 9.3 Technology-dependent blocks behind narrow interfaces

The pattern used by Rocket/Chipyard (`MulDivModule`, `SRAMFile`). Implementations differ
per technology; the pipeline never learns about it.

| Module | FPGA implementation | ASIC implementation |
|---|---|---|
| `rtl/core/muldiv.v` | Behavioral → DSP48E1 | Behavioral → multiplier array, **or** iterative shift-add if area outweighs speed |
| `rtl/mem/sram_*.v` | Inferred BRAM | **OpenRAM-generated SRAM macro** — open source, PDK-aware, keeps the flow self-contained (§2.4 Rule 1) |
| Boot flash interface | SPI NOR flash controller | Same controller; pads and flash device are external to the die |
| `rtl/common/reset_sync.v` | `always @(posedge clk)` + async reset | Identical — portable as-is |
| `FPGA/<device>_wrap.v` | Clock generation, pins | **Excluded from ASIC synthesis** |

Only implementations differ.

### 9.4 Multiplier: a real area trade-off

Decision 2 (behavioral multiplier) is now justified twice. On FPGA, `*` maps to a few
DSP48E1 slices. In sky130, a fully pipelined 32×32 multiplier is genuinely large, and area
may argue for an iterative shift-add implementation instead. That decision belongs in
phase 9, informed by real area numbers — not guessed now, and not constrained by the FPGA
target. Keeping `muldiv` in its own module is what preserves the choice.

### 9.5 Verifying portability cheaply, from day one

No foundry, PDK, or Windows machine is needed to **check** portability. Yosys is the front
end for LibreLane and runs on macOS. Therefore:

- Every phase adds `make lint` (Verilator) and `make asic-check` (Yosys `synth` to a
  generic netlist), both on macOS, both in CI.
- If `asic-check` synthesizes clean from phase 1, the RTL is portable by construction
  rather than by a painful audit at the end.
- **Yosys cell counts and sky130 area estimates are recorded per module per phase.** This
  is the utilization trend line for the whole of phases 0–8 and needs no FPGA or device
  selection. It is what surfaces "this module just tripled in size" early, and it is the
  primary evidence for device selection in phase 9 (§8.1).
- Vivado synthesis against an arbitrary device (layer 6b, on Windows) adds a second
  utilization and timing opinion at each phase gate. Starting in phase 9 this becomes
  LUT/BRAM/DSP area and Fmax on the selected device, which is the PPA story that
  justifies or kills the predictor and the caches.

### 9.6 Downstream ASIC flow

At the PD stage the design flows through **LibreLane** (the successor to OpenLane;
OpenLane 1.0.x is in maintenance mode and explicitly not recommended for new designs) or
chipFoundry's OpenLane 2, both built on **OpenROAD**, with sky130 as the PDK. Note that
the ecosystem currently carries three similar names — LibreLane, OpenLane 2, and the
legacy OpenLane 1.x — and verify which is current before committing.

Real silicon, if that far, is reachable via Tiny Tapeout, which uses this flow and has
enabled thousands of first tape-outs.

---

## 10. Toolchain

### 10.1 macOS — authoring and verification

| Need | Tool | Install |
|---|---|---|
| Simulation | Verilator 5.052 | Already installed |
| Simulation | Icarus Verilog (4-state, nightly) | Already installed |
| Testbenches | cocotb | OSS CAD Suite (`darwin-arm64`) |
| Formal | SymbiYosys + yosys-smtbmc | OSS CAD Suite |
| Synthesis / portability | yosys | OSS CAD Suite |
| Waveforms | Surfer | OSS CAD Suite |
| Bare-metal C compiler | `riscv64-elf-gcc` 16.2.0 | `brew install riscv64-elf-gcc` |
| Compliance suite | riscv-arch-test + Sail | Docker (Linux container) |
| NuttX kernel + apps | NuttX `configure` / `make` with RV32 toolchain | `scripts/fetch-nuttx.sh` |

Fallbacks if a different version is needed: `port install riscv64-none-elf-gcc` (16.1.0),
or the xPack GNU RISC-V Embedded GCC via npm.

**Toolchain flags — the ABI trap.** Homebrew provides upstream GCC 16.2.0 under the
`riscv64-elf-` prefix, whereas RISC-V test environments historically expect
`riscv64-unknown-elf-`. The prefix is cosmetic; the flags are what matter, and they are
encoded in the linker script and Makefile so they are not tribal knowledge:

```
-march=rv32imac_zicsr -mabi=ilp32
```

- **`-mabi=ilp32`, not `ilp32d`.** There is no `F` extension (§2.2), so a hard-float ABI
  would generate FP instructions that trap as illegal. The toolchain **and the libc**
  must both be built without FP. If FP code is ever linked in, the symptom is an
  illegal-instruction trap at runtime, not a build error.
- **`zicsr` is explicit** because newer RISC-V profiles split CSR access out of the base
  `I` extension. Phase 3 and the entire NuttX bring-up depend on this being right from
  day one.

If a test suite misbehaves, check these flags before suspecting the RTL.

**Two toolchains, on purpose.** Bare-metal software (§6.4) uses the Homebrew compiler
directly, with full control over flags. NuttX is built by its own `configure` flow
against its own RV32 toolchain config, because the OS build must be self-consistent.
These are separate and neither substitutes for the other.

### 10.2 Windows — implementation

Vivado, free tier. Because implementation happens on Windows, AMD's 2026.1 restriction
(free tier is Windows-only) has no impact on this project.

Only `.tcl`, `.v` and `.xdc` are committed. Vivado regenerates `.Xil/` and `.runs/` from
the flow script, so no `.xpr` is version-controlled.

### 10.3 Build entry points

| Command | Runs on | Purpose |
|---|---|---|
| `make lint` | macOS | Verilator lint |
| `make asic-check` | macOS | Yosys synthesis — portability gate |
| `make test` | macOS | Full cocotb regression |
| `make formal` | macOS | riscv-formal |
| `make nuttx` | macOS | Configure and build the NuttX kernel + initramfs |
| `make boot-sim` | macOS | Boot the NuttX image on the core under Verilator |
| `make vivado` | Windows | `vivado -mode batch -source FPGA/build.tcl` |

`make boot-sim` is the phase-8 integration test and the single most valuable command in
the project: it exercises the core, caches, privileged architecture, CLINT, UART and boot
chain against real operating-system code, entirely in simulation.

---

## 11. Repository Layout

```
rtl/
  common/         interfaces, types, memmap.vh, reset_sync.v
  core/           pipeline; pure RV32I/M/C; no board, no bus protocol
  mem/            L1 I$, L1 D$, store buffer, sram_* wrappers
  verify/         pipe_checker.v and other checkers
  top/soc_top.v   SoC top; portable
tb/               cocotb testbenches, one directory per module
sw/               C startup, linker scripts, test programs
  linker/
  src/
formal/           SymbiYosys configs, riscv-formal harness
FPGA/             Vivado flow scripts; board-agnostic
constraints/      populated when a board is chosen
scripts/          fetch-tests.sh, elf2hex.py, etc.
docs/
  adr/            architecture decision records
  specs/
```

Structural rules:

- `rtl/core/` knows nothing about the FPGA or the bus protocol. It takes
  `mem_req`/`mem_rsp`. This is what makes phases 1–6 portable and lets the bus be swapped
  in phase 7 without touching the pipeline.
- `rtl/top/soc_top.v` is the only SoC-level file. It contains no board pin names.
- One Vivado entry point: `vivado -mode batch -source FPGA/build.tcl`.
- `.gitattributes` normalizes line endings, since editing happens on macOS and building
  on Windows.
- `docs/adr/` records decisions such as "native bus before AXI" so they are not
  relitigated later.

---

## 12. Open Questions and Deferred Decisions

Recorded so they are not re-litigated mid-implementation.

| Question | Deferred to | Note |
|---|---|---|
| Target FPGA device and board | Phase 9 | Chosen from phase 0–8 area data (§8.1), not guessed |
| Core clock frequency | Phase 9 | 100 MHz is the working assumption |
| Cache associativity, replacement policy, block size, final depths | Phase 4, confirmed 9 | Start direct-mapped and small; measure, then refine and fit to the chosen device |
| 2-bit counter vs gshare | Phase 5 | Start with the 2-bit counter; measure, then consider gshare |
| Pipelined vs iterative multiplier for ASIC | Phase 9 | Requires real area numbers; FPGA implementation is unaffected |
| Divider: add background execution | After phase 2 | Only if profiling justifies it |
| LFU vs LRU replacement | Phase 4+ | |
| **Main SRAM size** vs tape-out die budget | Phase 4, fixed 10 | The single most consequential open decision. Requires real OpenRAM area output, not estimates. |
| **Target shuttle / die size and process** | Phase 10 | Determines the SRAM and I/O ceilings above. |
| **sky130 vs gf180mcu** | Phase 10 | sky130 is denser and faster but needs 1.8 V SRAM and finer voltage margin; gf180mcu is larger and slower but more robust for a first tape-out. |
| Boot flash bus width (narrow SPI vs quad-SPI) | Phase 10 | I/O budget vs boot time. |
| AXI4 verification approach | Phase 7 | AXI4 itself is a free public specification, but mature AXI VIP is licensed. Open VIP is weaker. |

---

## 13. Change Log

| Date | Change |
|---|---|
| 2026-10-04 | Initial draft |
| 2026-10-04 | Reordered to RTL-first. Added layer 6b (Vivado synthesis without hardware) and Yosys area tracking as the device-selection evidence. Made board and device selection fully deferred. |
| 2026-10-04 | **Endpoint restated: real silicon is the deliverable, FPGA is confirmatory.** Added §2.4 silicon-first design rule (3 rules) and §1.2.1 defining "something substantial". **Excluded DDR and Ethernet on licensed-analog-PHY grounds**; networking dropped from phase 8 and memory budgets. Added §6.6 silicon-only requirements (POR, I/O budget, voltage domains, no internal oscillator, self-boot, no uninitialized state). Main memory re-specified as compiled SRAM via OpenRAM, making SRAM area the binding die-area constraint. Added post-layout simulation as verification layer 10. |
| 2026-10-04 | **Operating system target locked to Apache NuttX; ISA locked to RV32IMAC + Zicsr (ilp32, no F).** Added §4.3 kernel boot contract as the phase-3 gating requirement. Added §6.7 NuttX bring-up. Split phases: 8 = NuttX boots under Verilator, 9 = FPGA, 10 = ASIC PD. MMU/TLB, F extension, PLIC and DDR formally deferred (§2.2) with reasons; real Linux documented as considered-and-rejected with its real cost (§2.3). RAM budget raised to >=1 MB for kernel + initramfs. |