"""Chisel 6.7.0 libraries, as Chipyard 1.15.0's build.sbt compiles them."""

load("@rules_scala//scala:scala.bzl", "scala_library")

# chiselSettings, commonSettings and rocketLibDeps from Chipyard's build.sbt.
# The toolchain is transitive, so naming the top-level artifacts is enough.
CHIPYARD_MAVEN = [
    "@chipyard_maven//:org_chipsalliance_chisel_2_13",
    "@chipyard_maven//:org_apache_commons_commons_lang3",
    "@chipyard_maven//:org_apache_commons_commons_text",
    "@chipyard_maven//:com_lihaoyi_sourcecode_2_13",
    "@chipyard_maven//:org_scala_lang_scala_reflect",
    "@chipyard_maven//:com_lihaoyi_mainargs_2_13",
    "@chipyard_maven//:org_json4s_json4s_jackson_2_13",
    "@chipyard_maven//:org_scala_graph_graph_core_2_13",
]

CHIPYARD_SCALACOPTS = [
    "-deprecation",
    "-unchecked",
    "-Ymacro-annotations",
    "-language:reflectiveCalls",
    "-language:existentials",
    "-language:implicitConversions",
]

CHISEL_PLUGIN = "@chipyard_maven//:org_chipsalliance_chisel_plugin_2_13_16"

def chisel6_library(name, srcs, deps = [], resource_dir = None, scalacopts = [], plugins = [], visibility = ["//visibility:public"], **kwargs):
    """A Chipyard project's library: Chisel 6.7.0, its plugin and its options.

    Args:
      name: the target name.
      srcs: the Scala sources.
      deps: further libraries, beyond the common Chipyard set.
      resource_dir: a directory, relative to the package, whose files become
        the jar's resources (as sbt's src/main/resources). Not together with
        `resources`.
      scalacopts: more compiler options, after Chipyard's.
      plugins: more compiler plugins, besides Chisel's.
      visibility: the target's visibility; public by default, as overlays are
        meant to be used from other modules.
      **kwargs: passed to scala_library.
    """
    if resource_dir:
        if "resources" in kwargs:
            fail("chisel6_library: give resource_dir or resources, not both")
        kwargs["resources"] = native.glob([resource_dir + "/**"], allow_empty = True)
        kwargs["resource_strip_prefix"] = resource_dir
    scala_library(
        name = name,
        srcs = srcs,
        deps = CHIPYARD_MAVEN + deps,
        plugins = [CHISEL_PLUGIN] + plugins,
        scalacopts = CHIPYARD_SCALACOPTS + scalacopts,
        visibility = visibility,
        **kwargs
    )
