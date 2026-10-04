// ============================================================================
// ctrl_fields.vh - names and widths of the decode/execute control bundle.
//
// `decode` produces these signals (see docs/contracts/phase1-interfaces.md).
// `core` re-packs them into the ID/EX and EX/MEM bundles using the bit
// positions from pipeline_regs.vh.  The field-name macros exist so that
// `core` and the stage modules never spell a control signal by hand.
//
// Owners: controller (Phase 1, Task 1).  Frozen from this commit.
// ============================================================================
`ifndef SOC_CTRL_FIELDS_VH
`define SOC_CTRL_FIELDS_VH

`include "defs.vh"

// ---------------------------------------------------------------------------
// Field widths
// ---------------------------------------------------------------------------
`define p_ALU_OP_W    4  // alu operation select, encoding owned by ex_stage/alu
`define p_OP1_SEL_W   2  // 0 = rs1, 1 = pc, 2 = zero
`define p_OP2_SEL_W   3  // 0 = rs2, 1 = imm, 2 = 4, 3 = pc
`define p_IMM_SEL_W   3  // immediate format select, consumed by imm_gen
`define p_FUNCT3_W    3  // funct3 for load/store width, signedness, branches
`define p_MEM_SIZE_W  2  // 0 = byte, 1 = half, 2 = word
`define p_WB_SEL_W    2  // 0 = alu, 1 = mem, 2 = pc+4

// ---------------------------------------------------------------------------
// Field names (used by `core` when packing the stage bundles)
// ---------------------------------------------------------------------------
`define c_ALU_OP        alu_op
`define c_OP1_SEL       op1_sel
`define c_OP2_SEL       op2_sel
`define c_IMM_SEL       imm_sel
`define c_BRANCH_FUNCT3 branch_funct3
`define c_USES_RS1      uses_rs1
`define c_USES_RS2      uses_rs2
`define c_MEM_READ      mem_read
`define c_MEM_WRITE     mem_write
`define c_MEM_SIZE      mem_size
`define c_MEM_UNSIGNED  mem_unsigned
`define c_REG_WRITE     reg_write
`define c_WB_SEL        wb_sel

// The five single-bit memory-control fields share one byte inside the stage
// bundles; pipeline_regs.vh places them at the bottom of ID/EX and EX/MEM.
`define c_CTRL_BYTE_W   8

`endif // SOC_CTRL_FIELDS_VH
