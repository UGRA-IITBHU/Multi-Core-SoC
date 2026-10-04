// ============================================================================
// pipeline_regs.vh - bit layout of the four pipeline stage bundles.
//
// `core` owns the pipeline registers and packs every bundle from the discrete
// signals its stage modules produce (docs/contracts/phase1-interfaces.md,
// "Signal provenance").  Stage modules never see a bundle; they only see flat
// ports.  This header is therefore the single source of truth for where each
// field lives, and the only place bundle widths are written down.
//
// Layout convention: bit 0 is the LSB of the bundle, fields grow upward from
// the control byte, and each bundle lists `p_<BUNDLE>_W` as its total width.
//
// Owners: controller (Phase 1, Task 1).  Frozen from this commit.
// ============================================================================
`ifndef SOC_PIPELINE_REGS_VH
`define SOC_PIPELINE_REGS_VH

`include "defs.vh"
`include "ctrl_fields.vh"

// ===========================================================================
// IF/ID bundle  (width 97)
//
// Produced by `pc_gen` + `if_stage`, consumed by decode / regfile / imm_gen.
// ===========================================================================
`define p_IF_ID__PRED_TAKEN_LSB  0
`define p_IF_ID__PRED_TAKEN_W    1

`define p_IF_ID__PC_LSB          1
`define p_IF_ID__PC_W            32

`define p_IF_ID__PRED_PC_LSB     33
`define p_IF_ID__PRED_PC_W       32

`define p_IF_ID__INSTR_LSB       65
`define p_IF_ID__INSTR_W         32

`define p_IF_ID_W                97

// ===========================================================================
// ID/EX bundle  (width 170)
//
// Produced by `core` from `decode` control fields, `regfile` read data and
// `imm_gen` output.  Consumed by `ex_stage`, `forwarding`, `hazard_unit`.
// ===========================================================================
// -- control byte -----------------------------------------------------------
`define p_ID_EX__REG_WRITE_LSB   0
`define p_ID_EX__REG_WRITE_W     1
`define p_ID_EX__MEM_UNSIGNED_LSB 1
`define p_ID_EX__MEM_UNSIGNED_W  1
`define p_ID_EX__MEM_WRITE_LSB   2
`define p_ID_EX__MEM_WRITE_W     1
`define p_ID_EX__MEM_READ_LSB    3
`define p_ID_EX__MEM_READ_W      1
`define p_ID_EX__WB_SEL_LSB      4
`define p_ID_EX__WB_SEL_W        2
`define p_ID_EX__MEM_SIZE_LSB    6
`define p_ID_EX__MEM_SIZE_W      2

// -- operands and control ---------------------------------------------------
`define p_ID_EX__USES_RS2_LSB    8
`define p_ID_EX__USES_RS2_W      1
`define p_ID_EX__USES_RS1_LSB    9
`define p_ID_EX__USES_RS1_W      1
`define p_ID_EX__BRANCH_FUNCT3_LSB 10
`define p_ID_EX__BRANCH_FUNCT3_W 3
`define p_ID_EX__OP2_SEL_LSB     13
`define p_ID_EX__OP2_SEL_W       3
`define p_ID_EX__OP1_SEL_LSB     16
`define p_ID_EX__OP1_SEL_W       2
`define p_ID_EX__ALU_OP_LSB      18
`define p_ID_EX__ALU_OP_W        4
`define p_ID_EX__RD_ADDR_LSB     22
`define p_ID_EX__RD_ADDR_W       5
`define p_ID_EX__RS2_ADDR_LSB    27
`define p_ID_EX__RS2_ADDR_W      5
`define p_ID_EX__RS1_ADDR_LSB    32
`define p_ID_EX__RS1_ADDR_W      5
`define p_ID_EX__IMM_LSB         37
`define p_ID_EX__IMM_W           32
`define p_ID_EX__RS2_DATA_LSB    69
`define p_ID_EX__RS2_DATA_W      32
`define p_ID_EX__RS1_DATA_LSB    101
`define p_ID_EX__RS1_DATA_W      32
`define p_ID_EX__PC_LSB          133
`define p_ID_EX__PC_W            32

// -- control class and register-field meaning -------------------------------
// Added after the rest of the bundle was frozen, so these sit above `pc` and
// no offset above changes.  `is_branch` / `is_jal` / `is_jalr` are what let
// `ex_stage` resolve a branch or jump; `uses_rd` says whether the rd field is
// meaningful; `is_illegal` is the decode verdict that an opcode or funct
// encoding is not implemented.
`define p_ID_EX__IS_BRANCH_LSB   165
`define p_ID_EX__IS_BRANCH_W     1
`define p_ID_EX__IS_JAL_LSB      166
`define p_ID_EX__IS_JAL_W        1
`define p_ID_EX__IS_JALR_LSB     167
`define p_ID_EX__IS_JALR_W       1
`define p_ID_EX__IS_ILLEGAL_LSB  168
`define p_ID_EX__IS_ILLEGAL_W    1
`define p_ID_EX__USES_RD_LSB     169
`define p_ID_EX__USES_RD_W       1

`define p_ID_EX_W                170

// ===========================================================================
// EX/MEM bundle  (width 108)
//
// Produced by `core` from `ex_stage` and `lsu` outputs.  Consumed by
// `mem_stage`, and by `forwarding` / `hazard_unit` as the MEM-stage producer.
// ===========================================================================
`define p_EX_MEM__REG_WRITE_LSB  0
`define p_EX_MEM__REG_WRITE_W    1
`define p_EX_MEM__MEM_WRITE_LSB  1
`define p_EX_MEM__MEM_WRITE_W    1
`define p_EX_MEM__MEM_READ_LSB   2
`define p_EX_MEM__MEM_READ_W     1
`define p_EX_MEM__WB_SEL_LSB     3
`define p_EX_MEM__WB_SEL_W       2
`define p_EX_MEM__MEM_SIZE_LSB   5
`define p_EX_MEM__MEM_SIZE_W     2
`define p_EX_MEM__RD_ADDR_LSB    7
`define p_EX_MEM__RD_ADDR_W      5
`define p_EX_MEM__STORE_DATA_LSB 12
`define p_EX_MEM__STORE_DATA_W   32
`define p_EX_MEM__ALU_RESULT_LSB 44
`define p_EX_MEM__ALU_RESULT_W   32
`define p_EX_MEM__PC_LSB         76
`define p_EX_MEM__PC_W           32

`define p_EX_MEM_W               108

// ===========================================================================
// MEM/WB bundle  (width 70)
//
// Produced by `core` from `mem_stage` outputs.  Consumed by `wb_stage`.
// ===========================================================================
`define p_MEM_WB__REG_WRITE_LSB  0
`define p_MEM_WB__REG_WRITE_W    1
`define p_MEM_WB__RD_ADDR_LSB    1
`define p_MEM_WB__RD_ADDR_W      5
`define p_MEM_WB__RD_DATA_LSB    6
`define p_MEM_WB__RD_DATA_W      32
`define p_MEM_WB__PC_LSB         38
`define p_MEM_WB__PC_W           32

`define p_MEM_WB_W               70

`endif // SOC_PIPELINE_REGS_VH
