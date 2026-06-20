// Simple FIFO example for deterministic skill builder tests.
module simple_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH = 4
) (
    input wire clk,
    input wire rst,
    input wire wr_en,
    input wire [DATA_WIDTH-1:0] wr_data,
    input wire rd_en,
    output reg [DATA_WIDTH-1:0] rd_data,
    output wire full,
    output wire empty
);
    localparam IDLE = 2'd0;
    reg [1:0] state;
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    reg [2:0] count;

    assign full = count == DEPTH;
    assign empty = count == 0;

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            count <= 0;
            rd_data <= 0;
        end else begin
            state <= IDLE;
        end
    end
endmodule
