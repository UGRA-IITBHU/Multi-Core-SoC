`default_nettype none
// ============================================================================
// defs.vh - global datapath widths for the RV32IMAC 5-stage pipeline SoC.
//
// Shared by every module.  Included as `include "defs.vh" with no relative
// path: the +incdir/-I path is supplied by the Makefile so that each module
// can be built from its own source file alone (the drop-in contract).
//
// Owners: controller (Phase 1, Task 1).  Frozen from this commit.
// ============================================================================
`ifndef SOC_DEFS_VH
`define SOC_DEFS_VH

// --- datapath widths -------------------------------------------------------
`define p_XLEN      32
`define p_PC_W      32
`define p_INSTR_W   32
`define p_REG_W     32
`define p_ADDR_W    32
`define p_DATA_W    32

// --- reset -----------------------------------------------------------------
`define p_RESET_VEC 32'h0000_0000

// --- register file ---------------------------------------------------------
// Not listed in the plan's defs.vh table, but every module needs it and the
// contract forbids magic numbers outside this file.
`define p_REG_ADDR_W 5

`endif // SOC_DEFS_VH
`default_nettype wire
