`timescale 1ns/1ps

module async_fifo #(
    parameter integer DATA_WIDTH = 8,
    parameter integer ADDR_WIDTH = 2
) (
    input  wire                  wr_clk,
    input  wire                  wr_rst,
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    output wire                  wr_full,
    input  wire                  rd_clk,
    input  wire                  rd_rst,
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output wire                  rd_empty
);
    localparam integer DEPTH = 1 << ADDR_WIDTH;
    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    reg [ADDR_WIDTH:0] wr_bin, wr_gray;
    reg [ADDR_WIDTH:0] rd_bin, rd_gray;
    reg [ADDR_WIDTH:0] rd_gray_sync1, rd_gray_sync2;
    reg [ADDR_WIDTH:0] wr_gray_sync1, wr_gray_sync2;

    wire [ADDR_WIDTH:0] wr_bin_next = wr_bin + 1'b1;
    wire [ADDR_WIDTH:0] rd_bin_next = rd_bin + 1'b1;
    wire [ADDR_WIDTH:0] wr_gray_next = (wr_bin_next >> 1) ^ wr_bin_next;
    wire [ADDR_WIDTH:0] rd_gray_next = (rd_bin_next >> 1) ^ rd_bin_next;

    assign wr_full = (wr_gray_next == {~rd_gray_sync2[ADDR_WIDTH:ADDR_WIDTH-1], rd_gray_sync2[ADDR_WIDTH-2:0]});
    assign rd_empty = (rd_gray == wr_gray_sync2);

    always @(posedge wr_clk) begin
        if (wr_rst) begin
            wr_bin <= 0;
            wr_gray <= 0;
            rd_gray_sync1 <= 0;
            rd_gray_sync2 <= 0;
        end else begin
            rd_gray_sync1 <= rd_gray;
            rd_gray_sync2 <= rd_gray_sync1;
            if (wr_en && !wr_full) begin
                mem[wr_bin[ADDR_WIDTH-1:0]] <= wr_data;
                wr_bin <= wr_bin_next;
                wr_gray <= wr_gray_next;
            end
        end
    end

    always @(posedge rd_clk) begin
        if (rd_rst) begin
            rd_bin <= 0;
            rd_gray <= 0;
            wr_gray_sync1 <= 0;
            wr_gray_sync2 <= 0;
            rd_data <= 0;
        end else begin
            wr_gray_sync1 <= wr_gray;
            wr_gray_sync2 <= wr_gray_sync1;
            if (rd_en && !rd_empty) begin
                rd_data <= mem[rd_bin[ADDR_WIDTH-1:0]];
                rd_bin <= rd_bin_next;
                rd_gray <= rd_gray_next;
            end
        end
    end
endmodule
