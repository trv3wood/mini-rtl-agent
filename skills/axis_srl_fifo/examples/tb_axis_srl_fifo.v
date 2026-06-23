`timescale 1ns/1ps

module tb_axis_srl_fifo;
    reg clk = 0;
    reg rst = 1;
    reg [7:0] s_axis_tdata = 0;
    reg s_axis_tvalid = 0;
    wire s_axis_tready;
    wire [7:0] m_axis_tdata;
    wire m_axis_tvalid;
    reg m_axis_tready = 0;

    axis_srl_fifo dut (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(s_axis_tdata),
        .s_axis_tvalid(s_axis_tvalid),
        .s_axis_tready(s_axis_tready),
        .m_axis_tdata(m_axis_tdata),
        .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready)
    );

    always #5 clk = ~clk;

    task push(input [7:0] value);
        begin
            @(negedge clk);
            s_axis_tdata = value;
            s_axis_tvalid = 1'b1;
            while (!s_axis_tready) @(negedge clk);
            @(negedge clk);
            s_axis_tvalid = 1'b0;
        end
    endtask

    task pop_expect(input [7:0] value);
        begin
            @(negedge clk);
            m_axis_tready = 1'b1;
            while (!m_axis_tvalid) @(negedge clk);
            if (m_axis_tdata !== value) begin
                $display("expected %0h got %0h", value, m_axis_tdata);
                $fatal;
            end
            @(negedge clk);
            m_axis_tready = 1'b0;
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst = 1'b0;

        push(8'ha1);
        push(8'ha2);
        push(8'ha3);
        pop_expect(8'ha1);
        push(8'ha4);
        pop_expect(8'ha2);
        pop_expect(8'ha3);
        pop_expect(8'ha4);

        $display("tb_axis_srl_fifo passed");
        $finish;
    end
endmodule
