`default_nettype none
`timescale 1ns/1ps
`include "defs.vh"
`include "ctrl_fields.vh"

// ============================================================================
// core - top level of the RV32IMAC 5-stage pipelined SoC.
//
// Purpose: instantiate and connect the whole pipeline, own the four pipeline
// registers, and expose both memory port pairs to the outside world.
//
// Ports (frozen; see docs/contracts/phase1-interfaces.md):
//   clk            input  1   rising-edge clock
//   rst_n          input  1   active-low reset
//   if_rsp_rdata   input  32  instruction returned by fetch memory
//   if_rsp_valid   input  1   fetch memory has returned an instruction
//   mem_rsp_rdata  input  32  load data returned by data memory
//   mem_rsp_valid  input  1   data memory has returned its data
//   if_req_valid   output 1   instruction fetch request
//   if_req_addr    output 32  instruction fetch address
//   mem_req_valid  output 1   load/store request
//   mem_req_addr   output 32  load/store address
//   mem_req_wdata  output 32  store data
//   mem_req_we     output 1   write enable
//   mem_req_wstrb  output 4   byte enables, one per byte lane
//   stage_valid    output 4   {mem_wb, ex_mem, id_ex, if_id} - verification
//                         observability, so "no stage is valid after reset"
//                         is testable without hierarchical references
//
// DROP-IN REPLACEABLE: this is the integrator's module. Every block below has
// a frozen port list and can be rewritten without touching the others.
//
// Bundle packing lives here and nowhere else: stage modules produce discrete
// values on their own ports, and `core` assembles the if_id__*, id_ex__*,
// ex_mem__* and mem_wb__* registers using the offsets in pipeline_regs.vh. The
// offsets are localparam (IEEE 1364-2005 makes localparam module-scope), which
// is why that header is included inside this module.
// ============================================================================
/* verilator lint_off UNUSEDPARAM */
`include "pipeline_regs.vh"
/* verilator lint_on UNUSEDPARAM */

module core (
  input  wire                  clk,
  input  wire                  rst_n,
  input  wire [`p_INSTR_W-1:0] if_rsp_rdata,
  input  wire                  if_rsp_valid,
  input  wire [`p_DATA_W-1:0]  mem_rsp_rdata,
  input  wire                  mem_rsp_valid,
  output wire                  if_req_valid,
  output wire [`p_PC_W-1:0]    if_req_addr,
  output wire                  mem_req_valid,
  output wire [`p_ADDR_W-1:0]  mem_req_addr,
  output wire [`p_DATA_W-1:0]  mem_req_wdata,
  output wire                  mem_req_we,
  output wire [3:0]            mem_req_wstrb,
  output wire [3:0]            stage_valid
);

  // --------------------------------------------------------------------------
  // The four pipeline registers. These are the ONLY sequential state that
  // belongs to the pipeline as a whole; everything else lives in a block.
  // --------------------------------------------------------------------------
  reg [p_IF_ID_W-1:0]  if_id_q;
  reg [p_ID_EX_W-1:0]  id_ex_q;
  reg [p_EX_MEM_W-1:0] ex_mem_q;
  reg [p_MEM_WB_W-1:0] mem_wb_q;

  // --------------------------------------------------------------------------
  // Bundle fields, unpacked. Every slice is named - no literal bit ranges.
  // --------------------------------------------------------------------------
  wire                  if_id_pred_taken  = if_id_q[p_IF_ID__PRED_TAKEN_LSB +: p_IF_ID__PRED_TAKEN_W];
  wire [`p_PC_W-1:0]    if_id_pc          = if_id_q[p_IF_ID__PC_LSB         +: p_IF_ID__PC_W];
  wire [`p_PC_W-1:0]    if_id_pred_pc     = if_id_q[p_IF_ID__PRED_PC_LSB    +: p_IF_ID__PRED_PC_W];
  wire [`p_INSTR_W-1:0] if_id_instr       = if_id_q[p_IF_ID__INSTR_LSB      +: p_IF_ID__INSTR_W];
  wire                  if_id_valid       = if_id_q[p_IF_ID__VALID_LSB      +: p_IF_ID__VALID_W];
  wire [2:0]            if_id_instr_len   = if_id_q[p_IF_ID__INSTR_LEN_LSB  +: p_IF_ID__INSTR_LEN_W];

  wire                  id_ex_reg_write   = id_ex_q[p_ID_EX__REG_WRITE_LSB   +: p_ID_EX__REG_WRITE_W];
  wire                  id_ex_mem_unsigned= id_ex_q[p_ID_EX__MEM_UNSIGNED_LSB+: p_ID_EX__MEM_UNSIGNED_W];
  wire                  id_ex_mem_write   = id_ex_q[p_ID_EX__MEM_WRITE_LSB   +: p_ID_EX__MEM_WRITE_W];
  wire                  id_ex_mem_read    = id_ex_q[p_ID_EX__MEM_READ_LSB    +: p_ID_EX__MEM_READ_W];
  wire [`p_WB_SEL_W-1:0] id_ex_wb_sel     = id_ex_q[p_ID_EX__WB_SEL_LSB      +: p_ID_EX__WB_SEL_W];
  wire [`p_MEM_SIZE_W-1:0] id_ex_mem_size = id_ex_q[p_ID_EX__MEM_SIZE_LSB    +: p_ID_EX__MEM_SIZE_W];
  wire                  id_ex_uses_rs2    = id_ex_q[p_ID_EX__USES_RS2_LSB    +: p_ID_EX__USES_RS2_W];
  wire                  id_ex_uses_rs1    = id_ex_q[p_ID_EX__USES_RS1_LSB    +: p_ID_EX__USES_RS1_W];
  wire [`p_FUNCT3_W-1:0] id_ex_branch_f3  = id_ex_q[p_ID_EX__BRANCH_FUNCT3_LSB +: p_ID_EX__BRANCH_FUNCT3_W];
  wire [`p_OP2_SEL_W-1:0] id_ex_op2_sel   = id_ex_q[p_ID_EX__OP2_SEL_LSB     +: p_ID_EX__OP2_SEL_W];
  wire [`p_OP1_SEL_W-1:0] id_ex_op1_sel   = id_ex_q[p_ID_EX__OP1_SEL_LSB     +: p_ID_EX__OP1_SEL_W];
  wire [`p_ALU_OP_W-1:0] id_ex_alu_op      = id_ex_q[p_ID_EX__ALU_OP_LSB      +: p_ID_EX__ALU_OP_W];
  wire [`p_REG_ADDR_W-1:0] id_ex_rd_addr  = id_ex_q[p_ID_EX__RD_ADDR_LSB     +: p_ID_EX__RD_ADDR_W];
  wire [`p_REG_ADDR_W-1:0] id_ex_rs2_addr = id_ex_q[p_ID_EX__RS2_ADDR_LSB    +: p_ID_EX__RS2_ADDR_W];
  wire [`p_REG_ADDR_W-1:0] id_ex_rs1_addr = id_ex_q[p_ID_EX__RS1_ADDR_LSB    +: p_ID_EX__RS1_ADDR_W];
  wire [`p_XLEN-1:0]     id_ex_imm         = id_ex_q[p_ID_EX__IMM_LSB         +: p_ID_EX__IMM_W];
  wire [`p_XLEN-1:0]     id_ex_rs2_data    = id_ex_q[p_ID_EX__RS2_DATA_LSB    +: p_ID_EX__RS2_DATA_W];
  wire [`p_XLEN-1:0]     id_ex_rs1_data    = id_ex_q[p_ID_EX__RS1_DATA_LSB    +: p_ID_EX__RS1_DATA_W];
  wire [`p_PC_W-1:0]     id_ex_pc          = id_ex_q[p_ID_EX__PC_LSB          +: p_ID_EX__PC_W];
  wire                  id_ex_is_branch   = id_ex_q[p_ID_EX__IS_BRANCH_LSB   +: p_ID_EX__IS_BRANCH_W];
  wire                  id_ex_is_jal      = id_ex_q[p_ID_EX__IS_JAL_LSB      +: p_ID_EX__IS_JAL_W];
  wire                  id_ex_is_jalr     = id_ex_q[p_ID_EX__IS_JALR_LSB     +: p_ID_EX__IS_JALR_W];
  wire                  id_ex_is_illegal  = id_ex_q[p_ID_EX__IS_ILLEGAL_LSB  +: p_ID_EX__IS_ILLEGAL_W];
  wire                  id_ex_uses_rd     = id_ex_q[p_ID_EX__USES_RD_LSB     +: p_ID_EX__USES_RD_W];
  wire                  id_ex_valid       = id_ex_q[p_ID_EX__VALID_LSB       +: p_ID_EX__VALID_W];
  wire [2:0]            id_ex_instr_len   = id_ex_q[p_ID_EX__INSTR_LEN_LSB   +: p_ID_EX__INSTR_LEN_W];

  wire                  em_reg_write      = ex_mem_q[p_EX_MEM__REG_WRITE_LSB  +: p_EX_MEM__REG_WRITE_W];
  wire                  em_mem_write      = ex_mem_q[p_EX_MEM__MEM_WRITE_LSB  +: p_EX_MEM__MEM_WRITE_W];
  wire                  em_mem_read       = ex_mem_q[p_EX_MEM__MEM_READ_LSB   +: p_EX_MEM__MEM_READ_W];
  wire [`p_WB_SEL_W-1:0] em_wb_sel         = ex_mem_q[p_EX_MEM__WB_SEL_LSB    +: p_EX_MEM__WB_SEL_W];
  wire [`p_MEM_SIZE_W-1:0] em_mem_size     = ex_mem_q[p_EX_MEM__MEM_SIZE_LSB  +: p_EX_MEM__MEM_SIZE_W];
  wire [`p_REG_ADDR_W-1:0] em_rd_addr      = ex_mem_q[p_EX_MEM__RD_ADDR_LSB   +: p_EX_MEM__RD_ADDR_W];
  wire [`p_XLEN-1:0]     em_store_data     = ex_mem_q[p_EX_MEM__STORE_DATA_LSB +: p_EX_MEM__STORE_DATA_W];
  wire [`p_XLEN-1:0]     em_alu_result     = ex_mem_q[p_EX_MEM__ALU_RESULT_LSB +: p_EX_MEM__ALU_RESULT_W];
  wire [`p_PC_W-1:0]     em_pc             = ex_mem_q[p_EX_MEM__PC_LSB         +: p_EX_MEM__PC_W];
  wire                  em_valid          = ex_mem_q[p_EX_MEM__VALID_LSB     +: p_EX_MEM__VALID_W];
  wire [2:0]            em_instr_len      = ex_mem_q[p_EX_MEM__INSTR_LEN_LSB +: p_EX_MEM__INSTR_LEN_W];

  wire                  mw_reg_write      = mem_wb_q[p_MEM_WB__REG_WRITE_LSB +: p_MEM_WB__REG_WRITE_W];
  wire [`p_REG_ADDR_W-1:0] mw_rd_addr      = mem_wb_q[p_MEM_WB__RD_ADDR_LSB  +: p_MEM_WB__RD_ADDR_W];
  wire [`p_XLEN-1:0]     mw_rd_data        = mem_wb_q[p_MEM_WB__RD_DATA_LSB  +: p_MEM_WB__RD_DATA_W];
  /* verilator lint_off UNUSEDSIGNAL */
  // MEM/WB carries `pc`, but this design resolves `wb_sel == 2` (the JAL/JALR
  // link register) inside `mem_stage`, which is a stage earlier, so nothing
  // downstream reads this copy. The field is part of the frozen bundle layout,
  // so it is packed rather than removed; see the note in docs/TEAM.md.
  wire [`p_PC_W-1:0]     mw_pc             = mem_wb_q[p_MEM_WB__PC_LSB       +: p_MEM_WB__PC_W];
  /* verilator lint_on UNUSEDSIGNAL */
  wire                  mw_valid          = mem_wb_q[p_MEM_WB__VALID_LSB     +: p_MEM_WB__VALID_W];

  assign stage_valid = {mw_valid, em_valid, id_ex_valid, if_id_valid};

  // --------------------------------------------------------------------------
  // Register indices. Extracted here rather than in `decode` because three
  // fixed bit ranges are wiring, not decoding - and `decode` must stay a pure
  // function of the instruction word.  Taken from `d_instr_eff`, the expanded
  // word: a compressed encoding carries rd'/rs1'/rs2' in different bit
  // positions, so the raw `if_id_instr` would yield the wrong indices.
  // --------------------------------------------------------------------------
  wire [`p_REG_ADDR_W-1:0] if_rs1_addr = d_instr_eff[19:15];
  wire [`p_REG_ADDR_W-1:0] if_rs2_addr = d_instr_eff[24:20];
  wire [`p_REG_ADDR_W-1:0] if_rd_addr  = d_instr_eff[11:7];

  // --------------------------------------------------------------------------
  // IF stage
  // --------------------------------------------------------------------------
  wire [`p_PC_W-1:0] pc;
  wire              if_pred_taken;
  wire [`p_PC_W-1:0] if_pred_pc;
  wire [`p_INSTR_W-1:0] if_instr;
  wire [2:0]        if_instr_len;

  // --------------------------------------------------------------------------
  // ID stage
  // --------------------------------------------------------------------------
  wire [`p_XLEN-1:0] rs1_data;
  wire [`p_XLEN-1:0] rs2_data;

  wire [`p_INSTR_W-1:0] d_instr_eff;
  wire [`p_ALU_OP_W-1:0] d_alu_op_bits;
  wire                  d_uses_rs1, d_uses_rs2, d_uses_rd;
  wire                  d_reg_write, d_mem_read, d_mem_write, d_mem_unsigned;
  wire [`p_WB_SEL_W-1:0] d_wb_sel;
  wire [`p_MEM_SIZE_W-1:0] d_mem_size;
  wire [`p_FUNCT3_W-1:0] d_branch_f3;
  wire [`p_OP1_SEL_W-1:0] d_op1_sel;
  wire [`p_OP2_SEL_W-1:0] d_op2_sel;
  wire                  d_is_branch, d_is_jal, d_is_jalr, d_is_illegal;
  wire [`p_IMM_SEL_W-1:0] d_imm_sel;
  wire [`p_XLEN-1:0]    d_imm;

  // --------------------------------------------------------------------------
  // EX stage
  // --------------------------------------------------------------------------
  wire [`p_XLEN-1:0] ex_rs1_data, ex_rs2_data;
  wire [`p_XLEN-1:0] ex_alu_result;
  wire [`p_XLEN-1:0] ex_store_data;
  wire [`p_REG_ADDR_W-1:0] ex_rd_addr;
  wire                  ex_reg_write, ex_mem_read, ex_mem_write, ex_mem_unsigned;
  wire [`p_WB_SEL_W-1:0] ex_wb_sel;
  wire [`p_MEM_SIZE_W-1:0] ex_mem_size;
  wire                  ex_redirect_valid, ex_target_misaligned;
  wire [`p_PC_W-1:0]    ex_redirect_pc;

  // --------------------------------------------------------------------------
  // MEM / WB stage
  // --------------------------------------------------------------------------
  wire                  mem_rd_valid;      // a load is completing in MEM
  /* verilator lint_off UNUSEDSIGNAL */
  // `mem_stage`'s registered writeback value, deliberately not consumed.
  //
  // It is correct, but it is one instruction behind: `mem_stage` latches it on
  // the edge that also packs the MEM/WB bundle, so reading it combinationally in
  // that same edge yields the *previous* instruction's value. Using it pairs
  // this instruction's rd_addr and reg_write with the last one's data - the
  // forwarding unit then sees a plausible address and a plausible value that do
  // not belong to the same instruction. `wb_value` below selects the same three
  // sources combinationally instead, which is aligned by construction.
  wire [`p_XLEN-1:0]    mem_rd_data;
  /* verilator lint_on UNUSEDSIGNAL */
  wire                  mem_data_misaligned;
  wire [`p_REG_ADDR_W-1:0] mem_rd_addr;
  wire                  mem_reg_write;
  wire                  mem_reg_write_gated;
  wire [`p_WB_SEL_W-1:0] mem_wb_sel;


  wire                  wb_we;
  wire [`p_XLEN-1:0]    wb_wdata;
  wire [`p_REG_ADDR_W-1:0] wb_waddr;
  wire [`p_REG_ADDR_W-1:0] fwd_rd_addr;
  wire [`p_XLEN-1:0]    fwd_rd_data;
  wire                  fwd_reg_write;

  // --------------------------------------------------------------------------
  // Hazards. The load-use interlock is the only interlock in phase 1; MEM
  // holds itself internally, so there is no MEM-stage stall to distribute.
  // --------------------------------------------------------------------------
  wire hazard_id_stall;
  wire fwd_rs1_valid, fwd_rs2_valid;
  wire [`p_XLEN-1:0] fwd_rs1_data, fwd_rs2_data;

  // --------------------------------------------------------------------------
  // Stall and flush. A redirect resolves in EX and throws away IF and ID: the
  // PC takes the new target and two bubbles are injected, so a mispredicted
  // branch costs two cycles. `pc_gen` gives redirect priority over stall, so a
  // fetch held by a redirect still latches the target.
  // --------------------------------------------------------------------------
  // A misaligned jump target is reported by ex_stage but not followed:
  // phase 1 has no trap path, so the safe behaviour is to keep executing
  // sequentially and let the assertion below record it.
  wire redirect_ok   = ex_redirect_valid & ~ex_target_misaligned;
  wire flush         = redirect_ok;

  // The MEM/WB register's reg_write is gated here rather than inside
  // `mem_stage`: a module cannot gate its own input, and `core` owns the
  // bundle. A misaligned load must not write back a value it never read.
  assign mem_reg_write_gated = mem_reg_write & ~mem_data_misaligned;

  // The fetch handshake.
  //
  // `if_stage` owns the request/response exchange and presents the instruction
  // it captured for exactly as long as it is in its internal holding state.
  // `if_req_valid` is asserted in every state except that one, so a low
  // `if_req_valid` is the observable signal for "an instruction is being
  // presented right now" - and `core` has no valid output on `if_stage` to ask.
  //
  // The instruction is accepted only when it can actually move into IF/ID: not
  // squashed by a redirect, not re-fetched while an interlock holds, and not
  // taken while MEM is still waiting on memory. When it is not accepted the
  // instruction stays presented and the PC does not advance, so nothing is
  // lost - the fetch simply waits.
  wire if_present = ~if_req_valid;
  wire pipe_busy  = mem_req_valid & ~mem_rsp_valid;
  wire accept     = if_present & ~flush & ~hazard_id_stall & ~pipe_busy;

  // A redirect has to reach `if_stage` for one cycle longer than it reaches the
  // pipeline behind it.
  //
  // `flush` alone is not enough. In the cycle the redirect resolves, `pc` is
  // still the old one - `pc_gen` latches the new value on that same edge - so
  // `if_stage` is still presenting a request for the address being abandoned.
  // Its answer arrives the cycle *after* the redirect, by which time `if_stage`
  // is idle and fetching the target, and it is taken as the instruction there.
  // The wrong instruction executes and nothing reports it.
  //
  // Holding the flush a second cycle drains that answer instead: `if_stage`
  // discards it, and meanwhile the request for the new `pc` - now correct - is
  // already on the bus.
  reg flush_q;
  always @(posedge clk) begin
    if (!rst_n) flush_q <= 1'b0;
    else        flush_q <= flush;
  end

  // Why these three hold terms exist, and what is still wrong.
  //
  // `if_stage` spends cycles in ST_REQ waiting for its fetch response, and IF/ID
  // cannot be refilled during that window - it still holds the instruction it
  // has. ID/EX must therefore hold too, or it would take that instruction a
  // second time. EX/MEM must hold as well, or it would take ID/EX's instruction
  // while ID/EX keeps it. `hazard` is excluded from the EX/MEM term because a
  // load-use interlock is about to replace ID/EX with a bubble: EX/MEM has to
  // move then, or the instruction being vacated is dropped.
  //
  // Holding EX/MEM across a *granted* memory access is the remaining defect.
  // When the response arrives, `lsu` clears `req_pending`, but the access is
  // still in EX/MEM because `if_id_holding` is holding it, so `req_eligible`
  // goes true again and the same access is presented a second time - the second
  // time carrying whatever the bundle has become. A store then writes its data
  // and overwrites it, and nothing in the design complains. Observed in
  // tb/test_core.py as a store landing the wrong value rather than as an
  // assertion.
  //
  // The structural fix is to stop IF/ID retaining an instruction ID/EX has
  // already consumed: IF/ID should go empty in the cycle its instruction is
  // taken, whenever `if_stage` has nothing new to present. That was tried and
  // it is not a drop-in - it drops `test_back_to_back_dependent_addis` from 8/8
  // to 3/8, because IF/ID then empties on a cycle the store is depending on for
  // its forwarded operand. Whatever resolves this has to keep the forwarding
  // operands alive across the same edge, so it is a change to how the hand-over
  // and the operand read are sequenced, not a one-line stall condition.
  wire hazard = hazard_id_stall & ~pipe_busy;

  // The cycle in which ID/EX consumes whatever IF/ID is holding. `if_stage`
  // leaves its holding state in exactly the cycle ID/EX takes the instruction,
  // so from then on IF/ID still shows an instruction the pipeline has already
  // run. Holding it is what makes ID/EX take it twice: a load then occupies ID/EX
  // and EX/MEM simultaneously and drives two requests for one access. IF/ID must
  // therefore go empty the moment its instruction is taken and nothing new is
  // presented in its place.
  wire take = ~pipe_busy & ~hazard & ~flush;

  // --------------------------------------------------------------------------
  // Block instances. Every port is wired; no positional connections.
  // --------------------------------------------------------------------------
  pc_gen u_pc_gen (
    .clk            (clk),
    .rst_n          (rst_n),
    .stall          (~accept),
    .redirect_valid (redirect_ok),
    .redirect_pc    (ex_redirect_pc),
    .pred_taken     (if_id_pred_taken),
    .pred_pc        (if_id_pred_pc),
    // The step is the fetched instruction's length: 4 for a 32-bit encoding,
    // 2 for a compressed one.  `instr_len` is only meaningful in `if_stage`'s
    // ST_HOLD, which is exactly the cycle `pc_gen` is not stalled and takes
    // this step, so the length and the step always describe the same
    // instruction.
    .pc_step        ({29'b0, if_instr_len}),
    .pc             (pc),
    .next_pc        (pc_next_unused)
  );
  // `next_pc` has no consumer until phase 5, when the branch predictor reads
  // it to decide whether the fetch was right. Carried and named rather than
  // left dangling so the port is visibly wired.
  /* verilator lint_off UNUSEDSIGNAL */
  wire [`p_PC_W-1:0] pc_next_unused;
  /* verilator lint_on UNUSEDSIGNAL */

  if_stage u_if_stage (
    .clk          (clk),
    .rst_n        (rst_n),
    .stall        (~accept),
    .flush        (flush | flush_q),
    .pc           (pc),
    .if_rsp_rdata (if_rsp_rdata),
    .if_rsp_valid (if_rsp_valid),
    .if_req_valid (if_req_valid),
    .if_req_addr  (if_req_addr),
    .instr        (if_instr),
    .instr_len    (if_instr_len),
    .pred_taken   (if_pred_taken),
    .pred_pc      (if_pred_pc)
  );

  regfile u_regfile (
    .clk       (clk),
    .rst_n     (rst_n),
    .rs1_addr  (if_rs1_addr),
    .rs2_addr  (if_rs2_addr),
    .rs1_used  (d_uses_rs1),
    .rs2_used  (d_uses_rs2),
    .wb_we     (wb_we),
    .wb_waddr  (wb_waddr),
    .wb_wdata  (wb_wdata),
    .rs1_data  (rs1_data),
    .rs2_data  (rs2_data)
  );

  decode u_decode (
    .instr        (if_id_instr),
    .instr_eff    (d_instr_eff),
    .alu_op       (d_alu_op_bits),
    .op1_sel      (d_op1_sel),
    .op2_sel      (d_op2_sel),
    .imm_sel      (d_imm_sel),
    .branch_funct3(d_branch_f3),
    .is_branch    (d_is_branch),
    .is_jal       (d_is_jal),
    .is_jalr      (d_is_jalr),
    .is_illegal   (d_is_illegal),
    .uses_rs1     (d_uses_rs1),
    .uses_rs2     (d_uses_rs2),
    .uses_rd      (d_uses_rd),
    .mem_read     (d_mem_read),
    .mem_write    (d_mem_write),
    .mem_size     (d_mem_size),
    .mem_unsigned (d_mem_unsigned),
    .reg_write    (d_reg_write),
    .wb_sel       (d_wb_sel)
  );

  imm_gen u_imm_gen (
    .instr   (d_instr_eff),
    .imm_sel (d_imm_sel),
    .imm     (d_imm)
  );

  hazard_unit u_hazard_unit (
    .id_uses_rs1 (d_uses_rs1),
    .id_uses_rs2 (d_uses_rs2),
    .id_rs1_addr (if_rs1_addr),
    .id_rs2_addr (if_rs2_addr),
    .ex_mem_read (em_mem_read),
    .ex_mem_write(em_mem_write),
    .ex_rd_addr  (em_rd_addr),
    .id_stall    (hazard_id_stall)
  );

  forwarding u_forwarding (
    .ex_rs1_addr   (id_ex_rs1_addr),
    .ex_rs2_addr   (id_ex_rs2_addr),
    .id_uses_rs1   (id_ex_uses_rs1),
    .id_uses_rs2   (id_ex_uses_rs2),
    .mem_rd_addr   (em_rd_addr),
    .mem_rd_data   (em_alu_result),
    .mem_reg_write (em_reg_write),
    .fwd_rd_addr   (fwd_rd_addr),
    .fwd_rd_data   (fwd_rd_data),
    .fwd_reg_write (fwd_reg_write),
    .fwd_rs1_valid (fwd_rs1_valid),
    .fwd_rs1_data  (fwd_rs1_data),
    .fwd_rs2_valid (fwd_rs2_valid),
    .fwd_rs2_data  (fwd_rs2_data)
  );

  // The final operand mux: a forwarded value wins over the register file.
  // `forwarding` has already resolved MEM/WB against WB by priority.
  assign ex_rs1_data = fwd_rs1_valid ? fwd_rs1_data : id_ex_rs1_data;
  assign ex_rs2_data = fwd_rs2_valid ? fwd_rs2_data : id_ex_rs2_data;

  ex_stage u_ex_stage (
    .id_pc               (id_ex_pc),
    .id_imm              (id_ex_imm),
    .id_rs1_addr         (id_ex_rs1_addr),
    .id_rs2_addr         (id_ex_rs2_addr),
    .id_rd_addr          (id_ex_rd_addr),
    .id_alu_op           (id_ex_alu_op),
    .id_op1_sel          (id_ex_op1_sel),
    .id_op2_sel          (id_ex_op2_sel),
    .id_branch_funct3    (id_ex_branch_f3),
    .id_is_branch        (id_ex_is_branch),
    .id_is_jal           (id_ex_is_jal),
    .id_is_jalr          (id_ex_is_jalr),
    .id_uses_rs1         (id_ex_uses_rs1),
    .id_uses_rs2         (id_ex_uses_rs2),
    .id_uses_rd          (id_ex_uses_rd),
    .id_mem_read         (id_ex_mem_read),
    .id_mem_write        (id_ex_mem_write),
    .id_mem_size         (id_ex_mem_size),
    .id_mem_unsigned     (id_ex_mem_unsigned),
    .id_reg_write        (id_ex_reg_write),
    .id_wb_sel           (id_ex_wb_sel),
    .ex_rs1_data         (ex_rs1_data),
    .ex_rs2_data         (ex_rs2_data),
    .ex_alu_result       (ex_alu_result),
    .ex_store_data       (ex_store_data),
    .ex_rd_addr          (ex_rd_addr),
    .ex_reg_write        (ex_reg_write),
    .ex_wb_sel           (ex_wb_sel),
    .ex_mem_read         (ex_mem_read),
    .ex_mem_write        (ex_mem_write),
    .ex_mem_size         (ex_mem_size),
    .ex_mem_unsigned     (ex_mem_unsigned),
    .ex_redirect_valid   (ex_redirect_valid),
    .ex_redirect_pc      (ex_redirect_pc),
    .ex_target_misaligned(ex_target_misaligned)
  );

  lsu u_lsu (
    .clk             (clk),
    .rst_n           (rst_n),
    .stall           (1'b0),
    .ex_mem_addr     (em_alu_result),
    .ex_store_data   (em_store_data),
    .ex_mem_read     (em_mem_read),
    .ex_mem_write    (em_mem_write),
    .ex_mem_size     (em_mem_size),
    .ex_mem_unsigned (ex_mem_unsigned),
    .ex_rd_addr      (em_rd_addr),
    .ex_reg_write    (em_reg_write),
    .ex_wb_sel       (em_wb_sel),
    .mem_rsp_rdata   (mem_rsp_rdata),
    .mem_rsp_valid   (mem_rsp_valid),
    .mem_req_valid   (mem_req_valid),
    .mem_req_addr    (mem_req_addr),
    .mem_req_wdata   (mem_req_wdata),
    .mem_req_we      (mem_req_we),
    .mem_req_wstrb   (mem_req_wstrb),
    .data_misaligned (mem_rd_valid),
    .mem_rd_addr     (mem_rd_addr),
    .mem_reg_write   (mem_reg_write),
    .mem_wb_sel      (mem_wb_sel)
  );

  mem_stage u_mem_stage (
    .clk               (clk),
    .rst_n             (rst_n),
    .stall             (pipe_busy),
    .mem_alu_result    (em_alu_result),
    .mem_pc            (em_pc),
    .mem_rsp_rdata     (mem_rsp_rdata),
    .mem_rd_addr       (mem_rd_addr),
    .mem_reg_write     (mem_reg_write),
    .mem_wb_sel        (mem_wb_sel),
    .lsu_data_misaligned(mem_rd_valid),
    .mem_rd_data       (mem_rd_data),
    .data_misaligned   (mem_data_misaligned)
  );

  // wb_stage reads the MEM/WB bundle, not mem_stage's raw outputs: the bundle
  // is the pipeline register, and reading it is what makes the packed bits
  // meaningful rather than a parallel unused copy.
  wb_stage u_wb_stage (
    .mem_rd_data    (mw_rd_data),
    .mem_rd_addr    (mw_rd_addr),
    .mem_reg_write  (mw_reg_write),
    .data_misaligned(1'b0),
    .wb_we          (wb_we),
    .wb_wdata       (wb_wdata),
    .wb_waddr       (wb_waddr),
    .fwd_rd_addr    (fwd_rd_addr),
    .fwd_rd_data    (fwd_rd_data),
    .fwd_reg_write  (fwd_reg_write)
  );

  // --------------------------------------------------------------------------
  // Bundle packing. Each field is placed at its frozen offset by name.
  // --------------------------------------------------------------------------
  reg [p_IF_ID_W-1:0] if_id_d;
  reg [p_ID_EX_W-1:0] id_ex_d;
  reg [p_EX_MEM_W-1:0] ex_mem_d;
  reg [p_MEM_WB_W-1:0] mem_wb_d;

  always @(*) begin
    if_id_d = {p_IF_ID_W{1'b0}};
    if_id_d[p_IF_ID__PRED_TAKEN_LSB +: p_IF_ID__PRED_TAKEN_W] = if_pred_taken;
    if_id_d[p_IF_ID__PC_LSB         +: p_IF_ID__PC_W]         = pc;
    if_id_d[p_IF_ID__PRED_PC_LSB    +: p_IF_ID__PRED_PC_W]    = if_pred_pc;
    if_id_d[p_IF_ID__INSTR_LSB      +: p_IF_ID__INSTR_W]      = if_instr;
    if_id_d[p_IF_ID__VALID_LSB      +: p_IF_ID__VALID_W]      = accept;
    if_id_d[p_IF_ID__INSTR_LEN_LSB  +: p_IF_ID__INSTR_LEN_W]  = if_instr_len;
  end

  always @(*) begin
    id_ex_d = {p_ID_EX_W{1'b0}};
    id_ex_d[p_ID_EX__REG_WRITE_LSB   +: p_ID_EX__REG_WRITE_W]    = d_reg_write;
    id_ex_d[p_ID_EX__MEM_UNSIGNED_LSB+: p_ID_EX__MEM_UNSIGNED_W] = d_mem_unsigned;
    id_ex_d[p_ID_EX__MEM_WRITE_LSB   +: p_ID_EX__MEM_WRITE_W]    = d_mem_write;
    id_ex_d[p_ID_EX__MEM_READ_LSB    +: p_ID_EX__MEM_READ_W]     = d_mem_read;
    id_ex_d[p_ID_EX__WB_SEL_LSB      +: p_ID_EX__WB_SEL_W]       = d_wb_sel;
    id_ex_d[p_ID_EX__MEM_SIZE_LSB    +: p_ID_EX__MEM_SIZE_W]     = d_mem_size;
    id_ex_d[p_ID_EX__USES_RS2_LSB    +: p_ID_EX__USES_RS2_W]     = d_uses_rs2;
    id_ex_d[p_ID_EX__USES_RS1_LSB    +: p_ID_EX__USES_RS1_W]     = d_uses_rs1;
    id_ex_d[p_ID_EX__BRANCH_FUNCT3_LSB +: p_ID_EX__BRANCH_FUNCT3_W] = d_branch_f3;
    id_ex_d[p_ID_EX__OP2_SEL_LSB     +: p_ID_EX__OP2_SEL_W]      = d_op2_sel;
    id_ex_d[p_ID_EX__OP1_SEL_LSB     +: p_ID_EX__OP1_SEL_W]      = d_op1_sel;
    id_ex_d[p_ID_EX__ALU_OP_LSB      +: p_ID_EX__ALU_OP_W]       = d_alu_op_bits;
    id_ex_d[p_ID_EX__RD_ADDR_LSB     +: p_ID_EX__RD_ADDR_W]      = if_rd_addr;
    id_ex_d[p_ID_EX__RS2_ADDR_LSB    +: p_ID_EX__RS2_ADDR_W]     = if_rs2_addr;
    id_ex_d[p_ID_EX__RS1_ADDR_LSB    +: p_ID_EX__RS1_ADDR_W]     = if_rs1_addr;
    id_ex_d[p_ID_EX__IMM_LSB         +: p_ID_EX__IMM_W]          = d_imm;
    id_ex_d[p_ID_EX__RS2_DATA_LSB    +: p_ID_EX__RS2_DATA_W]     = rs2_data;
    id_ex_d[p_ID_EX__RS1_DATA_LSB    +: p_ID_EX__RS1_DATA_W]     = rs1_data;
    id_ex_d[p_ID_EX__PC_LSB          +: p_ID_EX__PC_W]           = if_id_pc;
    id_ex_d[p_ID_EX__IS_BRANCH_LSB   +: p_ID_EX__IS_BRANCH_W]    = d_is_branch;
    id_ex_d[p_ID_EX__IS_JAL_LSB      +: p_ID_EX__IS_JAL_W]       = d_is_jal;
    id_ex_d[p_ID_EX__IS_JALR_LSB     +: p_ID_EX__IS_JALR_W]      = d_is_jalr;
    id_ex_d[p_ID_EX__IS_ILLEGAL_LSB  +: p_ID_EX__IS_ILLEGAL_W]   = d_is_illegal;
    id_ex_d[p_ID_EX__USES_RD_LSB     +: p_ID_EX__USES_RD_W]      = d_uses_rd;
    id_ex_d[p_ID_EX__VALID_LSB       +: p_ID_EX__VALID_W]        = if_id_valid & ~flush & ~hazard_id_stall;
    id_ex_d[p_ID_EX__INSTR_LEN_LSB   +: p_ID_EX__INSTR_LEN_W]    = if_id_instr_len;
  end

  always @(*) begin
    ex_mem_d = {p_EX_MEM_W{1'b0}};
    // An illegal encoding must not write back. `is_illegal` lives in ID/EX
    // and is not carried into MEM/WB, so the suppression happens here, the
    // last bundle that still holds the flag.
    ex_mem_d[p_EX_MEM__REG_WRITE_LSB  +: p_EX_MEM__REG_WRITE_W]  = ex_reg_write & ~id_ex_is_illegal;
    ex_mem_d[p_EX_MEM__MEM_WRITE_LSB  +: p_EX_MEM__MEM_WRITE_W]  = ex_mem_write;
    ex_mem_d[p_EX_MEM__MEM_READ_LSB   +: p_EX_MEM__MEM_READ_W]   = ex_mem_read;
    ex_mem_d[p_EX_MEM__WB_SEL_LSB     +: p_EX_MEM__WB_SEL_W]     = ex_wb_sel;
    ex_mem_d[p_EX_MEM__MEM_SIZE_LSB   +: p_EX_MEM__MEM_SIZE_W]   = ex_mem_size;
    ex_mem_d[p_EX_MEM__RD_ADDR_LSB    +: p_EX_MEM__RD_ADDR_W]    = ex_rd_addr;
    ex_mem_d[p_EX_MEM__STORE_DATA_LSB +: p_EX_MEM__STORE_DATA_W] = ex_store_data;
    ex_mem_d[p_EX_MEM__ALU_RESULT_LSB +: p_EX_MEM__ALU_RESULT_W] = ex_alu_result;
    // The PC rides alongside for the JAL/JALR link register, so it is copied
    // from ID/EX rather than recomputed: no stage re-derives it.
    ex_mem_d[p_EX_MEM__PC_LSB        +: p_EX_MEM__PC_W]          = id_ex_pc;
    // Validity is carried down the chain, not invented here: an instruction
    // only reaches MEM if it was real in EX.
    ex_mem_d[p_EX_MEM__VALID_LSB      +: p_EX_MEM__VALID_W]      = id_ex_valid;
    // Length rides with the PC so WB can link the *next* instruction's address.
    ex_mem_d[p_EX_MEM__INSTR_LEN_LSB  +: p_EX_MEM__INSTR_LEN_W]  = id_ex_instr_len;
  end

  // The writeback value for the instruction currently in EX/MEM.
  //
  // `mem_stage` selects the same three sources and registers them, but that
  // registered output is one instruction behind the address `core` is packing
  // into the same bundle: at the edge, `mem_stage`'s register latches the value
  // for the instruction in EX/MEM now, while reading it back combinationally
  // returns the *previous* one's. So the bundle pairs this instruction's
  // rd_addr and reg_write with the last instruction's data, and the symptom is
  // a forwarding unit that sees a plausible address, a plausible value, and
  // neither belonging to the same instruction.
  //
  // The selection is repeated here rather than taken from `mem_stage` because
  // the frozen port list exposes only the registered result; adding an
  // unregistered output would be a contract change. The encoding matches
  // `mem_stage`: 0 = ALU, 1 = memory, 2 = PC + instruction length. The link is
  // `pc + 4` for a 32-bit JAL and `pc + 2` for a compressed `c.jal`, so the
  // length travels with the PC in EX/MEM instead of a hard-coded 4.
  reg [`p_XLEN-1:0] wb_value;
  always @(*) begin
    case (em_wb_sel)
      2'd1:    wb_value = mem_rsp_rdata;
      2'd2:    wb_value = em_pc + {29'b0, em_instr_len};
      default: wb_value = em_alu_result;
    endcase
  end

  always @(*) begin
    mem_wb_d = {p_MEM_WB_W{1'b0}};
    mem_wb_d[p_MEM_WB__REG_WRITE_LSB +: p_MEM_WB__REG_WRITE_W] = mem_reg_write_gated;
    mem_wb_d[p_MEM_WB__RD_ADDR_LSB   +: p_MEM_WB__RD_ADDR_W]   = mem_rd_addr;
    mem_wb_d[p_MEM_WB__RD_DATA_LSB   +: p_MEM_WB__RD_DATA_W]   = wb_value;
    mem_wb_d[p_MEM_WB__PC_LSB        +: p_MEM_WB__PC_W]        = em_pc;
    mem_wb_d[p_MEM_WB__VALID_LSB     +: p_MEM_WB__VALID_W]     = em_valid;
  end

  // --------------------------------------------------------------------------
  // Sequential update. Every stage-bundle register clears while reset is
  // asserted, so no stage can come up holding a stale valid bit. That is the
  // property `stage_valid` exists to let a testbench observe.
  // --------------------------------------------------------------------------
  always @(posedge clk) begin
    if (!rst_n) begin
      if_id_q  <= {p_IF_ID_W{1'b0}};
      id_ex_q  <= {p_ID_EX_W{1'b0}};
      ex_mem_q <= {p_EX_MEM_W{1'b0}};
      mem_wb_q <= {p_MEM_WB_W{1'b0}};
    end else begin
      // IF/ID takes a newly presented instruction, or goes empty in the cycle
      // its instruction is consumed and `if_stage` has nothing to replace it
      // with. Holding a consumed instruction is the duplication bug above.
      if (flush)
        if_id_q <= {p_IF_ID_W{1'b0}};
      else if (accept)
        if_id_q <= if_id_d;
      else if (take)
        if_id_q <= {p_IF_ID_W{1'b0}};

// ID/EX takes the decode result, a load-use bubble, or a redirect bubble.
      if (hazard || flush)
        id_ex_q <= {p_ID_EX_W{1'b0}};
      else if (pipe_busy)
        id_ex_q <= id_ex_q;
      else
        id_ex_q <= id_ex_d;

      // EX/MEM and MEM/WB hold while MEM is waiting on a response.
      //
      // This is not an optimisation, it is the `lsu`'s stated contract: it
      // asserts that an access is never withdrawn while its request is live,
      // and says in terms that `core` is the one that must honour it by
      // holding EX/MEM for exactly this condition. Advancing here would swap
      // the address out from under an outstanding load or store, and the
      // request would simply stop - invisibly, which is the worst failure
      // mode this block has.
      if (pipe_busy) begin
        ex_mem_q <= ex_mem_q;
        mem_wb_q <= mem_wb_q;
      end else begin
        ex_mem_q <= ex_mem_d;
        mem_wb_q <= mem_wb_d;
      end
    end
  end

  // --------------------------------------------------------------------------
  // Self-checks. These are properties of the wiring, not of any one block, so
  // they belong to the module that owns the wiring.
  // --------------------------------------------------------------------------
  always @(posedge clk) begin
    if (rst_n) begin
      assert (!fwd_reg_write || (fwd_rd_addr != {`p_REG_ADDR_W{1'b0}})) else $error("core: fwd_reg_write asserted for x0");
      assert (!wb_we || (wb_waddr != {`p_REG_ADDR_W{1'b0}})) else $error("core: wb_we asserted for x0");
      assert (!flush || !hazard_id_stall) else $error("core: a redirect and a load-use interlock in the same cycle");
      assert (!ex_target_misaligned || ex_redirect_valid) else $error("core: a misaligned target was reported with no redirect to suppress");
      assert (!mw_reg_write || (mw_rd_addr != {`p_REG_ADDR_W{1'b0}}) || !wb_we) else $error("core: MEM/WB would write x0 - the x0 discard was not enforced downstream");
    end
  end

endmodule
`default_nettype wire
