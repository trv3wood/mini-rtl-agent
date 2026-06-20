`timescale 1ns/1ps

module example_wishbone_reg_block(input wire clk, input wire rst, input wire [2:0] adr, input wire [7:0] dat_i, output wire [7:0] dat_o, input wire we, input wire stb, input wire cyc, output wire ack, output wire irq);
    wishbone_reg_block u_regs (.clk(clk), .rst(rst), .wb_adr_i(adr), .wb_dat_i(dat_i), .wb_dat_o(dat_o), .wb_we_i(we), .wb_stb_i(stb), .wb_cyc_i(cyc), .wb_ack_o(ack), .irq_o(irq));
endmodule
