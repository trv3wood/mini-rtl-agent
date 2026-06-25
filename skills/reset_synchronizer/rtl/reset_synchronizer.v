`timescale 1ns/1ps

module reset_synchronizer #(
    parameter integer STAGES = 2,
    parameter integer RESET_ACTIVE_LEVEL = 1
) (
    input  wire clk,
    input  wire rst_in,
    output wire rst_out
);
    reg [STAGES-1:0] sync_reg;
    wire active_value = RESET_ACTIVE_LEVEL ? 1'b1 : 1'b0;
    wire inactive_value = ~active_value;
    wire rst_active = (rst_in == active_value);

    assign rst_out = sync_reg[STAGES-1];

    always @(posedge clk or posedge rst_active) begin
        if (rst_active) begin
            sync_reg <= {STAGES{active_value}};
        end else begin
            sync_reg <= {sync_reg[STAGES-2:0], inactive_value};
        end
    end
endmodule
