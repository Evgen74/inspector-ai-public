# inspector_common

Owner: **AG-00**, except `params.py` (**AG-03**). Shared by every Python package.

| Module | Content |
|---|---|
| `settings.py` | `Settings` from `INSPECTOR_*` env vars (see `.env.example`); `get_settings()` |
| `paths.py` | repo root, contracts dir, organizer data roots (`DataPaths`, read-only), `ensure_dir` for our own dirs |
| `jsonlog.py` | JSON-lines logging with bound context (`log_context(run_id=…, file_id=…)`) |
| `hashing.py` | `sha256_file`, canonical JSON, `input_manifest_hash`, `config_hash` (golden vectors in contracts) |
| `geometry.py` | normalized page geometry `PDF_VISIBLE_ROTATED_TL_V1` (02 §3.14), bbox/polygon ops |
| `errors.py` | `InspectorError(code, **details)` backed by `errors.yaml`; RFC 9457 bodies |
| `exitcodes.py` | CLI exit codes |
| `batch.py` | protocol between `inspector-batch` and the command modules of owner packages |
| `contracts/` | loader + validators, generated `enums.py`, pydantic `models.py`, `codes.py`, `status.py`, `inspector-contracts` CLI |
| `params.py` | catalog loader — AG-03 |
