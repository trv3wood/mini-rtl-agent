`timescale 1ns/1ps

module example_round_robin_arbiter(input wire clk, input wire rst, input wire [3:0] request, input wire acknowledge, output wire [3:0] grant, output wire grant_valid, output wire [1:0] grant_encoded);
    round_robin_arbiter #(.PORTS(4)) u_arb (.clk(clk), .rst(rst), .request(request), .acknowledge(acknowledge), .grant(grant), .grant_valid(grant_valid), .grant_encoded(grant_encoded));
endmodule
