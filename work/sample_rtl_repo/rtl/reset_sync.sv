// Reset synchronizer example.
module reset_sync (
    input logic clk,
    input logic async_reset,
    output logic sync_reset
);
    logic [1:0] sync_reg;

    always_ff @(posedge clk or posedge async_reset) begin
        if (async_reset) begin
            sync_reg <= 2'b11;
        end else begin
            sync_reg <= {sync_reg[0], 1'b0};
        end
    end

    assign sync_reset = sync_reg[1];
endmodule
