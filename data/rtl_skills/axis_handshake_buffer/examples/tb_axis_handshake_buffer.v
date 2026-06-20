`timescale 1ns/1ps

module tb_axis_handshake_buffer;
    reg clk = 0;
    reg rst = 1;
    reg [7:0] s_data = 0;
    reg s_valid = 0;
    wire s_ready;
    wire [7:0] m_data;
    wire m_valid;
    reg m_ready = 0;

    axis_handshake_buffer dut (
        .clk(clk), .rst(rst),
        .s_axis_tdata(s_data), .s_axis_tvalid(s_valid), .s_axis_tready(s_ready),
        .m_axis_tdata(m_data), .m_axis_tvalid(m_valid), .m_axis_tready(m_ready)
    );

    always #5 clk = ~clk;

    initial begin
        repeat (2) @(posedge clk);
        rst <= 0;
        @(posedge clk);
        s_data <= 8'h3c;
        s_valid <= 1;
        m_ready <= 0;
        @(posedge clk);
        s_valid <= 0;
        @(negedge clk);
        if (!m_valid || m_data !== 8'h3c) $fatal(1, "buffer did not capture data");
        if (s_ready) $fatal(1, "input ready should be low while full and stalled");
        repeat (2) @(posedge clk);
        if (m_data !== 8'h3c) $fatal(1, "data changed under backpressure");
        m_ready <= 1;
        @(posedge clk);
        @(negedge clk);
        if (m_valid) $fatal(1, "valid did not clear after output handshake");
        $display("PASS axis_handshake_buffer");
        $finish;
    end
endmodule
