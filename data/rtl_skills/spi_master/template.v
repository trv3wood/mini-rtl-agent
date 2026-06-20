`timescale 1ns/1ps

module spi_master #(
    parameter integer DATA_WIDTH = 8,
    parameter integer CS_WIDTH = 1,
    parameter integer DIV_WIDTH = 16
) (
    input  wire clk,
    input  wire rst,
    input  wire start,
    input  wire [DATA_WIDTH-1:0] tx_data,
    output reg  [DATA_WIDTH-1:0] rx_data,
    output reg  busy,
    output reg  done,
    output reg  sclk,
    output reg  mosi,
    input  wire miso,
    output reg  [CS_WIDTH-1:0] cs_n
);
    reg [$clog2(DATA_WIDTH):0] bit_count;
    reg [DATA_WIDTH-1:0] tx_shift;

    always @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0;
            done <= 1'b0;
            sclk <= 1'b0;
            mosi <= 1'b0;
            cs_n <= {CS_WIDTH{1'b1}};
            bit_count <= 0;
            tx_shift <= 0;
            rx_data <= 0;
        end else begin
            done <= 1'b0;
            if (!busy && start) begin
                busy <= 1'b1;
                cs_n <= {{(CS_WIDTH-1){1'b1}}, 1'b0};
                bit_count <= DATA_WIDTH;
                tx_shift <= {tx_data[DATA_WIDTH-2:0], 1'b0};
                mosi <= tx_data[DATA_WIDTH-1];
                rx_data <= 0;
                sclk <= 1'b0;
            end else if (busy) begin
                sclk <= ~sclk;
                rx_data <= {rx_data[DATA_WIDTH-2:0], miso};
                bit_count <= bit_count - 1'b1;
                mosi <= tx_shift[DATA_WIDTH-1];
                tx_shift <= {tx_shift[DATA_WIDTH-2:0], 1'b0};
                if (bit_count == 1) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    cs_n <= {CS_WIDTH{1'b1}};
                    sclk <= 1'b0;
                end
            end
        end
    end
endmodule
