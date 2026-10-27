# rules_firesim

Bazel rules for [FireSim](https://fires.im) 1.22.0: a target design goes from
Chisel to a bitstream and a host driver, built from source, without sbt,
conda or a Vivado project on the host.

    firesim_elaborate   the target, to legacy SFC FIRRTL (Chipyard's generator)
    firesim_goldengate  Golden Gate: FireSim-generated.sv, the driver header, XDCs
    firesim_driver      the host driver for one design and platform
    firesim_bitstream   the board project's own build script, under rules_vivado

Platforms: FireSim's RHS Research Nitefury II (`xc7a200tfbg484-2`), on
Vivado 2025.2. FireSim's own flow for it is pinned to Vivado 2022.1; the one
change 2025.2 needs (XDMA 4.1 to 4.2) is a patch in
`firesim_platform_nitefury`.

## The module net

Everything comes from the [filmil registry](https://github.com/filmil/bazel-registry)
and the BCR. Most modules are registry overlays over an upstream commit, at
the commits Chipyard 1.15.0 pins:

    rules_firesim ─┬─ firesim_goldengate   Golden Gate, a prebuilt jar
                   ├─ firesim_target       FireSim's target-side library and driver sources
                   ├─ firesim_platform_nitefury   the board project
                   └─ rules_vivado
    chipyard_firechip ─┬─ testchipip, icenet, riscv_boom, pmu, constellation,
                       │  bar_fetchers, shuttle, rerocc, rocket_chip_blocks,
                       │  rocket_chip_inclusive_cache, firrtl2, riscv_isa_sim
                       └─ rocket_chip ─┬─ diplomacy ── cde
                                       └─ berkeley_hardfloat
    every Chisel module ── chipyard_scala  (this repo's chipyard_scala/)

`chipyard_scala` holds what the Chisel modules share: the `chisel6_library`
macro, the one Maven set (`@chipyard_maven`), and a Scala toolchain that
compiles against full transitive classpaths, as sbt does.

Golden Gate is a separate Scala world (Chisel 3.6.1), and rules_scala takes
its Scala version from the root module only, so it is built in its own
repository, [bazel_firesim_goldengate](https://github.com/filmil/bazel_firesim_goldengate),
and used here as a tool.

## Use

`.bazelrc`:

    common --registry=https://raw.githubusercontent.com/filmil/bazel-registry/main
    common --registry=https://bcr.bazel.build

`MODULE.bazel` needs, besides the `bazel_dep`s, what only the root module can
state: Scala 2.13.16 (Chisel 6.7.0's plugin is built for it exactly), the
transitive toolchain, a C++ toolchain and Vivado. See
[`integration/MODULE.bazel`](integration/MODULE.bazel), which is the whole
of it, plus a lock file for `@chipyard_maven` (only the root module can give
one). Its Vivado lines name eph4's install cache and installer archive; a
consumer names their own.

`BUILD.bazel`, FireSim's `nitefury_firesim_rocket_singlecore_no_nic` recipe:

```starlark
load("@rules_firesim//firesim:defs.bzl", "firesim_bitstream", "firesim_driver", "firesim_elaborate", "firesim_goldengate")

firesim_elaborate(
    name = "rocket",
    config = "firechip.chip:FireSimRocket1GiBDRAMConfig",
    generator = "@chipyard_firechip//:generator",
    top_module = "firechip.chip.FireSim",
)

firesim_goldengate(
    name = "rocket_nitefury",
    platform_config = "firesim.configs:BaseNitefuryConfig",
    target = ":rocket",
)

firesim_driver(
    name = "rocket_nitefury_driver",
    design = ":rocket_nitefury",
    driver_lib = "@chipyard_firechip//:firechip_driver_lib",
)

firesim_bitstream(
    name = "rocket_nitefury_bitstream",
    design = ":rocket_nitefury",
    tags = ["manual"],
)
```

On one machine (eph4), from a warm cache: elaboration and Golden Gate take
about 1.5 minutes, the bitstream about 30 (WNS +0.318 ns, 69% of LUTs).

## Opt-in: the Nitefury shell without a block design

`firesim_bitstream` runs the board project's own script. As an
alternative, `@rules_firesim//firesim/nitefury_shell:defs.bzl` builds the
same shell on rules_vivado's own rules: `vivado_ip` per core, then
`vivado_synthesis2` and `vivado_place_and_route2`, so cores and synthesis
are cached on their own.

```starlark
load("@rules_firesim//firesim/nitefury_shell:defs.bzl", "firesim_nitefury_shell")

firesim_nitefury_shell(
    name = "rocket_nitefury_shell",
    design = ":rocket_nitefury",
    tags = ["manual"],
)
```

On the Rocket recipe, the two builds compare as follows:

| | Without block design | Board script |
|---|---|---|
| WNS | +0.152 ns | +0.318 ns |
| LUTs | 92,263 | 92,354 |
| Time | 66 min | 32 min |

The shell without a block design spends most of its time in synthesis,
which a rebuild with only a changed constraint skips.

What differs from the block design:

- The two AXI interconnects are the cores Vivado puts inside them.
- XDMA's own lane placement wins outside a block design, so a step after
  synthesis sets the board's PCIe lane swap and fails the build unless all
  16 `pcie_mgt` pins match the board. Vivado checks this, but no board has
  run it yet.

The board's files come from `@firesim_platform_nitefury`; the two that
change (`early.xdc` less the lane map, the MIG project file without a BOM)
are made by genrules.

## Updating

`registry/` holds the overlay BUILD files, the patches, the upstream pins
and `mkregistry.py`, which writes the registry entries from them. A later
Chipyard means new pins and a re-run.

## Releasing

A release publishes this repository's own two modules, `rules_firesim`
and `chipyard_scala`, to the filmil registry; the upstream modules under
`registry/` are written by `mkregistry.py` as above.

- **Tag and Release** (`.github/workflows/tag-and-release.yml`), run by
  hand, tags `main` with the next version, from the commits since the last
  tag (`feat:` a minor, a breaking change a major, anything else a
  patch), once both modules resolve against the registries. It makes the
  tag and the release together, with `bazel_rules_firesim-<tag>.zip`,
  `git archive` of the commit, as the earlier releases were.
- It then calls **Publish** (`.github/workflows/publish.yml`), which runs
  [publish-to-bcr](https://github.com/bazel-contrib/publish-to-bcr)
  against `filmil/bazel-registry` and opens one pull request there with an
  entry for each module. `.bcr/config.yml` names both module roots; the
  templates under `.bcr/` and `.bcr/chipyard_scala/` give each entry its
  metadata, its source (the same zip, `chipyard_scala` with
  `strip_prefix`) and its presubmit. The entry's `MODULE.bazel` takes its
  version from the tag.
- Publish needs the repository secret `BCR_PUBLISH_TOKEN`, a token that
  can push to `filmil/bazel-registry`. Publish can also be run by hand on
  an existing tag.

Not the BCR: these modules depend on the overlay modules, which are in
the filmil registry only.

## Notes

- **Linux only,** as FireSim and Vivado are.
- **Tools in the target configuration.** The generator and Golden Gate are
  JVM programs and run as built for the target platform, because an
  exec-configured copy would compile the whole generator a second time. A
  build with `--platforms` set to another architecture won't work.
- **Vivado** is the host install rules_vivado resolves; it is not tracked as
  an action input, as in rules_vivado's own rules.

- **Source locators.** Chisel writes each locator as the file's real path,
  and Bazel's external repositories resolve into the repository cache, so
  the rules rewrite each to its path inside its repository. Without that, the
  Verilog would hold the build machine's paths.
- **Left out of Chipyard.** `chipyard_firechip` builds without dsptools (the
  source exclusions Chipyard itself uses under Chisel 7) and without the
  optional generators; a patch drops the ten FireChip configs that name
  those (NVDLA, Saturn, Gemmini, CVA6, Radiance).
- **No firtool.** FireSim's flow has Golden Gate write the Verilog, so
  CIRCT is not needed.
- **Vivado** runs on the host, from rules_vivado's hermetic install; docker
  mode is not supported yet.
- **Running a simulation** needs the board on PCIe (XDMA). The driver builds
  and stops where it looks for the device.
