`timescale 1ns/1ps

module tb_wishbone_reg_block;
    reg clk = 0, rst = 1;
    reg [2:0] adr = 0;
    reg [7:0] dat_i = 0;
    wire [7:0] dat_o;
    reg we = 0, stb = 0, cyc = 0;
    wire ack, irq;
    wishbone_reg_block dut (.clk(clk), .rst(rst), .wb_adr_i(adr), .wb_dat_i(dat_i), .wb_dat_o(dat_o), .wb_we_i(we), .wb_stb_i(stb), .wb_cyc_i(cyc), .wb_ack_o(ack), .irq_o(irq));
    always #5 clk = ~clk;

    task wb_write(input [2:0] a, input [7:0] d); begin
        @(negedge clk); adr = a; dat_i = d; we = 1; stb = 1; cyc = 1;
        @(posedge clk); @(negedge clk); stb = 0; cyc = 0; we = 0;
    end endtask
    task wb_read(input [2:0] a, input [7:0] e); begin
        @(negedge clk); adr = a; we = 0; stb = 1; cyc = 1;
        @(posedge clk); @(negedge clk); stb = 0; cyc = 0;
        if (dat_o !== e) $fatal(1, "read addr %0d expected %h got %h", a, e, dat_o);
    end endtask

    initial begin
        repeat (2) @(posedge clk); rst = 0;
        wb_write(0, 8'h01);
        wb_write(1, 8'h5a);
        wb_read(0, 8'h01);
        wb_read(1, 8'h5a);
        wb_write(0, 8'h03);
        repeat (2) @(posedge clk);
        if (!irq) $fatal(1, "irq should be pending and enabled");
        wb_write(2, 8'h01);
        repeat (2) @(posedge clk);
        if (irq) $fatal(1, "irq should clear");
        $display("PASS wishbone_reg_block");
        $finish;
    end
endmodule
