"""FireSim's Nitefury II shell on rules_vivado's own rules, without a block design.

Opt-in: firesim_bitstream, which runs the board project's own script, stays
the default. This shell builds the same design with vivado_ip per core,
vivado_synthesis2 and vivado_place_and_route2, so cores and synthesis are
cached on their own. On FireSim's Nitefury Rocket recipe it met timing at
WNS +0.152 ns with 92,263 LUTs (the board script's build: +0.318 ns,
92,354 LUTs). Its PCIe lane map (below) is checked by Vivado but not yet on
a board.
"""

load("@rules_vivado//build/vivado:rules.bzl", "vivado_place_and_route2", "vivado_synthesis2")

PART = "xc7a200tfbg484-2"

_PKG = "//firesim/nitefury_shell:"

IPS = [Label(_PKG + n) for n in [
    "Top_xdma_0_0",
    "Top_mig_7series_0_0",
    "Top_clk_wiz_0_0",
    "Top_xadc_wiz_0_0",
    "Top_proc_sys_reset_0_0",
    "Top_util_ds_buf_0",
    "Top_axi_clock_converter_1_0",
    "Top_axi_interconnect_0_imp_auto_cc_0",
    "Top_axi_interconnect_2_imp_auto_us_0",
    "Top_axi_interconnect_2_imp_auto_cc_0",
]]

# The board's PCIe lane map, from the board project's early.xdc: lane 3 on
# GTPE2_CHANNEL_X0Y7, 0 on Y6, 2 on Y5, 1 on Y4. XDMA's own XDC puts lane n
# on Y(7-n), and the block design flow overrode it by reading early.xdc
# first. Here the IP's XDC comes first, and no XDC order can swap three
# occupied sites, so this clears and sets the four LOCs after synthesis (the
# checkpoint keeps them), then checks every PCIe pin landed where the board
# wires it.
_GT = "Top_i/xdma_0/inst/Top_xdma_0_0_pcie2_to_pcie3_wrapper_i/pcie2_ip_i/inst/inst/gt_top_i/pipe_wrapper_i/pipe_lane[%d].gt_wrapper_i/gtp_channel.gtpe2_channel_i"
_LANES = [(3, "X0Y7"), (0, "X0Y6"), (2, "X0Y5"), (1, "X0Y4")]
_PINS = "pcie_mgt_rxn[0] A10 pcie_mgt_rxp[0] B10 pcie_mgt_txn[0] A6 pcie_mgt_txp[0] B6 pcie_mgt_rxn[1] A8 pcie_mgt_rxp[1] B8 pcie_mgt_txn[1] A4 pcie_mgt_txp[1] B4 pcie_mgt_rxn[2] C11 pcie_mgt_rxp[2] D11 pcie_mgt_txn[2] C5 pcie_mgt_txp[2] D5 pcie_mgt_rxn[3] C9 pcie_mgt_rxp[3] D9 pcie_mgt_txn[3] C7 pcie_mgt_txp[3] D7"

LANE_MAP = [
    "reset_property LOC [get_cells {%s}]" % (_GT % lane)
    for lane, _ in _LANES
] + [
    "set_property LOC GTPE2_CHANNEL_%s [get_cells {%s}]" % (site, _GT % lane)
    for lane, site in _LANES
] + [
    "foreach {port pin} {%s} { if {[get_property PACKAGE_PIN [get_ports $port]] ne $pin} { puts \"ERROR: $port is on [get_property PACKAGE_PIN [get_ports $port]], the board has it on $pin\"; exit 1 } }" % _PINS,
    "puts \"PCIe lane map: 16 pins as the board wires them\"",
]

# Prints where each PCIe lane's transceiver is.
LANES = [
    "foreach c [get_cells -hier -filter {REF_NAME == GTPE2_CHANNEL}] { puts \"LANE $c [get_property LOC $c]\" }",
]
def firesim_nitefury_shell(name, design, **kwargs):
    """A design's Nitefury II bitstream through rules_vivado's own rules.

    Makes <name>_synth (vivado_synthesis2) and <name> (vivado_place_and_route2;
    its outputs include <name>.bit).

    Args:
      name: the place-and-route target's name.
      design: a firesim_goldengate target.
      **kwargs: passed to both targets (tags, for one: they are long, so
        mark them manual).
    """
    native.filegroup(name = name + "_sv", srcs = [design], output_group = "sv")

    # The board project's constraint sets: early.xdc and Golden Gate's
    # synthesis XDC first, then normal.xdc, all in synthesis (the checkpoint
    # keeps them); Golden Gate's implementation XDC in implementation only.
    native.filegroup(name = name + "_gg_synth_xdc", srcs = [design], output_group = "synthesis_xdc")
    native.filegroup(name = name + "_gg_impl_xdc", srcs = [design], output_group = "implementation_xdc")
    native.filegroup(
        name = name + "_synth_xdc",
        srcs = [
            Label(_PKG + "early"),
            ":" + name + "_gg_synth_xdc",
            Label(_PKG + "normal"),
        ],
    )
    vivado_synthesis2(
        name = name + "_synth",
        srcs = [Label(_PKG + "board_srcs"), ":" + name + "_sv"],
        part = PART,
        post_synth_design = LANE_MAP + LANES,
        top = "nitefury_top",
        xdcs = [":" + name + "_synth_xdc"],
        deps = IPS,
        **kwargs
    )

    # The board project's implementation steps (Vivado's Implementation
    # Defaults): opt, place, phys_opt, route.
    vivado_place_and_route2(
        name = name,
        post_place_design = ["phys_opt_design"],
        post_route_design = LANES,
        synthesis = ":" + name + "_synth",
        xdcs = [":" + name + "_gg_impl_xdc"],
        **kwargs
    )
