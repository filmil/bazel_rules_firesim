"""FireSim's build flow as Bazel rules: elaborate, Golden Gate, driver, bitstream.

    firesim_elaborate   the target design, to legacy SFC FIRRTL
    firesim_goldengate  Golden Gate: FireSim-generated.sv, its header and XDCs
    firesim_driver      the host driver for one design and platform
    firesim_bitstream   the board project's own build script, under Vivado
"""

load("@rules_cc//cc:defs.bzl", "cc_binary", "cc_library")

# rules_vivado 4.1.1 does not export vivado_config from rules.bzl yet.
load("@rules_vivado//internal:toolchain.bzl", _vivado_config = "vivado_config")

# rules_vivado exports the toolchain type as a bare string, which resolves in
# the caller's repository (rules_vivado issue 159); this is the label it means.
_VIVADO_TOOLCHAIN_TYPE = "@rules_vivado//toolchains:toolchain_type"

# Chisel records each source locator as the file's real path minus
# chisel.project.root, and Bazel's external repositories resolve into the
# repository cache, so the locators would hold the build machine's paths.
# This keeps each one's path inside its repository, as Chisel's own jars have
# them. It runs on the FIRRTL before Golden Gate, which sorts locators that
# name several files, and on the Verilog after it, for Golden Gate's own.
_NORMALIZE = ("sed -E -i " +
              "'s#([[ ,{])[^] ,[{]*/cache/repos/v1/contents/[0-9a-f]{64}/[0-9a-f-]{36}/#\\1#g; " +
              "s#([[ ,{])[^] ,[{]*/external/[^]/ ,[{]+/#\\1#g'")

FireSimTargetInfo = provider(
    doc = "A target design elaborated for FireSim.",
    fields = {
        "fir": "File: the legacy SFC FIRRTL",
        "anno": "File: its annotations",
    },
)

# The tools are JVM programs and run in the target configuration: an
# exec-configured copy would compile the whole generator a second time.

def _elaborate_impl(ctx):
    config = ctx.attr.config.split(":")[-1]
    long = "%s.%s" % (ctx.attr.top_module, config)
    fir = ctx.actions.declare_file("%s/%s.sfc.fir" % (ctx.label.name, long))
    anno = ctx.actions.declare_file("%s/%s.anno.json" % (ctx.label.name, long))
    log = ctx.actions.declare_file("%s/elaborate.log" % ctx.label.name)
    dtc = ctx.executable._dtc
    ctx.actions.run_shell(
        outputs = [fir, anno, log],
        inputs = [dtc],
        tools = [ctx.attr.generator[DefaultInfo].files_to_run],
        command = """export PATH="$PWD/{dtcdir}:$PATH"
"$1" "${{@:2}}" > "{log}" 2>&1 || {{ tail -40 "{log}" >&2; exit 1; }}
{norm} "{fir}"
""".format(dtcdir = dtc.dirname, log = log.path, norm = _NORMALIZE, fir = fir.path),
        arguments = [
            ctx.executable.generator.path,
            "--target-dir",
            fir.dirname,
            "--name",
            long,
            "--top-module",
            ctx.attr.top_module,
            "--legacy-configs",
            ctx.attr.config,
            "--emit-legacy-sfc",
        ] + ctx.attr.extra_args,
        mnemonic = "FireSimElaborate",
        progress_message = "Elaborating %s" % long,
    )
    return [
        DefaultInfo(files = depset([fir, anno])),
        FireSimTargetInfo(fir = fir, anno = anno),
    ]

firesim_elaborate = rule(
    implementation = _elaborate_impl,
    doc = """Elaborates a target design to legacy SFC FIRRTL for Golden Gate.

    As Chipyard's FireChip flow runs it (common.mk with
    EXTRA_CHISEL_OPTIONS=--emit-legacy-sfc). The generator is Chipyard's
    `chipyard.Generator`, or anything taking the same arguments.""",
    attrs = {
        "generator": attr.label(executable = True, cfg = "target", mandatory = True, doc = "e.g. @chipyard_firechip//:generator"),
        "top_module": attr.string(mandatory = True, doc = "e.g. firechip.chip.FireSim"),
        "config": attr.string(mandatory = True, doc = "package:Config, as --legacy-configs takes it"),
        "extra_args": attr.string_list(doc = "more generator arguments"),
        "_dtc": attr.label(default = "@dtc", executable = True, cfg = "exec"),
    },
)

_GG_OUTS = ["sv", "const.h", "defines.vh", "synthesis.xdc", "implementation.xdc"]

def _goldengate_impl(ctx):
    t = ctx.attr.target[FireSimTargetInfo]
    outs = {s: ctx.actions.declare_file("%s/FireSim-generated.%s" % (ctx.label.name, s)) for s in _GG_OUTS}
    log = ctx.actions.declare_file("%s/goldengate.log" % ctx.label.name)
    package, config = ctx.attr.platform_config.split(":")
    ctx.actions.run_shell(
        outputs = outs.values() + [log],
        inputs = [t.fir, t.anno],
        tools = [ctx.attr._goldengate[DefaultInfo].files_to_run],
        # As FireSim's goldengate.mk runs it, then appends the black boxes.
        command = """"$1" -i "$2" -faf "$3" -td "$4" -ggcp "$5" -ggcs "$6" \\
    --output-filename-base FireSim-generated --allow-unrecognized-annotations --no-dedup \\
    > "{log}" 2>&1 || {{ tail -40 "{log}" >&2; exit 1; }}
grep -sh ^ "$4/firrtl_black_box_resource_files.f" | xargs -r cat >> "$4/FireSim-generated.sv"
{norm} "$4/FireSim-generated.sv"
""".format(log = log.path, norm = _NORMALIZE),
        arguments = [
            ctx.executable._goldengate.path,
            t.fir.path,
            t.anno.path,
            outs["sv"].dirname,
            package,
            config,
        ],
        mnemonic = "GoldenGate",
        progress_message = "Golden Gate for %s" % ctx.label,
    )
    return [
        DefaultInfo(files = depset(outs.values())),
        OutputGroupInfo(
            header = depset([outs["const.h"]]),
            hdl = depset([outs[s] for s in ["sv", "defines.vh", "synthesis.xdc", "implementation.xdc"]]),
        ),
    ]

firesim_goldengate = rule(
    implementation = _goldengate_impl,
    doc = "Runs Golden Gate on an elaborated target for one platform config.",
    attrs = {
        "target": attr.label(mandatory = True, providers = [FireSimTargetInfo], doc = "a firesim_elaborate"),
        "platform_config": attr.string(mandatory = True, doc = "package:Config, e.g. firesim.configs:BaseNitefuryConfig"),
        "_goldengate": attr.label(default = "@firesim_goldengate//:goldengate", executable = True, cfg = "target"),
    },
)

def _header_impl(ctx):
    src = ctx.attr.design[OutputGroupInfo].header.to_list()[0]
    out = ctx.actions.declare_file("%s/FireSim-generated.const.h" % ctx.label.name)
    ctx.actions.symlink(output = out, target_file = src)
    return [DefaultInfo(files = depset([out]))]

_firesim_header = rule(
    implementation = _header_impl,
    attrs = {"design": attr.label(mandatory = True)},
)

def firesim_driver(name, design, driver_lib, platform = "rhsresearch_nitefury_ii", copts = [], **kwargs):
    """The host driver for one firesim_goldengate design.

    FireSim's platform simif, main and entry, compiled against the design's
    generated header and linked with the target's bridge drivers.

    Args:
      name: the binary's name.
      design: a firesim_goldengate target.
      driver_lib: the target's bridge drivers, a cc_library; for Chipyard's
        FireChip targets, @chipyard_firechip//:firechip_driver_lib.
      platform: FireSim's platform name, as in simif_<platform>.cc.
      copts: more compiler options.
      **kwargs: passed to cc_binary.
    """
    _firesim_header(name = name + "_header", design = design)
    cc_library(
        name = name + "_const",
        hdrs = [":" + name + "_header"],
        includes = [name + "_header"],
    )
    cc_binary(
        name = name,
        srcs = [
            Label("@firesim_target//:sim/midas/src/main/cc/simif_%s.cc" % platform),
            Label("@firesim_target//:sim/midas/src/main/cc/main.cc"),
            Label("@firesim_target//:sim/midas/src/main/cc/entry.cc"),
        ],
        copts = ["-std=c++20", "-DFIRESIM", "-Wno-inconsistent-missing-override"] + copts,
        deps = [":" + name + "_const", driver_lib],
        **kwargs
    )

def _bitstream_impl(ctx):
    vivado = _vivado_config(ctx)
    if not vivado.is_host:
        fail("firesim_bitstream runs Vivado on the host; docker mode is not supported yet")
    hdl = ctx.attr.design[OutputGroupInfo].hdl.to_list()
    marker = ctx.attr.project_dir + "/" + ctx.attr.script
    tops = [f for f in ctx.files.board if f.path.endswith("/" + marker)]
    if len(tops) != 1:
        fail("board has no single %s" % marker)
    board_root = tops[0].path[:-len(marker) - 1]
    names = ["firesim.bit", "firesim.mcs", "timing_summary.rpt", "utilization.rpt", "vivado.log"]
    outs = [ctx.actions.declare_file("%s/%s" % (ctx.label.name, n)) for n in names]
    lock = 'flock -o -w 5400 "%s" ' % ctx.attr.lock if ctx.attr.lock else ""
    ctx.actions.run_shell(
        outputs = outs,
        inputs = ctx.files.board + hdl,
        command = """set -e
EXECROOT="$PWD"
OUT="$EXECROOT/{outdir}"
W=$(mktemp -d "$OUT/work.XXXXXX")
trap 'rm -rf "$W"' EXIT
# Bazel clears the environment; Vivado's startup scripts need a HOME.
export HOME="$W/home"
mkdir -p "$HOME"
cp -rL "{board}/." "$W/"
chmod -R u+w "$W"
for f in {hdl}; do cp "$EXECROOT/$f" "$W/{proj}/{hdl_dir}/"; done
cd "$W/{proj}"
{lock}"{vivado}/bin/vivado" -mode batch -nojournal -log "$OUT/vivado.log" -source {script} -tclargs {freq} {strategy} > "$W/vivado.out" 2>&1 \\
    || {{ grep -E "^ERROR" "$W/vivado.out" | head -20 >&2; exit 1; }}
cp {bit} "$OUT/firesim.bit"
cp {mcs} "$OUT/firesim.mcs"
cp {impl}/*_timing_summary_routed.rpt "$OUT/timing_summary.rpt"
cp {impl}/*_utilization_placed.rpt "$OUT/utilization.rpt"
""".format(
            outdir = outs[0].dirname,
            board = board_root,
            hdl = " ".join(['"%s"' % f.path for f in hdl]),
            proj = ctx.attr.project_dir,
            hdl_dir = ctx.attr.hdl_dir,
            lock = lock,
            vivado = vivado.vivado_path,
            script = ctx.attr.script,
            freq = ctx.attr.frequency_mhz,
            strategy = ctx.attr.strategy,
            bit = ctx.attr.bit,
            mcs = ctx.attr.mcs,
            impl = ctx.attr.impl_dir,
        ),
        mnemonic = "FireSimBitstream",
        progress_message = "Vivado bitstream for %s" % ctx.label,
        # Vivado runs from its install on the host, outside the sandbox.
        execution_requirements = {"no-sandbox": "1", "no-remote": "1"},
    )
    return [DefaultInfo(files = depset(outs[:4]))]

firesim_bitstream = rule(
    implementation = _bitstream_impl,
    doc = """Builds a design's bitstream with its board project's own script.

    The board project is copied, Golden Gate's outputs are put where its
    script expects them, and the script runs under the Vivado that
    rules_vivado resolves. The defaults are FireSim's Nitefury II project
    (@firesim_platform_nitefury), as its build-bitstream.sh runs it.""",
    attrs = {
        "design": attr.label(mandatory = True, doc = "a firesim_goldengate"),
        "board": attr.label(default = "@firesim_platform_nitefury//:all", allow_files = True),
        "project_dir": attr.string(default = "Sample-Projects/Project-0/cl_firesim/Nitefury-II/project"),
        "hdl_dir": attr.string(default = "project.srcs/sources_1/imports/HDL"),
        "script": attr.string(default = "top.tcl"),
        "impl_dir": attr.string(default = "project/project.runs/impl_1"),
        "bit": attr.string(default = "project/project.runs/impl_1/Top_wrapper.bit"),
        "mcs": attr.string(default = "../mcs/out.mcs"),
        "frequency_mhz": attr.int(default = 50),
        "strategy": attr.string(default = "TIMING", values = ["TIMING", "AREA"]),
        "lock": attr.string(doc = "a file to flock while Vivado runs, if any"),
    },
    toolchains = [_VIVADO_TOOLCHAIN_TYPE],
)
