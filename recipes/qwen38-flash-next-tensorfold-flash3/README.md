# qwen38-flash-next-tensorfold-flash3

TensorFold 0.6.6 `flash-3` recipe, used by run `20261031T023355Z--qwen38-flash-next-tensorfold-flash3`.

## External dependencies

The recipe is not self-contained:

- **Host tool files.** It bind-mounts two files read-only into the container:
  `tool_calls.py` and `tool_trace.py` from `~/tensorfold-recipes/flash-3/tools/`.
  That directory is a checkout of
  [anubhavgupta/Tensorfold-recipies-single-dgx-spark](https://github.com/anubhavgupta/Tensorfold-recipies-single-dgx-spark)
  at commit `481854d920a4050a504b4ca8d4bc4fceb2960235` (unmodified).
  The files are not vendored here because that repository has no license.
  To reproduce, clone it at that commit to `~/tensorfold-recipes`.
- **Container image.** `tensorfold:v0.6.6-cb2ebf0540f4-pb7c96ae7e07e` is built locally by
  that repository's `tensorfold.sh --tf-version 0.6.6 --tf-patches flash-3/runtime/patches`.
- **Drafter.** `incoai/Qwen3.8-Flash-Next-DFlash2` snapshot `a22a1744e85c17364dcc54a6a420af7135d4c7f6`
  must be in the Hugging Face cache (`HF_HUB_OFFLINE=1`).

## Known issue

`model_revision: 4.05bpw_h6_ng6` is recorded, but the command never passes `--revision`.
The server loads whatever snapshot is cached; the benchmark run used `55a732e0c4c3d4614bc42b68493bb930d9b02c0a`.
