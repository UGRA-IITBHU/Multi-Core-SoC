`default_nettype none
// ============================================================================
// mem_stage - memory stage, owner of the MEM/WB register.
//
// Purpose: take the single-cycle data-memory response, select the value that
// will be written back, report a misaligned data access, and hold the result
// for the writeback stage.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk             input  1    rising-edge clock
//   rst_n           input  1    active-low synchronous reset
//   stall           input  1    hold the MEM/WB register
//   mem_alu_result  input  32   effective address / ALU result from EX/MEM
//   mem_pc          input  32   PC from EX/MEM, needed for the pc+4 source
//   mem_rsp_rdata   input  32   data returned by `lsu`
//   mem_rd_addr     input  5    destination register index
//   mem_reg_write   input  1    the access writes rd
//   mem_wb_sel      input  2    0 = alu, 1 = mem, 2 = pc+4
//   lsu_data_misaligned input 1  misaligned access, verdict from `lsu`
//   mem_rd_data     output 32   value written back to rd
//   data_misaligned output 1    a misaligned data access reached this stage
//
// Note - naming: the input is named for its source (`lsu_data_misaligned`, the
// same source-naming convention as `mem_rsp_rdata` and as `regfile`'s `wb_*`
// write port) and the output carries the plain condition name, so the two
// are never confused.  Neither is an illegal-instruction condition:
// `decode.is_illegal` is that, and it has a different owner.
//
// Guarantee to `wb_stage` and `forwarding`: `mem_rd_data` is the single
// already-selected writeback value for this instruction, so `wb_stage` needs no
// multiplexer of its own.
//
// Guarantee to `core`: this module REPORTS a misaligned data access, it does not
// gate anything.  `mem_reg_write` is an input here, so this module cannot gate
// it - `core` applies the rule while packing the MEM/WB bundle:
// `mem_wb__reg_write = mem_reg_write && !mem_stage.data_misaligned`.  A
// misaligned access therefore never commits a register write, and the decision
// lives with the module that owns the bundle.
//
// Drop-in replaceable: this file builds and lints from its own source alone.
// Replacing it with another implementation must not change the port list and
// must not require any other module to change.
//
// ============================================================================
// DESIGN NOTE 1 - this module holds the MEM/WB state
// ============================================================================
//
// The contract calls `mem_stage` "owner of the MEM/WB register", and its three
// side inputs - `clk`, `rst_n`, `stall`, with `stall` documented as "hold the
// MEM/WB register" - are only meaningful if it really does hold it.  A purely
// combinational writeback multiplexer would leave all three with nothing to do,
// which is not a thing the frozen port list is likely to have done by accident.
// So the writeback value, the destination index, the write enable and the
// misalignment verdict are registered here, and `core` packs MEM/WB from these
// outputs rather than from a second register of its own - `core` owns the
// bundle, `mem_stage` owns the timing, and the two are not the same job.
//
// The consequence for `core` is worth stating because it is the kind of thing
// that goes wrong as a double register: MEM/WB is *these* four outputs.  There
// is no second copy.  A cycle in which `mem_stage` is stalled therefore holds
// the writeback value, which is what lets a slow memory hold the stage.
//
// `mem_rsp_rdata` is sampled on the edge that ends the access, so the word
// memory returns must be valid in that cycle - which is exactly what
// `mem_rsp_valid` promises.
//
// ============================================================================
// DESIGN NOTE 2 - three writeback sources, and pc+4 is one of them
// ============================================================================
//
// `wb_sel` is 2 bits, not 1, because JAL and JALR write `pc + 4` into `rd` and
// that value is not an ALU result and is not memory data.  A two-way
// ALU-or-memory mux would silently turn every taken jump into a jump into
// garbage, which is why the contract's `wb_sel` has three encodings and why
// `mem_pc` exists as an input:
//
//   0 = alu    `mem_alu_result`   - every ALU result and every effective address
//   1 = mem    `mem_rsp_rdata`    - a load
//   2 = pc+4   `mem_pc + 4`       - the JAL / JALR link register
//
// Selection is `mem`'s case first only so that a `wb_sel` of 3 - which is not
// an encoding - lands on the ALU value instead of on a half-decoded constant.
// A non-memory instruction's ALU result is then the value that reaches writeback
// for `wb_sel` 2 as well, which is harmless: `wb_sel` and `mem_reg_write` come
// from the same decoder and only JAL/JALR ever asks for 2 with a register write.
//
// The addition is 32-bit and wraps, so `mem_pc = 0xFFFF_FFFC` yields
// `mem_rd_data = 0`.  That is the correct RV32 behaviour at the top of the
// address space, and it is asserted rather than left to the arithmetic.
//
// Sub-word loads are forwarded whole: `lsu` has no port to extract a byte or a
// halfword on, and `mem_rd_data` here is a pure `mem_rsp_rdata` for `wb_sel` 1.
// See DESIGN NOTE 4 in `rtl/core/lsu.v`, which reports the contract gap: phase 2
// needs `mem_size` and `mem_unsigned` on *this* module to do the LB/LBU/LH/LHU
// sign- and zero-extension the ISA requires, and neither is in the frozen port
// list.
//
// ============================================================================
// DESIGN NOTE 3 - x0 is discarded here, and again at `wb_stage`
// ============================================================================
//
// The write enable registered here excludes `x0`, so a mis-addressed
// instruction that claims to write `x0` never reaches the writeback port, and a
// `j .` spin loop (`jal x0, 0`) cannot corrupt the ISA by accident.
//
// The exclusion is applied twice on purpose - here and in `wb_stage` - because
// that is what the contract requires and because the two ends fail separately:
// `wb_stage` gates the value it presents, and this module gates what it
// remembers.  `regfile` discards `x0` a third time at the far end, so an index-0
// write cannot reach the array even if two of the three gates were removed.
//
// `wb_addr_q` is the destination index the stage retires.  It has no port of its
// own - the frozen port list gives `mem_stage` a `mem_rd_addr` input and no
// `mem_rd_addr` output, so `core` takes the index for the MEM/WB bundle straight
// from `lsu` - which makes this register the only place the index can be checked
// at all, and it is kept for that reason.  It costs no area: its sole consumer is
// the `== REG_ADDR0` comparison in the self-check below, and once
// scripts/yosys-prep.sh has stripped that assertion the register has no consumer
// left, so synthesis removes it.
//
// Review Focus 3 (plan, Task 3) is enforced here in hardware by the assertion
// at the bottom of this file.
//
// ============================================================================
// DESIGN NOTE 4 - `mem_stage` reports misalignment, it does not gate it
// ============================================================================
//
// `mem_reg_write` is an *input*, and a module cannot gate its own input, so the
// rule `mem_wb__reg_write = mem_reg_write && !data_misaligned` is applied by
// `core` while it packs MEM/WB.  What this module does is make sure the verdict
// it reports belongs to the instruction that is actually leaving the stage,
// which is what registering it buys: the value is held with the writeback value
// and the destination index, so the three cannot drift apart under a stall.
//
// This is why `data_misaligned` is registered rather than passed straight
// through.  A combinational pass-through would let a *later* access's verdict
// reach `wb_stage` for the instruction currently in MEM/WB, and the suppression
// in `core` would then be applied to the wrong instruction.  The misalignment
// and the access it describes have to travel together into MEM/WB.
//
// `lsu` already refuses to perform a misaligned access, so nothing is written to
// memory; this stage's job is only to make sure the register write is dropped
// too, and to carry the verdict forward so phase 3 can turn it into a trap.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

module mem_stage (
  input  wire                     clk,
  input  wire                     rst_n,
  input  wire                     stall,
  input  wire [`p_XLEN-1:0]       mem_alu_result,
  input  wire [`p_PC_W-1:0]       mem_pc,
  input  wire [`p_DATA_W-1:0]     mem_rsp_rdata,
  input  wire [`p_REG_ADDR_W-1:0] mem_rd_addr,
  input  wire                     mem_reg_write,
  input  wire [`p_WB_SEL_W-1:0]   mem_wb_sel,
  input  wire                     lsu_data_misaligned,
  output wire [`p_XLEN-1:0]       mem_rd_data,
  output wire                     data_misaligned
);

  // ------------------------------------------------------------------------
  // Frozen encodings, named so this file can be read against the contract.
  localparam [1:0] WB_SEL_ALU = 2'd0;
  localparam [1:0] WB_SEL_MEM = 2'd1;
  localparam [1:0] WB_SEL_PC4 = 2'd2;

  // x0, declared at the address width rather than as a bare integer, so every
  // comparison against it is width-exact and Verilator's -Wall stays silent.
  localparam [`p_REG_ADDR_W-1:0] REG_ADDR0 = {`p_REG_ADDR_W{1'b0}};

  // ------------------------------------------------------------------------
  // The writeback value for the instruction now in front of us (DESIGN NOTE 2).
  // `mem`'s case is written out rather than collapsed to a default, so all
  // three frozen encodings are named, and so that `wb_sel` of 3 - which is not
  // an encoding - falls on the ALU value instead of on a half-decoded constant.
  reg [`p_XLEN-1:0] wb_value;

  always @* begin
    case (mem_wb_sel)
      WB_SEL_MEM: wb_value = mem_rsp_rdata;
      WB_SEL_PC4: wb_value = mem_pc + 32'd4;
      WB_SEL_ALU: wb_value = mem_alu_result;
      default:    wb_value = mem_alu_result;
    endcase
  end

  // The write enable, with x0 excluded (DESIGN NOTE 3).  `lsu_data_misaligned`
  // is deliberately NOT folded in here: `core` applies that rule while packing
  // MEM/WB, because this module cannot gate its own input (DESIGN NOTE 4).
  wire                wb_enable = mem_reg_write && (mem_rd_addr != REG_ADDR0);

  // ------------------------------------------------------------------------
  // The MEM/WB state (DESIGN NOTE 1).
  reg [`p_XLEN-1:0]       wb_data_q;
  reg [`p_REG_ADDR_W-1:0] wb_addr_q;
  reg                    wb_en_q;
  reg                    misalign_q;

  always @(posedge clk) begin
    if (!rst_n) begin
      // Reset is synchronous and clears all four, so a writeback value read
      // before the first instruction reaches this stage is a defined 0 rather
      // than whatever the flops powered up with.  Verilator's two-state model
      // hides that difference, which is what `make test-4state` exists for.
      wb_data_q   <= {`p_XLEN{1'b0}};
      wb_addr_q   <= {`p_REG_ADDR_W{1'b0}};
      wb_en_q     <= 1'b0;
      misalign_q  <= 1'b0;
    end else if (!stall) begin
      // A held stage must hold everything it knows about the instruction in it,
      // including the misalignment verdict, or the three drift apart and
      // `core`'s suppression lands on the wrong instruction.
      wb_data_q   <= wb_value;
      wb_addr_q   <= mem_rd_addr;
      wb_en_q     <= wb_enable;
      misalign_q  <= lsu_data_misaligned;
    end
  end

  assign mem_rd_data    = wb_data_q;
  assign data_misaligned = misalign_q;

  // ------------------------------------------------------------------------
  // Self-checks.
  //
  // Each assertion is kept on ONE line: scripts/yosys-prep.sh deletes exactly
  // whole-line `assert (...) else $error(...);` statements, so a two-line
  // assertion is not deleted and Yosys then fails on the `else`.  See the same
  // note in regfile.v.
  //
  // `===` against `1'b1` is used for X-safety, and it matters here: an
  // immediate assertion FAILS when its condition is unknown, and `wb_en_q` and
  // `wb_addr_q` are X until the first reset edge has been taken, so a plain
  // `&&` would fire on the very first clock.  Case equality gives a definite
  // answer for an unknown operand, so only a real violation fires.
  //
  // They are clocked rather than combinational for the same reason as in
  // `rtl/core/lsu.v`: a combinational `always @*` assertion can see the design
  // mid-settle, with one continuous assign updated and another still holding
  // last cycle's value, and then fire on a state that never existed.
  always @(posedge clk) begin
    // Review Focus 3, in hardware: the state this stage retires must never be
    // a write to x0, whatever the instruction claimed.  `wb_addr_q` has no port
    // of its own - `core` takes the destination index straight from `lsu` - so
    // this is the only place the index can be checked, which is why the
    // register is kept (DESIGN NOTE 3).
    assert (!((wb_en_q === 1'b1) && (wb_addr_q == REG_ADDR0))) else $error("mem_stage: writeback to x0 is enabled");
    // `pc + 4` is the only source this module computes rather than selects, so
    // it is the only one with an arithmetic corner worth stating: at the top of
    // the address space the link register wraps to 0 instead of growing to 33
    // bits, and RV32 says that is what a jump to the last word does.
    assert (!((mem_wb_sel == WB_SEL_PC4) && (mem_pc === {`p_PC_W{1'b1}}) && ((mem_pc + 32'd4) != {`p_XLEN{1'b0}}))) else $error("mem_stage: pc+4 wrapped past 32 bits at pc=%08x", mem_pc);
  end

endmodule
`default_nettype wire
