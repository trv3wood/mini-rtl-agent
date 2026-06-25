`timescale 1ns/1ps

module i2c_master #(
    parameter ARST_LVL = 1'b1,
    parameter [6:0] DEFAULT_SLAVE_ADDR = 7'b1111110
) (
    input  wire wb_clk_i,
    input  wire wb_rst_i,
    input  wire arst_i,
    input  wire [2:0] wb_adr_i,
    input  wire [7:0] wb_dat_i,
    output reg  [7:0] wb_dat_o,
    input  wire wb_we_i,
    input  wire wb_stb_i,
    input  wire wb_cyc_i,
    output reg  wb_ack_o,
    output wire wb_inta_o,
    input  wire scl_pad_i,
    output wire scl_pad_o,
    output reg  scl_padoen_o,
    input  wire sda_pad_i,
    output wire sda_pad_o,
    output reg  sda_padoen_o
);
    localparam S_IDLE = 0, S_START = 1, S_SHIFT = 2, S_STOP = 3;
    reg [1:0] state;
    reg [7:0] tx_reg;
    reg [2:0] bit_count;
    reg irq_pending;
    reg [7:0] status_reg;
    wire access = wb_cyc_i && wb_stb_i && !wb_ack_o;

    assign scl_pad_o = 1'b0;
    assign sda_pad_o = 1'b0;
    assign wb_inta_o = irq_pending;

    always @(posedge wb_clk_i or posedge arst_i) begin
        if (arst_i == ARST_LVL || wb_rst_i) begin
            state <= S_IDLE;
            tx_reg <= {DEFAULT_SLAVE_ADDR, 1'b0};
            bit_count <= 0;
            irq_pending <= 0;
            status_reg <= 0;
            wb_ack_o <= 0;
            wb_dat_o <= 0;
            scl_padoen_o <= 1;
            sda_padoen_o <= 1;
        end else begin
            wb_ack_o <= access;
            if (access && wb_we_i) begin
                case (wb_adr_i)
                    3'd1: tx_reg <= wb_dat_i;
                    3'd2: if (wb_dat_i[7]) begin state <= S_START; status_reg[0] <= 1; irq_pending <= 0; end
                    3'd3: irq_pending <= irq_pending & ~wb_dat_i[0];
                    default: begin end
                endcase
            end
            if (access && !wb_we_i) begin
                case (wb_adr_i)
                    3'd0: wb_dat_o <= status_reg;
                    3'd1: wb_dat_o <= tx_reg;
                    default: wb_dat_o <= 0;
                endcase
            end
            case (state)
                S_IDLE: begin scl_padoen_o <= 1; sda_padoen_o <= 1; status_reg[0] <= 0; end
                S_START: begin sda_padoen_o <= 0; scl_padoen_o <= 1; bit_count <= 7; state <= S_SHIFT; end
                S_SHIFT: begin
                    scl_padoen_o <= ~scl_padoen_o;
                    if (!scl_padoen_o) begin
                        sda_padoen_o <= tx_reg[bit_count];
                        if (bit_count == 0) state <= S_STOP;
                        else bit_count <= bit_count - 1'b1;
                    end
                end
                S_STOP: begin sda_padoen_o <= 1; scl_padoen_o <= 1; status_reg[0] <= 0; irq_pending <= 1; state <= S_IDLE; end
            endcase
        end
    end
endmodule
