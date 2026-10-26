#!/usr/bin/env python3
"""Writes the FireSim overlay modules into a bazel-registry checkout.

Each module is an upstream commit tarball plus overlay files (MODULE.bazel,
BUILD.bazel) and patches, the form of the registry's nvc entry. The BUILD
overlays are in overlays/, written with short repository names (@hardfloat,
@boom, @firesim, @cy_maven) as one workspace would use them; this script
renames them to the modules' names. pins.txt holds each upstream's commit and
tarball sha256, from Chipyard's submodules.

usage: registry/mkregistry.py <bazel-registry checkout> registry registry/pins.txt
"""
import base64, hashlib, json, os, re, sys

REG, TRIAL, PINS = sys.argv[1:4]
CY = "0.0.0-chipyard.1.15.0"
MAINT = [{"name": "Filip Filmar", "email": "246576+filmil@users.noreply.github.com",
          "github": "filmil", "github_user_id": 246576}]

pins = {}
for line in open(PINS):
    n, repo, sha, h = line.split()
    pins[n] = (repo, sha, h)

def sri(data):
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()

def sri_hex(h):
    return "sha256-" + base64.b64encode(bytes.fromhex(h)).decode()

# Trial labels -> module labels.
RENAMES = [
    ('"@//overlays:defs.bzl", "OPTS", "chisel6_library"', '"@chipyard_scala//:defs.bzl", "CHIPYARD_SCALACOPTS", "chisel6_library"'),
    ('"@//overlays:defs.bzl"', '"@chipyard_scala//:defs.bzl"'),
    ("scalacopts = OPTS", "scalacopts = CHIPYARD_SCALACOPTS"),
    ("@cy_maven//", "@chipyard_maven//"),
    ('"@hardfloat"', '"@berkeley_hardfloat//:hardfloat"'),
    ('"@boom"', '"@riscv_boom//:boom"'),
    ('"@inclusive_cache"', '"@rocket_chip_inclusive_cache//:inclusive_cache"'),
    ('"@firesim//', '"@firesim_target//'),
    ('"@//:riscv_isa_sim"', '"@riscv_isa_sim//:riscv_isa_sim"'),
]

def overlay_build(trial_name):
    s = open(os.path.join(TRIAL, "overlays", trial_name + ".BUILD")).read()
    for a, b in RENAMES:
        s = s.replace(a, b)
    return s

# name: (pin key, trial overlay or literal BUILD, bazel_deps, uses maven, patches, presubmit targets, homepage)
SCALA = [("chipyard_scala", "0.1.0")]
CC = [("rules_cc", "0.2.27")]
def chisel(*more):
    return SCALA + list(more)

MODULES = {
    "cde": ("cde", "cde", chisel(), True, [], ["@cde"]),
    "berkeley_hardfloat": ("hardfloat", "hardfloat", chisel(("firesim_target", "1.22.0")), True, [], ["@berkeley_hardfloat//:hardfloat"]),
    "diplomacy": ("diplomacy", "diplomacy", chisel(("cde", CY)), True, [], ["@diplomacy"]),
    "rocket_chip": ("rocket_chip", "rocket_chip", chisel(("cde", CY), ("diplomacy", CY), ("berkeley_hardfloat", CY)), True, [], ["@rocket_chip"]),
    "rocket_chip_blocks": ("rocket_chip_blocks", "rocket_chip_blocks", chisel(("rocket_chip", CY)), True, [], ["@rocket_chip_blocks"]),
    "rocket_chip_inclusive_cache": ("inclusive_cache", "inclusive_cache", chisel(("rocket_chip", CY)), True, [], ["@rocket_chip_inclusive_cache//:inclusive_cache"]),
    "testchipip": ("testchipip", "testchipip", chisel(("rocket_chip", CY), ("rocket_chip_blocks", CY), ("riscv_isa_sim", CY)) + CC, True,
                   ["testchipip-void-pointer-arith.patch"], ["@testchipip", "@testchipip//:csrc"]),
    "icenet": ("icenet", "icenet", chisel(("rocket_chip", CY)), True, [], ["@icenet"]),
    "pmu": ("pmu", "pmu", chisel(("cde", CY), ("rocket_chip", CY)), True, [], ["@pmu", "@pmu//:pmu_tilelink"]),
    "riscv_boom": ("boom", "boom", chisel(("rocket_chip", CY), ("pmu", CY)), True, [], ["@riscv_boom//:boom"]),
    "constellation": ("constellation", "constellation", chisel(("rocket_chip", CY)), True, [], ["@constellation"]),
    "bar_fetchers": ("bar_fetchers", "bar_fetchers", chisel(("rocket_chip", CY)), True, [], ["@bar_fetchers"]),
    "shuttle": ("shuttle", "shuttle", chisel(("rocket_chip", CY)), True, [], ["@shuttle"]),
    "rerocc": ("rerocc", "rerocc", chisel(("rocket_chip", CY), ("constellation", CY), ("riscv_boom", CY), ("shuttle", CY)), True, [], ["@rerocc"]),
    "firrtl2": ("firrtl2", "firrtl2", chisel(("rules_scala", "7.4.0"), ("rules_java", "8.14.0")), True, [], ["@firrtl2", "@firrtl2//:firrtl2_bridge"]),
    "firesim_target": ("firesim", "firesim", chisel(("gmp", "6.3.0.bcr.4")) + CC, True, [], ["@firesim_target//:firesim_lib", "@firesim_target//:midas_bridges"]),
    "chipyard_firechip": ("chipyard", "chipyard",
        chisel(("rules_scala", "7.4.0"), ("testchipip", CY), ("rocket_chip", CY), ("riscv_boom", CY), ("rocket_chip_blocks", CY),
               ("rocket_chip_inclusive_cache", CY), ("icenet", CY), ("constellation", CY), ("bar_fetchers", CY), ("shuttle", CY),
               ("rerocc", CY), ("firrtl2", CY), ("firesim_target", "1.22.0"), ("riscv_isa_sim", CY), ("zlib", "1.3.2.bcr.2"),
               ("libdwarf", "2.2.0.bcr.1"), ("elfutils", "0.195")) + CC, True,
        ["chipyard-firechip-optional-generators.patch"], ["@chipyard_firechip//:generator", "@chipyard_firechip//:firechip_driver_lib"]),
}
# A module's version here is the one the script writes. Published
# versions are never rewritten: a change to an overlay is a new version
# (1.22.0.bcr.1 exports FireSim's example drivers), and metadata.json
# gains it beside the old ones.
VERSIONS = {"firesim_target": "1.22.0.bcr.1", "chipyard_firechip": "1.15.0"}

RISCV_ISA_SIM_BUILD = '''load("@rules_foreign_cc//foreign_cc:defs.bzl", "configure_make")

filegroup(
    name = "all",
    srcs = glob(["**"], exclude = ["BUILD.bazel", "MODULE.bazel"]),
)

# Spike, from its own autoconf, without Boost (its optional debugger and
# remote bitbang interface). libfesvr carries the TSI and DTM front-ends
# FireSim's bridges use; libriscv carries cospike's ISA model.
configure_make(
    name = "riscv_isa_sim",
    configure_options = ["--without-boost", "--without-boost-asio", "--without-boost-regex"],
    lib_source = ":all",
    build_data = ["@dtc//:dtc"],
    env = {"DTC": "$$EXT_BUILD_ROOT$$/$(execpath @dtc//:dtc)"},
    out_include_dir = "include",
    out_shared_libs = ["libriscv.so", "libsoftfloat.so", "libcustomext.so"],
    out_static_libs = ["libfesvr.a", "libdisasm.a"],
    args = ["-j8"],
    visibility = ["//visibility:public"],
)
'''

NITEFURY_BUILD = '''# FireSim's Nitefury II board project (the NiteFury-and-LiteFury-firesim
# submodule of FireSim 1.22.0), patched for Vivado 2025.2. The data that
# @rules_firesim's firesim_bitstream builds from; its single files are
# exported for @rules_firesim//firesim/nitefury_shell.
exports_files(glob(["**"], exclude = ["BUILD.bazel", "MODULE.bazel"]))

filegroup(
    name = "all",
    srcs = glob(["**"], exclude = ["BUILD.bazel", "MODULE.bazel"]),
    visibility = ["//visibility:public"],
)
'''

def module_bazel(name, version, deps, maven, extra=""):
    out = ['module(\n    name = "%s",\n    version = "%s",\n    compatibility_level = 0,\n)\n' % (name, version)]
    for d, v in deps:
        out.append('bazel_dep(name = "%s", version = "%s")' % (d, v))
    if maven:
        out.append('\nmaven = use_extension("@rules_jvm_external//:extensions.bzl", "maven")\nuse_repo(maven, "chipyard_maven")')
        if ("rules_jvm_external", "6.7") not in deps:
            out.insert(1, 'bazel_dep(name = "rules_jvm_external", version = "6.7")')
    return "\n".join(out) + "\n" + extra

def write_entry(name, version, url, strip, integrity, files, patches, targets, homepage, repo_for_meta=None):
    d = os.path.join(REG, "modules", name, version)
    os.makedirs(os.path.join(d, "overlay"), exist_ok=True)
    overlay = {}
    for rel, content in files.items():
        p = os.path.join(d, "overlay", rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(content)
        overlay[rel] = sri(content.encode())
    # The registry wants the module file next to source.json too.
    open(os.path.join(d, "MODULE.bazel"), "w").write(files["MODULE.bazel"])
    pp = {}
    if patches:
        os.makedirs(os.path.join(d, "patches"), exist_ok=True)
        for p in patches:
            data = open(os.path.join(TRIAL, "patches", p), "rb").read()
            open(os.path.join(d, "patches", p), "wb").write(data)
            pp[p] = sri(data)
    src = {"url": url, "integrity": integrity, "strip_prefix": strip, "overlay": overlay}
    if pp:
        src["patches"] = pp
        src["patch_strip"] = 1
    open(os.path.join(d, "source.json"), "w").write(json.dumps(src, indent=4) + "\n")
    open(os.path.join(d, "presubmit.yml"), "w").write(
        'matrix:\n  platform: ["debian11", "ubuntu2204"]\n  bazel: ["8.x"]\ntasks:\n  verify_targets:\n'
        '    name: Verify build targets\n    platform: ${{ platform }}\n    bazel: ${{ bazel }}\n    build_targets:\n'
        + "".join('      - "%s"\n' % t for t in targets))
    mp = os.path.join(REG, "modules", name, "metadata.json")
    versions = json.load(open(mp))["versions"] if os.path.exists(mp) else []
    if version not in versions:
        versions.append(version)
    meta = {"homepage": homepage, "maintainers": MAINT, "repository": [repo_for_meta] if repo_for_meta else [],
            "versions": versions, "yanked_versions": {}}
    open(os.path.join(REG, "modules", name, "metadata.json"), "w").write(json.dumps(meta, indent=4) + "\n")

for name, (pin, trial, deps, maven, patches, targets) in MODULES.items():
    repo, sha, h = pins[pin]
    version = VERSIONS.get(name, CY)
    build = overlay_build(trial)
    write_entry(name, version, "https://github.com/%s/archive/%s.tar.gz" % (repo, sha),
                "%s-%s" % (repo.split("/")[1], sha), sri_hex(h),
                {"MODULE.bazel": module_bazel(name, version, deps, maven), "BUILD.bazel": build},
                patches, targets, "https://github.com/" + repo, "github:" + repo)

# Spike, at Chipyard 1.15.0's pin.
write_entry("riscv_isa_sim", CY,
    "https://github.com/riscv-software-src/riscv-isa-sim/archive/9c190a07c6838f6392bafa4ad83acea462c7f759.tar.gz",
    "riscv-isa-sim-9c190a07c6838f6392bafa4ad83acea462c7f759",
    sri_hex("586d92f4cc3a2a2dead3b6c10274789d2618b468735ec296aaea822edc800e3b"),
    {"MODULE.bazel": module_bazel("riscv_isa_sim", CY, [("rules_foreign_cc", "0.15.1"), ("dtc", "1.7.2.bcr.2")], False),
     "BUILD.bazel": RISCV_ISA_SIM_BUILD},
    [], ["@riscv_isa_sim//:riscv_isa_sim"], "https://github.com/riscv-software-src/riscv-isa-sim",
    "github:riscv-software-src/riscv-isa-sim")

# The Nitefury II board project, at FireSim 1.22.0's submodule pin.
write_entry("firesim_platform_nitefury", "1.22.0",
    "https://github.com/firesim/NiteFury-and-LiteFury-firesim/archive/dfed09d33196ba4c96bca0ca2b078ce1bdb16c8c.tar.gz",
    "NiteFury-and-LiteFury-firesim-dfed09d33196ba4c96bca0ca2b078ce1bdb16c8c",
    sri_hex("4341e244aafa6b69be0cabbb15027553d7204ff31e3ddb24065ee1e8967a5828"),
    {"MODULE.bazel": module_bazel("firesim_platform_nitefury", "1.22.0", [], False), "BUILD.bazel": NITEFURY_BUILD},
    ["nitefury-vivado-2025.2.patch"], ["@firesim_platform_nitefury//:all"],
    "https://github.com/firesim/NiteFury-and-LiteFury-firesim", "github:firesim/NiteFury-and-LiteFury-firesim")
print("wrote", len(MODULES) + 2, "modules")

# The registry builds //... and would load each overlay's BUILD files as its
# own packages, so every overlay directory is listed in its .bazelignore
# (Bazel expands no patterns there).
ign = os.path.join(REG, ".bazelignore")
if os.path.exists(ign):
    text = open(ign).read()
    have = set(text.split("\n"))
    names = list(MODULES) + ["riscv_isa_sim", "firesim_platform_nitefury"]
    new = sorted(
        "modules/%s/%s/overlay" % (n, v)
        for n in names
        for v in os.listdir(os.path.join(REG, "modules", n))
        if os.path.isdir(os.path.join(REG, "modules", n, v, "overlay"))
    )
    with open(ign, "a") as f:
        if text and not text.endswith("\n"):
            f.write("\n")
        for line in new:
            if line not in have:
                f.write(line + "\n")
