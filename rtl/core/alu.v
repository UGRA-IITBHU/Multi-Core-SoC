`default_nettype none
// ============================================================================
// alu - 32-bit integer ALU.
//
// Purpose: perform the arithmetic, logic, shift and compare operation selected
// by `decode`, and expose the comparison results branch resolution needs.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   op_a    input  32  first operand, already selected by `ex_stage`
//   op_b    input  32  second operand, already selected by `ex_stage`
//   alu_op  input  4   operation select from `decode`
//   result  output 32  operation result, `p_XLEN` bits
//   zero    output 1   result is zero
//   slt     output 1   signed less-than
//   sltu    output 1   unsigned less-than
//
// Guarantee to `ex_stage`: all four outputs are consistent with each other in
// the same cycle, so branch resolution needs one ALU instance and no second
// comparison pass.  `result` is the operand result only; `ex_stage` owns
// choosing which value is written back.
//
// Note: the `alu_op` encoding is owned jointly by this module and `ex_stage`
// and is not enumerated in the contract, because the two are built by the same
// owner and the encoding is internal to the execute block.
//
// Drop-in replaceable: this file holds the frozen port list and its body.
// Replacing the body must not change the port list and must not require any
// other module to change.
// ============================================================================
`timescale 1ns/1ps

`include "defs.vh"
`include "ctrl_fields.vh"

module alu (
  input  wire [`p_XLEN-1:0]     op_a,
  input  wire [`p_XLEN-1:0]     op_b,
  input  wire [`p_ALU_OP_W-1:0] alu_op,
  output wire [`p_XLEN-1:0]     result,
  output wire                   zero,
  output wire                   slt,
  output wire                   sltu
);

  // --------------------------------------------------------------------------
  // DESIGN NOTE 1 - THE `alu_op` ENCODING, WHICH P2's `decode` MUST MATCH
  //
  // `docs/contracts/phase1-interfaces.md` deliberately leaves the `alu_op`
  // encoding unenumerated: "The `alu_op` encoding is internal to the execute
  // block ... and is therefore not enumerated here."  That makes this file and
  // `decode.v` the only two places it can be written down, and it is written
  // down here as:
  //
  //     4'd0 ALU_ADD    4'd5 ALU_XOR
  //     4'd1 ALU_SUB    4'd6 ALU_SRL
  //     4'd2 ALU_SLL    4'd7 ALU_SRA
  //     4'd3 ALU_SLT    4'd8 ALU_OR
  //     4'd4 ALU_SLTU   4'd9 ALU_AND
  //
  // Ten encodings, which is what RV32I has, in a 4-bit field.  4'd10..4'd15
  // are unused and are produced by no legal encoding; `decode` asserts that its
  // own output is never one of them, and the `default` arm below exists only so
  // an illegal encoding produces a defined value rather than a latch.
  //
  // This is a cross-owner agreement, not a port change, so it needs no contract
  // change - but if the two files ever disagree, one of them has to move.
  // --------------------------------------------------------------------------
  localparam [`p_ALU_OP_W-1:0] ALU_ADD  = 4'd0;
  localparam [`p_ALU_OP_W-1:0] ALU_SUB  = 4'd1;
  localparam [`p_ALU_OP_W-1:0] ALU_SLL  = 4'd2;
  localparam [`p_ALU_OP_W-1:0] ALU_SLT  = 4'd3;
  localparam [`p_ALU_OP_W-1:0] ALU_SLTU = 4'd4;
  localparam [`p_ALU_OP_W-1:0] ALU_XOR  = 4'd5;
  localparam [`p_ALU_OP_W-1:0] ALU_SRL  = 4'd6;
  localparam [`p_ALU_OP_W-1:0] ALU_SRA  = 4'd7;
  localparam [`p_ALU_OP_W-1:0] ALU_OR   = 4'd8;
  localparam [`p_ALU_OP_W-1:0] ALU_AND  = 4'd9;

  // Shift amounts are the low SHIFT_AMT_W bits of op_b, per the RISC-V spec:
  // only shamt[4:0] is used and the upper bits are ignored.  SLLI, SRLI and
  // SRAI all encode their operation in funct7 with shamt[5] always 0, so
  // masking here is what makes a 32-bit shift amount safe.
  localparam integer SHIFT_AMT_W = 5;

  // The instruction size, spelled as a shift of 1 rather than as a sized
  // literal such as 32'd4, because the contract forbids a width written as a
  // literal number outside the shared headers.
  localparam [`p_XLEN-1:0] CONST_ONE = {{(`p_XLEN-1){1'b0}}, 1'b1};

  // --------------------------------------------------------------------------
  // The comparisons.
  //
  // `slt` and `sltu` are computed DIRECTLY from op_a and op_b, never from
  // `result`.  That matters: `decode` asks for `alu_op = ALU_SUB` for every
  // conditional branch (its DESIGN NOTE 3), so on a branch this module's
  // `result` is the difference op_a - op_b, not a comparison bit.  Deriving
  // the comparison from the operands is therefore the only formulation that is
  // correct for the operation actually selected, and it is also correct for
  // `ALU_SLT` / `ALU_SLTU` themselves, where `result` is 0 or 1 and happens to
  // agree.  The cost is that `slt` / `sltu` are live for every operation rather
  // than only for the two that write them into `result`; the contract's promise
  // is that the four outputs are *consistent* in one cycle, not that the unused
  // ones are zero.
  //
  // Signedness is carried by an explicit `wire signed` alias rather than by
  // casting at each use, so the intent is stated once.
  // --------------------------------------------------------------------------
  wire signed [`p_XLEN-1:0] op_a_s = op_a;
  wire signed [`p_XLEN-1:0] op_b_s = op_b;

  wire [`p_XLEN-1:0] shamt = op_b[SHIFT_AMT_W-1:0];

  // The two comparison results, widened to `p_XLEN` once here so that the case
  // below can hand them straight to `result_r`.  A concatenation may not use a
  // macro expression as its width, so the widening is written as a select.
  wire [`p_XLEN-1:0] slt_result  = (op_a_s <  op_b_s) ? CONST_ONE : {`p_XLEN{1'b0}};
  wire [`p_XLEN-1:0] sltu_result = (op_a    <  op_b)   ? CONST_ONE : {`p_XLEN{1'b0}};

  // --------------------------------------------------------------------------
  // The operation.
  //
  // `result_r` is a reg assigned in one `always @(*)` rather than a wire fed by
  // a continuous assign, so that the `default` arm can hold an explicit value:
  // a continuous assign cannot express a case at all without a mux, and this
  // module is only correct if every encoding, including the illegal ones,
  // produces something defined.
  // --------------------------------------------------------------------------
  reg [`p_XLEN-1:0] result_r;

  always @(*) begin
    case (alu_op)
      ALU_ADD  : result_r = op_a + op_b;
      ALU_SUB  : result_r = op_a - op_b;
      ALU_SLL  : result_r = op_a << shamt;
      ALU_SLT  : result_r = slt_result;
      ALU_SLTU : result_r = sltu_result;
      ALU_XOR  : result_r = op_a ^ op_b;
      ALU_SRL  : result_r = op_a >> shamt;
      ALU_SRA  : result_r = op_a_s >>> shamt;
      ALU_OR   : result_r = op_a | op_b;
      ALU_AND  : result_r = op_a & op_b;
      // Unreachable for any legal decode; defined rather than a latch so that
      // an illegal encoding cannot propagate X into `ex_stage`'s address.
      default  : result_r = {`p_XLEN{1'b0}};
    endcase
  end

  assign result = result_r;
  assign zero   = (result_r == {`p_XLEN{1'b0}});
  assign slt    = (op_a_s < op_b_s);
  assign sltu   = (op_a < op_b);

  // --------------------------------------------------------------------------
  // Invariants.  Each assertion is ONE LINE on purpose: scripts/yosys-prep.sh
  // deletes exactly whole-line `assert (...) else $error(...);` statements,
  // because Yosys's parser rejects the action clause.  A wrapped assertion
  // would survive the deletion and fail asic-check, which is loud rather than
  // silent, but it would still fail.
  //
  // These two are properties of the *result*, not restatements of how it was
  // computed, which is what makes them worth having: `SRA` and `SRL` differ by
  // one character in the source and by whether the vacated high bits come back
  // as ones or as zeros, and nothing else in this module distinguishes them.
  // A test that only ever shifted zero would not notice either being wrong.
  //
  // The `$isunknown` guard is not decoration.  `always @(*)` fires once at
  // time zero, when every input is still X, and an immediate assertion whose
  // condition evaluates to X *fails* - so an unguarded assertion in a
  // combinational module reports itself before the testbench has applied any
  // stimulus at all.  Skipping only the undefined case keeps the assertion live
  // for every defined one, which is the whole point of having it.
  // --------------------------------------------------------------------------
  always @(*) begin
    if (!$isunknown({alu_op, op_a, op_b})) begin
      assert (!(alu_op == ALU_SRA) || (result_r[`p_XLEN-1] == op_a[`p_XLEN-1])) else $error("alu: SRA did not preserve the sign bit");
      assert (!(alu_op == ALU_SRL) || (result_r[`p_XLEN-1] == ((shamt == {`p_XLEN{1'b0}}) ? op_a[`p_XLEN-1] : 1'b0))) else $error("alu: SRL filled with sign bits instead of zeros");
    end
  end

endmodule
`default_nettype wire
