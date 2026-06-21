`timescale 1ns/1ps

module sync_fifo #(
    parameter integer DATA_WIDTH = 8,
    parameter integer DEPTH = 4,
    parameter integer ADDR_WIDTH = 2
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output wire                  full,
    output wire                  empty,
    output reg  [ADDR_WIDTH:0]   count
);
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_WIDTH-1:0] wr_ptr;
    reg [ADDR_WIDTH-1:0] rd_ptr;

    assign full = (count == DEPTH);
    assign empty = (count == 0);

    always @(posedge clk) begin
        if (rst) begin
            wr_ptr <= 0;
            rd_ptr <= 0;
            rd_data <= 0;
            count <= 0;
        end else begin
            case ({wr_en && !full, rd_en && !empty})
                2'b10: begin
                    mem[wr_ptr] <= wr_data;
                    wr_ptr <= wr_ptr + 1'b1;
                    count <= count + 1'b1;
                end
                2'b01: begin
                    rd_data <= mem[rd_ptr];
                    rd_ptr <= rd_ptr + 1'b1;
                    count <= count - 1'b1;
                end
                2'b11: begin
                    mem[wr_ptr] <= wr_data;
                    wr_ptr <= wr_ptr + 1'b1;
                    rd_data <= mem[rd_ptr];
                    rd_ptr <= rd_ptr + 1'b1;
                end
                default: begin end
            endcase
        end
    end
endmodule
