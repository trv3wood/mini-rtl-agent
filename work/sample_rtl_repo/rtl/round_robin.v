// Round-robin arbiter example.
module round_robin #(
    parameter PORTS = 4
) (
    input wire clk,
    input wire rst_n,
    input wire [PORTS-1:0] request,
    output reg [PORTS-1:0] grant,
    output reg valid
);
    reg [1:0] pointer;

    always @(posedge clk) begin
        if (!rst_n) begin
            grant <= 0;
            valid <= 0;
            pointer <= 0;
        end else begin
            valid <= |request;
            grant <= request;
            pointer <= pointer + 1'b1;
        end
    end
endmodule
