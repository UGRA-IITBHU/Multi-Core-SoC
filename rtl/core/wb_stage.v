`default_nettype none
// ============================================================================
// wb_stage - writeback stage: register write port and WB-stage forwarding
// source.
//
// Purpose: present the writeback value to `regfile` and publish the youngest
// architectural result so `forwarding` can select it with the highest priority.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   mem_rd_data     input  32  writeback value from `mem_stage`
//   mem_rd_addr     input  5   destination register index
//   mem_reg_write   input  1   the instruction writes rd, already gated by
//                               `core` on data misalignment
//   data_misaligned input  1   a misaligned data access reached the memory stage
//   wb_we           output 1   commit the register write this cycle
//   wb_wdata        output 32  data to write
//   wb_waddr        output 5   register to write
//   fwd_rd_addr     output 5   destination of the WB-stage forwarding value
//   fwd_rd_data     output 32  WB-stage forwarding value
//   fwd_reg_write   output 1   WB-stage forwarding value is valid
//
// Guarantee to `regfile` and `forwarding`: `wb_we` is the single write enable
// for the whole pipeline and is low whenever `mem_reg_write` is low or whenever
// `mem_rd_addr` is `x0`, so writes to `x0` are discarded.  `fwd_reg_write`
// carries that same `x0` exclusion, so `forwarding` can never forward `x0` as an
// architectural value; the register file discards `x0` writes independently, so
// the discard is enforced at both ends of the writeback path.
//
// The data-misalignment case needs no gate here: `core` has already folded it
// into `mem_reg_write` while packing the MEM/WB bundle, so
// `wb_we = mem_reg_write && (mem_rd_addr != x0)` and nothing more.  A module
// cannot gate its own input, which is why that rule lives in `core`.
//
// Note: this module is purely combinational in phase 1; the MEM/WB pipeline
// register lives in `mem_stage`, which owns the memory stage timing.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
//
// ============================================================================
// DESIGN NOTE 1 - the whole stage is one two-input gate
// ============================================================================
//
// Everything here is a rename of `mem_stage`'s output plus the `x0` exclusion,
// and that is not an under-implementation, it is the contract:
//
//   * `mem_rd_data` is *already* the selected writeback value - ALU, load data
//     or `pc + 4` - because `mem_stage` owns the writeback multiplexer.  Putting
//     a second mux here would give two owners of one decision, and the two
//     would eventually disagree about `pc + 4`, the case a one-bit `MemToReg`
//     select cannot express at all.
//   * `wb_we` is `wb_waddr != x0 && mem_reg_write`, and the destination and the
//     value it goes with are the same two signals `core` already carries in the
//     MEM/WB bundle.  There is no mux left to build.
//
// The module is combinational because in phase 1 the memory stage is a
// single-cycle pass-through: there is nothing for writeback to wait for.  Phase 4
// adds L1 D$ hits, and a cache that can miss needs a WB-side stall, which is the
// `wb_stall` the contract lists under *Known future contract changes*.  Building
// it now would mean building the stall the contract deliberately does not have.
//
// ============================================================================
// DESIGN NOTE 2 - `x0` is excluded here and again at the far end
// ============================================================================
//
// `wb_we` and `fwd_reg_write` are the *same* term, not two similar ones:
//
//   assign wb_we         = mem_reg_write && !rd_is_x0;
//   assign fwd_reg_write = wb_we;
//
// They must be, and the reason is structural.  `forwarding` uses
// `fwd_reg_write` to decide whether `fwd_rd_data` is a value the pipeline just
// produced.  If the two enables could differ, an excluded write to `x0` could
// still be forwarded as if it were architectural, and a dependent instruction
// would then read `x0`'s forwarded garbage instead of its own register value.
// Tying them to one expression makes that divergence impossible rather than
// merely unlikely.
//
// Review Focus 3 (plan, Task 3) is enforced here in hardware by the assertion at
// the bottom of this file, and independently at `mem_stage`, and independently
// again at `regfile`'s write port.  Three gates on the same rule at three ends of
// the path is deliberate: `addi x0, x0, 1` must not be able to corrupt the ISA,
// and each gate fails differently if the other two are removed.
//
// ============================================================================
// DESIGN NOTE 3 - `data_misaligned` is checked here, not gated here
// ============================================================================
//
// The frozen port list gives this module a `data_misaligned` input, and the
// contract is explicit that the gate must NOT be applied in this module:
//
//   `wb_we = mem_reg_write && (mem_rd_addr != x0)` and nothing more,
//   because `core` has already folded the misalignment into `mem_reg_write`
//   while packing MEM/WB.
//
// A dead port cannot be left behind either - `make lint` runs -Wall and an
// UNUSEDSIGNAL is a hard failure - so the port is read by the assertion below.
// That is the better of the two available uses, for a mechanical reason: gating
// `wb_we` with `!data_misaligned` here would be redundant *and* would hide a
// wiring error, because the two would then agree whether or not `core` had done
// its job.  As an assertion it is the opposite - it is high exactly when `core`
// has not done its job, and it names the signal that is wrong.
//
// So the port is a consistency check on `core`'s wiring, and the behaviour
// required by the contract is unchanged: `wb_we` is `mem_reg_write` with `x0`
// excluded, and nothing else.  If that assertion ever fires in an integrated
// core, the fix is in `core`:
//
//     mem_wb__reg_write = mem_reg_write && !mem_stage.data_misaligned
//
// Deleting the port instead is the other option and is a contract change, so it
// is the integrator's decision, not this module's.  See REPORT below.
//
// ============================================================================
// DESIGN NOTE 4 - `fwd_rd_data` is the writeback value, unmodified
// ============================================================================
//
// `forwarding` must publish the *youngest* architectural value in the pipeline,
// and the value about to be written to the register file is exactly that.  So
// `fwd_rd_data` is `mem_rd_data` with no transformation of any kind - no
// sub-word extraction, no truncation.  Sub-word extension belongs to
// `mem_stage`, which owns `mem_rd_data` (see DESIGN NOTE 2 in `rtl/core/lsu.v`
// for the contract gap this leaves in phase 1), and by the time a value reaches
// this module it is already the value `rd` is going to hold.
//
// REPORTED TO THE INTEGRATOR (contract changes are not mine to make):
//
//   1. `wb_stage.data_misaligned` has no consumer by design.  It is read here by
//      a self-check on `core`'s wiring rather than left dead; delete the port if
//      the assertion is not wanted, and the assertion goes with it.
//   2. `lsu.ex_mem_unsigned` has no producer - the frozen EX/MEM bundle has no
//      `mem_unsigned` field - and phase 2 needs both `mem_unsigned` and
//      `mem_size` on `mem_stage` for LB/LBU/LH/LHU.  See DESIGN NOTE 4 in
//      `rtl/core/lsu.v`.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"

module wb_stage (
  input  wire [`p_XLEN-1:0]       mem_rd_data,
  input  wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  input  wire                     mem_reg_write,
  input  wire                     data_misaligned,
  output wire                     wb_we,
  output wire [`p_XLEN-1:0]       wb_wdata,
  output wire [`p_REG_ADDR_W-1:0] wb_waddr,
  output wire [`p_REG_ADDR_W-1:0] fwd_rd_addr,
  output wire [`p_XLEN-1:0]       fwd_rd_data,
  output wire                     fwd_reg_write
);

  // x0, declared at the address width rather than as a bare integer, so every
  // comparison against it is width-exact and Verilator's -Wall stays silent.
  localparam [`p_REG_ADDR_W-1:0] REG_ADDR0 = {`p_REG_ADDR_W{1'b0}};

  // ------------------------------------------------------------------------
  // The register write port (DESIGN NOTE 1 and 2).
  //
  // `data_misaligned` is deliberately absent from this expression: `core` has
  // already folded it into `mem_reg_write`.  See DESIGN NOTE 3.
  //
  // Everything is computed in ONE `always @*` block and asserted inside it,
  // rather than in a chain of continuous assigns with the assertions after them.
  // That is the pattern `rtl/core/decode.v` uses and it is load-bearing here:
  // when a testbench changes several inputs at once, separate continuous
  // assigns settle over more than one delta, so a combinational assertion
  // comparing a freshly updated output with a not-yet-updated one fires on a
  // state the hardware never had.  Inside one block, all of these are updated
  // before any of them is read.
  reg                     rd_is_x0_r;
  reg                     wb_we_r;
  reg [`p_XLEN-1:0]       wb_wdata_r;
  reg [`p_REG_ADDR_W-1:0] wb_waddr_r;
  reg [`p_REG_ADDR_W-1:0] fwd_rd_addr_r;
  reg [`p_XLEN-1:0]       fwd_rd_data_r;
  reg                     fwd_reg_write_r;

  always @* begin
    rd_is_x0_r      = (mem_rd_addr == REG_ADDR0);
    wb_we_r         = mem_reg_write && !rd_is_x0_r;
    wb_wdata_r      = mem_rd_data;
    wb_waddr_r      = mem_rd_addr;
    fwd_rd_addr_r   = mem_rd_addr;
    fwd_rd_data_r   = mem_rd_data;
    // The same term as `wb_we_r`, from the same expression - see DESIGN NOTE 2
    // for why these two can never be allowed to differ.
    fwd_reg_write_r = wb_we_r;

    // ----------------------------------------------------------------------
    // Self-checks.
    //
    // There are no clocks in this module, so these are combinational; the block
    // structure above is what makes them safe to write at all.
    //
    // `===` against `1'b1` is used for X-safety: an immediate assertion FAILS
    // when its condition is unknown, not only when it is false, and at time 0
    // every input here is still X.  Case equality gives a definite answer for an
    // unknown operand, so only a real violation fires.
    //
    // Each assertion is on ONE line: scripts/yosys-prep.sh deletes exactly
    // whole-line `assert (...) else $error(...);` statements, and a two-line
    // assertion is not one, so Yosys then fails on the `else`.  See the same
    // note in regfile.v.
    //
    // Review Focus 3, in hardware: nothing that writes `x0` leaves this stage,
    // and `x0` is never published as a forwarding value either.
    assert (!((rd_is_x0_r === 1'b1) && (wb_we_r === 1'b1))) else $error("wb_stage: x0 was given a write enable");
    // The value and the destination belong to the same instruction: a write
    // enable with a destination the MEM/WB bundle did not carry would commit a
    // value to an unintended register, so it is stated explicitly.
    assert (!((wb_we_r === 1'b1) && (wb_waddr_r !== mem_rd_addr))) else $error("wb_stage: the write destination is not the MEM/WB destination");
    // The forwarding source is the writeback value itself, unmodified, and the
    // same destination - otherwise `forwarding` would publish a value the
    // register file will not take (DESIGN NOTE 4).
    assert (!((fwd_reg_write_r === 1'b1) && ((fwd_rd_data_r !== wb_wdata_r) || (fwd_rd_addr_r !== wb_waddr_r)))) else $error("wb_stage: the forwarding source is not the writeback source");
    // `core` owns the misalignment gate.  This fires exactly when it has not
    // been applied, and names the signal that is wrong - see DESIGN NOTE 3.
    assert (!((data_misaligned === 1'b1) && (mem_reg_write === 1'b1))) else $error("wb_stage: a misaligned access arrived with mem_reg_write high; core must apply mem_wb__reg_write = mem_reg_write && !mem_stage.data_misaligned");
  end

  assign wb_we        = wb_we_r;
  assign wb_wdata     = wb_wdata_r;
  assign wb_waddr     = wb_waddr_r;
  assign fwd_rd_addr  = fwd_rd_addr_r;
  assign fwd_rd_data  = fwd_rd_data_r;
  assign fwd_reg_write = fwd_reg_write_r;

endmodule
`default_nettype wire
