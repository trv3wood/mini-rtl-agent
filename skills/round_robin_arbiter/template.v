`timescale 1ns/1ps

module round_robin_arbiter #(
    parameter integer PORTS = 4
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire [PORTS-1:0]      request,
    input  wire                  acknowledge,
    output reg  [PORTS-1:0]      grant,
    output wire                  grant_valid,
    output reg  [$clog2(PORTS)-1:0] grant_encoded
);
    integer i;
    integer idx;
    reg [$clog2(PORTS)-1:0] pointer;

    assign grant_valid = |grant;

    always @* begin
        grant = {PORTS{1'b0}};
        grant_encoded = pointer;
        for (i = 0; i < PORTS; i = i + 1) begin
            idx = pointer + i;
            if (idx >= PORTS) idx = idx - PORTS;
            if (grant == {PORTS{1'b0}} && request[idx]) begin
                grant[idx] = 1'b1;
                grant_encoded = idx[$clog2(PORTS)-1:0];
            end
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            pointer <= 0;
        end else if (grant_valid && acknowledge) begin
            if (grant_encoded == PORTS-1) pointer <= 0;
            else pointer <= grant_encoded + 1'b1;
        end
    end
endmodule
