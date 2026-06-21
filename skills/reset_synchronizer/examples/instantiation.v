`timescale 1ns/1ps

module example_reset_synchronizer(input wire clk, input wire rst_in, output wire rst_out);
    reset_synchronizer #(.STAGES(2), .RESET_ACTIVE_LEVEL(1)) u_reset_sync (.clk(clk), .rst_in(rst_in), .rst_out(rst_out));
endmodule
