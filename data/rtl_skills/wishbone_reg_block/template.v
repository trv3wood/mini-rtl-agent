`timescale 1ns/1ps

module wishbone_reg_block #(
    parameter integer ADDR_WIDTH = 3,
    parameter integer DATA_WIDTH = 8
) (
    input  wire clk,
    input  wire rst,
    input  wire [ADDR_WIDTH-1:0] wb_adr_i,
    input  wire [DATA_WIDTH-1:0] wb_dat_i,
    output reg  [DATA_WIDTH-1:0] wb_dat_o,
    input  wire wb_we_i,
    input  wire wb_stb_i,
    input  wire wb_cyc_i,
    output reg  wb_ack_o,
    output wire irq_o
);
    reg [DATA_WIDTH-1:0] control_reg;
    reg [DATA_WIDTH-1:0] data_reg;
    reg irq_pending;
    wire access = wb_cyc_i && wb_stb_i && !wb_ack_o;

    assign irq_o = irq_pending && control_reg[0];

    always @(posedge clk) begin
        if (rst) begin
            control_reg <= 0;
            data_reg <= 0;
            irq_pending <= 0;
            wb_ack_o <= 0;
            wb_dat_o <= 0;
        end else begin
            wb_ack_o <= access;
            if (access && wb_we_i) begin
                case (wb_adr_i)
                    0: begin
                        control_reg <= wb_dat_i & 8'hfd;
                        if (wb_dat_i[1]) irq_pending <= 1'b1;
                    end
                    1: data_reg <= wb_dat_i;
                    2: irq_pending <= irq_pending & ~wb_dat_i[0];
                    default: begin end
                endcase
            end
            if (access && !wb_we_i) begin
                case (wb_adr_i)
                    0: wb_dat_o <= control_reg;
                    1: wb_dat_o <= data_reg;
                    2: wb_dat_o <= {{(DATA_WIDTH-1){1'b0}}, irq_pending};
                    default: wb_dat_o <= 0;
                endcase
            end
            // control_reg[1] is a write-only one-shot trigger handled above.
        end
    end
endmodule
