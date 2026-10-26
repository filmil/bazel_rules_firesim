load("@//overlays:defs.bzl", "chisel6_library")

chisel6_library(name = "macros", srcs = glob(["macros/src/main/scala/**/*.scala"]))

chisel6_library(
    name = "rocket_chip",
    srcs = glob(["src/main/scala/**/*.scala"]),
    resource_dir = "src/main/resources",
    deps = [":macros", "@cde", "@diplomacy", "@hardfloat"],
)

exports_files(glob(["bootrom/*"]))
