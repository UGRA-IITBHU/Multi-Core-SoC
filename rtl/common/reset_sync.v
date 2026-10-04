`default_nettype none
// ============================================================================
// reset_sync - active-low reset synchroniser.
//
// Purpose: turn an asynchronous, possibly glitchy reset assertion at the pad
// into a synchronous, glitch-free deassertion inside the design.
//
// Contract: asynchronous assertion, synchronous deassertion.  arst_n is
// sampled directly in the sensitivity list, so srst_n falls as soon as arst_n
// falls -- no clock and no reset delay.  Deassertion is passed through two
// flip-flops, so srst_n can only rise on a rising clock edge, two rising edges
// after arst_n goes high.  Nothing in the design sees an asynchronous
// deassertion.
//
// Drop-in replaceable: this file currently holds only the frozen port list.
// Replacing it with a real implementation must not change the port list and
// must not require any other module to change.
// ============================================================================
`timescale 1ns/1ps

module reset_sync (
  input  wire clk,
  input  wire arst_n,
  output wire srst_n
);

  // bit 1 is the synchronised output; bit 0 is the load that makes the
  // deassertion take two rising edges to propagate.
  reg [1:0] sync_q;

  always @(posedge clk or negedge arst_n) begin
    if (!arst_n) sync_q <= 2'b00;
    else        sync_q <= {sync_q[0], 1'b1};
  end

  assign srst_n = sync_q[1];

endmodule
`default_nettype wire
