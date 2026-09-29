# inspector_batch

Owner: **AG-00**. The `inspector-batch` CLI: native, no DB, no RabbitMQ (97 «two run modes, one engine»).

Subcommands and their implementing packages are fixed in `commands.py`; owners implement
`add_<cmd>_arguments` / `run_<cmd>` in their package's `batch.py` (protocol: `inspector_common.batch`).
The CLI adds `--object`, `--all` (every split_policy object, TRAIN first) and `--hidden-run`, writes
`runs/<run_id>/run_context.<cmd>.json`, and enforces the hidden-test policy: `inventory`/`bench` allowed (inventory,
format, speed checks), `recognize`/`layout`/`tables`/`compare`/`export` only with `--hidden-run` (the single frozen
run), `score` and `run` refused (also via `--all`). Without `--object`/`--all` only TRAIN objects run.

| Command | Package | Owner | M1 start |
|---|---|---|---|
| `inventory` | inspector_registry | AG-01 | implemented |
| `recognize`, `bench` | inspector_docproc | AG-02A | implemented |
| `layout` | inspector_layout | AG-02B | stub (exit 69) |
| `tables` | inspector_tables | AG-02C | stub (exit 69) |
| `compare`, `export` | inspector_compare | AG-04 | stub (exit 69) |
| `score` | inspector_eval | AG-10 | implemented |
| `run` | inspector_batch.pipeline | AG-00 | inventory → recognize → layout → tables → compare → export → score |

After every command the CLI rebuilds `runs/<run_id>/artifacts.json` (`inspector_common.runlayout`,
`packages/contracts/run_layout.yaml`); a failure there is logged and never changes the command's exit code.

`run` calls each owner's `run_<step>` with that step's default options in one run directory, writes
`run_context.<step>.json` per step and `pipeline_summary.json`, points `score` at this run's `submission/`, and stops
at the first failing or unimplemented step (exit 69 names the owner; `--keep-going` tries the remaining steps).
Options: `--steps recognize,layout`, `--from-step compare` (resume with the same `--run-id`). `make run-train
OBJECT=OBJ-TYUMENSKAYA-5-GOLD-SEED [RUN_ID=…] [ARGS=…]`.

The console script calls `cli.entrypoint()`: after `main()` returns it flushes logs and streams and leaves with
`os._exit`, so a native teardown race in ONNX Runtime/CoreML at interpreter exit cannot turn a finished run into
exit 134 (seen at M0 integration). With child processes still alive it exits normally so they are joined.
Tests call `cli.main()` directly.
