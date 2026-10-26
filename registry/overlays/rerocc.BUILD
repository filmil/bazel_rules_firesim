load("@//overlays:defs.bzl", "chisel6_library")

chisel6_library(
    name = "rerocc",
    srcs = glob(["src/main/scala/**/*.scala"]),
    resource_dir = "src/main/resources",
    deps = ["@rocket_chip", "@constellation", "@boom", "@shuttle"],
)
