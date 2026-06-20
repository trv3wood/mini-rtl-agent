`timescale 1ns/1ps

module example_i2c_master(input wire clk, input wire rst, input wire [2:0] adr, input wire [7:0] dat_i, output wire [7:0] dat_o, input wire we, input wire stb, input wire cyc, output wire ack, output wire irq, input wire scl_i, input wire sda_i, output wire scl_o, output wire scl_oe, output wire sda_o, output wire sda_oe);
    i2c_master u_i2c (.wb_clk_i(clk), .wb_rst_i(rst), .arst_i(1'b0), .wb_adr_i(adr), .wb_dat_i(dat_i), .wb_dat_o(dat_o), .wb_we_i(we), .wb_stb_i(stb), .wb_cyc_i(cyc), .wb_ack_o(ack), .wb_inta_o(irq), .scl_pad_i(scl_i), .scl_pad_o(scl_o), .scl_padoen_o(scl_oe), .sda_pad_i(sda_i), .sda_pad_o(sda_o), .sda_padoen_o(sda_oe));
endmodule
