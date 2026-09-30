`timescale 1ns/1ps
`default_nettype none

// Adapts Synapse32's no-ready CPU memory port to a one-outstanding-request
// ready/valid bus.  This block is clock-enable logic only: the board must use
// cpu_step as the CE of a BUFGCE (or equivalent clock-enable primitive), never
// as a fabric-gated clock.
//
// rst is synchronous and active high.  RESET_PC is the CPU's reset vector.
// The bus reset must be coordinated with this reset: a reset can withdraw a
// request or response-ready indication, so the bus target must be reset too.
// ready_to_run is a board run-permission input (currently PLL-stable && !rst),
// not the DDR controller's init_done/calibration indication.  It gates this
// system-domain sequencer before the BUFGCE samples cpu_step.  Once BUFGCE has
// sampled CE high on its falling edge, a later ready_to_run loss cannot retract
// that already-armed CPU rising edge; the board must treat that edge as part of
// the clock-enable contract rather than claim a no-retire guarantee.
module synapse32_memory_sequencer #(
    parameter logic [31:0] RESET_PC = 32'h8000_0000,
    parameter integer FETCH_ENTRIES = 16
) (
    input  logic        clk,
    input  logic        rst,
    input  logic        ready_to_run,

    input  logic [31:0] cpu_pc,
    input  logic        cpu_rd_en,
    input  logic        cpu_wr_en,
    input  logic [31:0] cpu_rd_addr,
    input  logic [31:0] cpu_wr_addr,
    input  logic [31:0] cpu_wdata,
    input  logic [3:0]  cpu_wstrb,
    input  logic [2:0]  cpu_load_type,
    output logic [31:0] cpu_instr,
    output logic [31:0] cpu_rdata,
    output logic        cpu_step,
    output logic        fault,

    output logic        req_valid,
    input  logic        req_ready,
    output logic        req_write,
    output logic [31:0] req_addr,
    output logic [31:0] req_wdata,
    output logic [3:0]  req_wstrb,

    input  logic        resp_valid,
    output logic        resp_ready,
    input  logic [31:0] resp_rdata,
    input  logic        resp_error
);

    localparam logic [2:0] LOAD_BYTE   = 3'b000;
    localparam logic [2:0] LOAD_HALF   = 3'b001;
    localparam logic [2:0] LOAD_WORD   = 3'b010;
    localparam logic [2:0] LOAD_BYTE_U = 3'b100;
    localparam logic [2:0] LOAD_HALF_U = 3'b101;

    typedef enum logic [3:0] {
        ST_BOOT_WAIT,
        ST_FETCH_REQ,
        ST_FETCH_WAIT,
        ST_STEP_EDGE,
        ST_SETTLE,
        ST_DATA_REQ,
        ST_DATA_WAIT,
        ST_FAULT
    } state_t;

    // Isolated experiment: demand-only direct-mapped reuse of the default
    // SoC's 64 KiB boot RAM. No prefetch, data caching, or PC-based data dedup.
    // Requires the default boot map and all boot writers to use this port
    // (or coordinate reset). This interface has no external snoop input.
    // FETCH_ENTRIES must be a power of two >= 2.
    localparam integer INDEX_BITS = $clog2(FETCH_ENTRIES);
    logic [31:0] fetch_addr;
    logic [FETCH_ENTRIES-1:0] fetch_valid;
    logic [31:0] fetch_tags [0:FETCH_ENTRIES-1];
    logic [31:0] fetch_words [0:FETCH_ENTRIES-1];
    wire [INDEX_BITS-1:0] fetch_index = fetch_addr[INDEX_BITS+1:2];
    wire boot_fetch = fetch_addr[31:16] == 16'h8000;
    wire fetch_hit = boot_fetch && fetch_valid[fetch_index] &&
                     fetch_tags[fetch_index] == fetch_addr;
    initial begin
        if (FETCH_ENTRIES < 2 || (FETCH_ENTRIES & (FETCH_ENTRIES-1)) != 0)
            $fatal(1, "FETCH_ENTRIES must be a power of two >= 2");
    end

    state_t state;
    logic [31:0] request_addr;
    logic [31:0] request_wdata;
    logic [3:0]  request_wstrb;
    logic        request_write;
    logic [1:0]  load_offset;
    logic [2:0]  load_type_latched;
    logic        step_pending;

    function automatic logic valid_load(input logic [2:0] kind,
                                         input logic [1:0] offset);
        begin
            case (kind)
                LOAD_BYTE, LOAD_BYTE_U: valid_load = 1'b1;
                LOAD_HALF, LOAD_HALF_U: valid_load = (offset[0] == 1'b0);
                LOAD_WORD: valid_load = (offset == 2'b00);
                default: valid_load = 1'b0;
            endcase
        end
    endfunction

    function automatic logic valid_store(input logic [31:0] address,
                                          input logic [3:0]  strobe);
        begin
            case (strobe)
                4'b0001: valid_store = 1'b1; // SB: byte offset is in address.
                4'b0011: valid_store = (address[0] == 1'b0); // SH.
                4'b1111: valid_store = (address[1:0] == 2'b00); // SW.
                default: valid_store = 1'b0;
            endcase
        end
    endfunction

    function automatic logic [31:0] extract_load(
        input logic [31:0] raw,
        input logic [1:0]  offset,
        input logic [2:0]  kind
    );
        logic [31:0] shifted;
        begin
            shifted = raw >> (offset * 8);
            case (kind)
                LOAD_BYTE, LOAD_BYTE_U: extract_load = {24'b0, shifted[7:0]};
                LOAD_HALF, LOAD_HALF_U: extract_load = {16'b0, shifted[15:0]};
                LOAD_WORD: extract_load = raw;
                default: extract_load = 32'b0;
            endcase
        end
    endfunction

    always_comb begin
        // These are latched before req_valid is asserted and therefore remain
        // stable for the whole request backpressure interval.
        req_write = (state == ST_FETCH_REQ) ? 1'b0 : request_write;
        req_addr = (state == ST_FETCH_REQ) ? fetch_addr : request_addr;
        req_wdata = (state == ST_FETCH_REQ) ? 32'b0 : request_wdata;
        req_wstrb = (state == ST_FETCH_REQ) ? 4'b0 : request_wstrb;

        req_valid = (((state == ST_FETCH_REQ) && !fetch_hit) || (state == ST_DATA_REQ)) &&
                    ready_to_run && !fault;
        resp_ready = ((state == ST_FETCH_WAIT) || (state == ST_DATA_WAIT)) &&
                     ready_to_run && !fault;

        // Gate the sequencer-side enable.  The board's BUFGCE samples this
        // signal on its falling edge; after that sample the upcoming CPU edge
        // is already armed and cannot be withdrawn by this combinational gate.
        cpu_step = step_pending && ready_to_run && !fault;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            fetch_valid       <= '0;
            state             <= ST_BOOT_WAIT;
            fault             <= 1'b0;
            cpu_instr         <= 32'b0;
            cpu_rdata         <= 32'b0;
            fetch_addr        <= RESET_PC;
            request_addr      <= 32'b0;
            request_wdata     <= 32'b0;
            request_wstrb     <= 4'b0;
            request_write     <= 1'b0;
            load_offset       <= 2'b0;
            load_type_latched <= LOAD_WORD;
            step_pending      <= 1'b0;
        end else begin
            // step_pending is a one-cycle registered pulse.  ST_STEP_EDGE is
            // intentionally followed by ST_SETTLE so CPU outputs are sampled
            // one complete system cycle after the enabled CPU edge.
            step_pending <= 1'b0;

            if (state != ST_BOOT_WAIT && state != ST_FAULT && !ready_to_run) begin
                fault <= 1'b1;
                state <= ST_FAULT;
            end else begin
                case (state)
                    ST_BOOT_WAIT: begin
                        if (ready_to_run) begin
                            if (RESET_PC[1:0] != 2'b00) begin
                                fault <= 1'b1;
                                state <= ST_FAULT;
                            end else begin
                                state <= ST_FETCH_REQ;
                            end
                        end
                    end

                    ST_FETCH_REQ: begin
                        // Register the instruction/CE just as on a bus response.
                        // ST_STEP_EDGE and the full ST_SETTLE cycle are unchanged.
                        if (fetch_hit) begin
                            cpu_instr <= fetch_words[fetch_index];
                            step_pending <= 1'b1;
                            state <= ST_STEP_EDGE;
                        end else if (req_ready) begin
                            request_write <= 1'b0;
                            state <= ST_FETCH_WAIT;
                        end
                    end

                    ST_FETCH_WAIT: begin
                        if (resp_valid && resp_ready) begin
                            if (resp_error) begin
                                fault <= 1'b1;
                                state <= ST_FAULT;
                            end else begin
                                if (boot_fetch) begin
                                    fetch_valid[fetch_index] <= 1'b1;
                                    fetch_tags[fetch_index] <= fetch_addr;
                                    fetch_words[fetch_index] <= resp_rdata;
                                end
                                cpu_instr <= resp_rdata;
                                step_pending <= 1'b1;
                                state <= ST_STEP_EDGE;
                            end
                        end
                    end

                    ST_STEP_EDGE: begin
                        // The CPU sees cpu_step high at this edge.  Do not
                        // inspect its newly changed combinational outputs yet.
                        state <= ST_SETTLE;
                    end

                    ST_SETTLE: begin
                        // Validate the PC before any data or instruction bus
                        // side effect.  A data request is sampled exactly once
                        // here, even if the CPU leaves its enables asserted.
                        if (cpu_pc[1:0] != 2'b00) begin
                            fault <= 1'b1;
                            state <= ST_FAULT;
                        end else if (cpu_rd_en && cpu_wr_en) begin
                            fault <= 1'b1;
                            state <= ST_FAULT;
                        end else if (cpu_rd_en) begin
                            if (!valid_load(cpu_load_type, cpu_rd_addr[1:0])) begin
                                fault <= 1'b1;
                                state <= ST_FAULT;
                            end else begin
                                request_write <= 1'b0;
                                request_addr <= {cpu_rd_addr[31:2], 2'b00};
                                request_wdata <= 32'b0;
                                request_wstrb <= 4'b0;
                                load_offset <= cpu_rd_addr[1:0];
                                load_type_latched <= cpu_load_type;
                                fetch_addr <= cpu_pc;
                                state <= ST_DATA_REQ;
                            end
                        end else if (cpu_wr_en) begin
                            if (!valid_store(cpu_wr_addr, cpu_wstrb)) begin
                                fault <= 1'b1;
                                state <= ST_FAULT;
                            end else begin
                                // Whole-buffer invalidation before a boot store
                                // reaches the bus, including partial/failed writes.
                                if (cpu_wr_addr[31:16] == 16'h8000)
                                    fetch_valid <= '0;
                                request_write <= 1'b1;
                                request_addr <= {cpu_wr_addr[31:2], 2'b00};
                                request_wdata <= cpu_wdata << (cpu_wr_addr[1:0] * 8);
                                request_wstrb <= cpu_wstrb << cpu_wr_addr[1:0];
                                fetch_addr <= cpu_pc;
                                state <= ST_DATA_REQ;
                            end
                        end else begin
                            fetch_addr <= cpu_pc;
                            state <= ST_FETCH_REQ;
                        end
                    end

                    ST_DATA_REQ: begin
                        if (req_ready)
                            state <= ST_DATA_WAIT;
                    end

                    ST_DATA_WAIT: begin
                        if (resp_valid && resp_ready) begin
                            if (resp_error) begin
                                fault <= 1'b1;
                                state <= ST_FAULT;
                            end else begin
                                if (!request_write)
                                    cpu_rdata <= extract_load(resp_rdata, load_offset,
                                                               load_type_latched);
                                state <= ST_FETCH_REQ;
                            end
                        end
                    end

                    ST_FAULT: begin
                        // Sticky until synchronous reset.
                        fault <= 1'b1;
                    end

                    default: begin
                        fault <= 1'b1;
                        state <= ST_FAULT;
                    end
                endcase
            end
        end
    end

endmodule
`default_nettype wire
