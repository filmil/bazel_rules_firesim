"""Writes shell/nitefury_top.sv, the Nitefury II FireSim shell without a
block design: the cells and nets of the board project's block design (Top),
with the two axi_interconnects replaced by the cores Vivado put inside them.

The AXI port maps come from the cores' own instantiation templates, so the
widths are the cores'. It is how nitefury_top.sv was written; the build
doesn't run it. To rewrite the top, build the cores
(bazel build @rules_firesim//firesim/nitefury_shell:all), then:

    python3 gen_top.py <bazel-bin/external/rules_firesim+/firesim/nitefury_shell> \
        nitefury_top.sv <firesim_wrapper.sv>

with the board's firesim_wrapper.v copied as firesim_wrapper.sv.
"""
import re, sys

BIN = sys.argv[1]
OUT = sys.argv[2]
WRAPPER = sys.argv[3]

def ports(name):
    s = open(f"{BIN}/{name}.ip_gen/{name}.veo").read()
    out = {}
    for n, d, w in re.findall(r"\.(\w+)\s*\(\s*\w+\s*\)\s*,?\s*//\s*(input|output|inout)\s*(?:wire)?\s*(\[[^\]]*\])?", s):
        w = re.sub(r"\s", "", w or "")
        out[n] = (d, w)
    return out

def wsplit(w):
    if not w: return 1
    a, b = w[1:-1].split(":")
    return int(a) - int(b) + 1

FW = {}  # firesim_wrapper's ports, from its declarations
src = re.sub(r"\(\*.*?\*\)", "", open(WRAPPER).read(), flags=re.S)
for d, w, n in re.findall(r"^\s*(input|output|inout)\s*(\[[^\]]*\])?\s*(\w+)\s*;", src, flags=re.M):
    FW[n] = (d, re.sub(r"\s", "", w or ""))

AXI = ["awid", "awaddr", "awlen", "awsize", "awburst", "awlock", "awcache", "awprot", "awregion", "awqos", "awvalid", "awready",
       "wdata", "wstrb", "wlast", "wvalid", "wready", "bid", "bresp", "bvalid", "bready",
       "arid", "araddr", "arlen", "arsize", "arburst", "arlock", "arcache", "arprot", "arregion", "arqos", "arvalid", "arready",
       "rid", "rdata", "rresp", "rlast", "rvalid", "rready"]
MASTER_DRIVES = {s for s in AXI if s not in ("awready", "wready", "bid", "bresp", "bvalid", "arready", "rid", "rdata", "rresp", "rlast", "rvalid")}

wires, conns = [], {}

def link(bus, m_inst, m_ports, m_pre, s_inst, s_ports, s_pre, ties=None, slices=None):
    """One AXI link: the master's m_pre* ports to the slave's s_pre* ports."""
    ties = ties or {}
    slices = slices or {}
    for sig in AXI:
        mp, sp = m_ports.get(m_pre + sig), s_ports.get(s_pre + sig)
        if mp is None and sp is None:
            continue
        net = f"{bus}_{sig}"
        driver_is_master = sig in MASTER_DRIVES
        drv, rcv = (mp, sp) if driver_is_master else (sp, mp)
        if drv is None:
            # The receiver has the port, the driver doesn't: tie it as the
            # block design did.
            val = ties.get(sig, f"{wsplit(rcv[1])}'b0")
            inst, pre = (s_inst, s_pre) if driver_is_master else (m_inst, m_pre)
            conns.setdefault(inst, []).append((pre + sig, val))
            continue
        width = wsplit(drv[1])
        wires.append(f"  wire [{width - 1}:0] {net};")
        conns.setdefault(m_inst, [])
        conns.setdefault(s_inst, [])
        if mp is not None:
            conns[m_inst].append((m_pre + sig, net))
        if sp is not None:
            if sig in slices:
                conns[s_inst].append((s_pre + sig, slices[sig](net)))
            elif sig in ties and not driver_is_master:
                conns[s_inst].append((s_pre + sig, net))
            else:
                rw = wsplit(sp[1])
                if rw == width:
                    conns[s_inst].append((s_pre + sig, net))
                elif rw > width:
                    # Wider receiver: the block design padded the top bits.
                    pad = ties.get(sig + "_pad", f"{rw - width}'b0")
                    conns[s_inst].append((s_pre + sig, f"{{{pad}, {net}}}"))
                else:
                    conns[s_inst].append((s_pre + sig, f"{net}[{rw - 1}:0]"))

P = {n: ports(n) for n in [
    "Top_xdma_0_0", "Top_mig_7series_0_0", "Top_clk_wiz_0_0", "Top_xadc_wiz_0_0", "Top_proc_sys_reset_0_0",
    "Top_util_ds_buf_0", "Top_axi_clock_converter_1_0", "Top_axi_interconnect_0_imp_auto_cc_0",
    "Top_axi_interconnect_2_imp_auto_us_0", "Top_axi_interconnect_2_imp_auto_cc_0"]}
INST = {
    "xdma_0": "Top_xdma_0_0", "mig_7series_0": "Top_mig_7series_0_0", "clk_wiz_0": "Top_clk_wiz_0_0",
    "xadc_wiz_0": "Top_xadc_wiz_0_0", "proc_sys_reset_0": "Top_proc_sys_reset_0_0", "util_ds_buf": "Top_util_ds_buf_0",
    "axi_clock_converter_1": "Top_axi_clock_converter_1_0",
    "axi_interconnect_0_auto_cc": "Top_axi_interconnect_0_imp_auto_cc_0",
    "axi_interconnect_2_auto_us": "Top_axi_interconnect_2_imp_auto_us_0",
    "axi_interconnect_2_auto_cc": "Top_axi_interconnect_2_imp_auto_cc_0",
    "firesim_wrapper_0": "Top_firesim_wrapper_0_0",
}
PI = {i: (P[m] if m in P else FW) for i, m in INST.items()}

# DMA: XDMA's AXI master, through the clock converter, into FireSim. The
# wrapper's write strobe is 64 bits for 128 bits of data; the block design
# set the 48 bits above the converter's 16 to ones.
link("dma_x", "xdma_0", PI["xdma_0"], "m_axi_", "axi_clock_converter_1", PI["axi_clock_converter_1"], "s_axi_")
link("dma_h", "axi_clock_converter_1", PI["axi_clock_converter_1"], "m_axi_", "firesim_wrapper_0", FW, "S_AXI_DMA_",
     ties={"wstrb_pad": "{48{1'b1}}"})
# Control: XDMA's AXI4-Lite master, through a clock converter, into FireSim.
link("ctl_x", "xdma_0", PI["xdma_0"], "m_axil_", "axi_interconnect_0_auto_cc", PI["axi_interconnect_0_auto_cc"], "s_axi_")
link("ctl_h", "axi_interconnect_0_auto_cc", PI["axi_interconnect_0_auto_cc"], "m_axi_", "firesim_wrapper_0", FW, "S_AXI_CTRL_")
# DRAM: FireSim's memory port, up to 128 bits, across to the MIG's clock,
# into the MIG, which takes the low 30 address bits and IDs of zero.
link("ddr_h", "firesim_wrapper_0", FW, "M_AXI_DDR0_", "axi_interconnect_2_auto_us", PI["axi_interconnect_2_auto_us"], "s_axi_")
link("ddr_w", "axi_interconnect_2_auto_us", PI["axi_interconnect_2_auto_us"], "m_axi_", "axi_interconnect_2_auto_cc", PI["axi_interconnect_2_auto_cc"], "s_axi_")
link("ddr_m", "axi_interconnect_2_auto_cc", PI["axi_interconnect_2_auto_cc"], "m_axi_", "mig_7series_0", PI["mig_7series_0"], "s_axi_",
     slices={"awaddr": lambda n: f"{n}[29:0]", "araddr": lambda n: f"{n}[29:0]"})

def add(inst, pairs):
    conns.setdefault(inst, []).extend(pairs)

# Clocks and resets, net by net as the block design has them.
add("xdma_0", [("sys_clk", "pcie_refclk"), ("sys_rst_n", "pci_reset"), ("axi_aclk", "xdma_clk"), ("axi_aresetn", "xdma_aresetn"),
               ("user_lnk_up", "LED_A3"), ("usr_irq_req", "1'b0"),
               ("pci_exp_rxn", "pcie_mgt_rxn"), ("pci_exp_rxp", "pcie_mgt_rxp"), ("pci_exp_txn", "pcie_mgt_txn"), ("pci_exp_txp", "pcie_mgt_txp")])
add("util_ds_buf", [("IBUF_DS_P", "pcie_clkin_clk_p"), ("IBUF_DS_N", "pcie_clkin_clk_n"), ("IBUF_OUT", "pcie_refclk")])
add("axi_clock_converter_1", [("s_axi_aclk", "xdma_clk"), ("s_axi_aresetn", "xdma_aresetn"), ("m_axi_aclk", "host_clk"), ("m_axi_aresetn", "host_aresetn")])
add("axi_interconnect_0_auto_cc", [("s_axi_aclk", "xdma_clk"), ("s_axi_aresetn", "xdma_aresetn"), ("m_axi_aclk", "host_clk"), ("m_axi_aresetn", "host_aresetn")])
add("axi_interconnect_2_auto_us", [("s_axi_aclk", "host_clk"), ("s_axi_aresetn", "host_aresetn")])
add("axi_interconnect_2_auto_cc", [("s_axi_aclk", "host_clk"), ("s_axi_aresetn", "host_aresetn"), ("m_axi_aclk", "ui_clk"), ("m_axi_aresetn", "ui_aresetn")])
add("firesim_wrapper_0", [("sys_clk_30", "host_clk"), ("sys_reset_n", "host_aresetn")])
add("clk_wiz_0", [("clk_in1", "ui_clk"), ("reset", "ui_clk_sync_rst"), ("clk_out1", "host_clk")])
add("proc_sys_reset_0", [("slowest_sync_clk", "host_clk"), ("ext_reset_in", "1'b1"), ("aux_reset_in", "1'b1"), ("mb_debug_sys_rst", "1'b0"),
                         ("dcm_locked", "1'b1"), ("interconnect_aresetn", "host_aresetn")])
add("mig_7series_0", [("sys_clk_p", "sys_clk_clk_p"), ("sys_clk_n", "sys_clk_clk_n"), ("sys_rst", "1'b1"), ("aresetn", "1'b1"),
                      ("device_temp_i", "temp"), ("init_calib_complete", "LED_A4"), ("ui_clk", "ui_clk"),
                      ("ui_clk_sync_rst", "ui_clk_sync_rst"), ("ui_addn_clk_0", "blink_clk"),
                      # Unconnected in the block design, so at their default.
                      ("app_sr_req", "1'b0"), ("app_ref_req", "1'b0"), ("app_zq_req", "1'b0")] +
    [(f"ddr3_{s}", f"DDR3_{s}") for s in ["addr", "ba", "cas_n", "ck_n", "ck_p", "cke", "dm", "dq", "dqs_n", "dqs_p", "odt", "ras_n", "reset_n", "we_n"]])
# The XADC's AXI port is unused; the block design tied it off.
add("xadc_wiz_0", [("s_axi_aclk", "xdma_clk"), ("s_axi_aresetn", "xdma_aresetn"), ("s_axi_awaddr", "11'b0"), ("s_axi_awvalid", "1'b0"),
                   ("s_axi_wdata", "32'b0"), ("s_axi_wstrb", "4'b1111"), ("s_axi_wvalid", "1'b0"), ("s_axi_bready", "1'b0"),
                   ("s_axi_araddr", "11'b0"), ("s_axi_arvalid", "1'b0"), ("s_axi_rready", "1'b0"), ("vp_in", "1'b0"), ("vn_in", "1'b0"),
                   ("temp_out", "temp")])

def inst_text(inst):
    mod = INST[inst]
    lines = [f"  {mod} {inst} ("]
    cs = conns[inst]
    for k, (p, v) in enumerate(cs):
        lines.append(f"    .{p}({v}){',' if k < len(cs) - 1 else ''}")
    lines.append("  );")
    return "\n".join(lines)

fw_ports = ",\n".join(f"    {d} {w + ' ' if w else ''}{n}" for n, (d, w) in FW.items())
out = f'''// The Nitefury II FireSim shell without a block design. Generated by
// tools/gen_top.py from the board project's block design (Top) as Vivado
// 2025.2 resolves it: the same cells under the same instance names, so the
// board's XDC and Golden Gate's, which name paths under Top_i, apply as
// they are. The two axi_interconnects are the cores Vivado put inside
// them: a clock converter for axi_interconnect_0, an upsizer and a clock
// converter for axi_interconnect_2. The xlconstant, xlslice and
// util_vector_logic cells are the assignments below.

// The block design's module reference to firesim_wrapper, by the name the
// constraints expect: Top_i/firesim_wrapper_0/inst.
module Top_firesim_wrapper_0_0 (
{fw_ports}
);
  firesim_wrapper inst (.*);
endmodule

module nitefury_shell (
  output [15:0] DDR3_addr,
  output [2:0] DDR3_ba,
  output DDR3_cas_n,
  output [0:0] DDR3_ck_n,
  output [0:0] DDR3_ck_p,
  output [0:0] DDR3_cke,
  output [1:0] DDR3_dm,
  inout [15:0] DDR3_dq,
  inout [1:0] DDR3_dqs_n,
  inout [1:0] DDR3_dqs_p,
  output [0:0] DDR3_odt,
  output DDR3_ras_n,
  output DDR3_reset_n,
  output DDR3_we_n,
  output [0:0] LED_A1,
  output [0:0] LED_A2,
  output [0:0] LED_A3,
  output [0:0] LED_A4,
  output [0:0] LED_M2,
  input pci_reset,
  input [0:0] pcie_clkin_clk_n,
  input [0:0] pcie_clkin_clk_p,
  output [0:0] pcie_clkreq_l,
  input [3:0] pcie_mgt_rxn,
  input [3:0] pcie_mgt_rxp,
  output [3:0] pcie_mgt_txn,
  output [3:0] pcie_mgt_txp,
  output [0:0] real_spi_ss,
  input sys_clk_clk_n,
  input sys_clk_clk_p
);
  wire pcie_refclk, xdma_clk, xdma_aresetn;
  wire host_clk, host_aresetn;
  wire ui_clk, ui_clk_sync_rst, blink_clk;
  wire [11:0] temp;

  // util_vector_logic_0: the MIG side's active-low reset.
  wire ui_aresetn = ~ui_clk_sync_rst;
  // xlconstant_1: PCIe CLKREQ# held low (and the interrupt request, below).
  assign pcie_clkreq_l = 1'b0;
  // xlslice_D0, xlslice_D1, xlslice_D4_D2: their input was a GPIO block the
  // block design no longer has, so it was tied to zero.
  assign LED_A2 = 1'b0;
  assign LED_M2 = 1'b0;
  // real_spi_ss is left undriven, as in the block design.

{chr(10).join(wires)}

{chr(10).join(inst_text(i) for i in INST)}

  // const_true1 and the blinker on LED_A1.
  CodeBlinker CodeBlinker_3 (.clk(blink_clk), .code(3'b000), .ok(1'b1), .led(LED_A1));
endmodule

// Top_wrapper's place: the board's ports, and the shell as Top_i.
module nitefury_top (
  output [15:0] DDR3_addr, output [2:0] DDR3_ba, output DDR3_cas_n,
  output [0:0] DDR3_ck_n, output [0:0] DDR3_ck_p, output [0:0] DDR3_cke,
  output [1:0] DDR3_dm, inout [15:0] DDR3_dq, inout [1:0] DDR3_dqs_n,
  inout [1:0] DDR3_dqs_p, output [0:0] DDR3_odt, output DDR3_ras_n,
  output DDR3_reset_n, output DDR3_we_n,
  output [0:0] LED_A1, output [0:0] LED_A2, output [0:0] LED_A3,
  output [0:0] LED_A4, output [0:0] LED_M2,
  input pci_reset, input [0:0] pcie_clkin_clk_n, input [0:0] pcie_clkin_clk_p,
  output [0:0] pcie_clkreq_l, input [3:0] pcie_mgt_rxn, input [3:0] pcie_mgt_rxp,
  output [3:0] pcie_mgt_txn, output [3:0] pcie_mgt_txp, output [0:0] real_spi_ss,
  input sys_clk_clk_n, input sys_clk_clk_p
);
  nitefury_shell Top_i (.*);
endmodule
'''
open(OUT, "w").write(out)
print("wrote", OUT, "with", len(wires), "AXI nets")
