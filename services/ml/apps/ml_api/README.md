# inspector-ml-api — internal ml-api (owner AG-00)

FastAPI service on **127.0.0.1 only**, called by the Node API (`apps/api/src/modules/render`) to render PDF pages
for the evidence viewer. It is the `ml-api` of 90 §3.4 N (`/v1/render/page`, `/v1/render/tile`, `/v1/render/crop`);
nginx never routes to it, and the browser never talks to it.

```bash
make ml-api-dev                     # = cd services/ml && uv run --locked inspector-ml-api serve   (127.0.0.1:8090)
make dev                            # API :3000 + web :5173 + ml-api :8090
uv run --locked inspector-ml-api info   --file F0201 --page 17
uv run --locked inspector-ml-api render --file F0201 --page 17 --width 1600 --out /tmp/p17.png
uv run --locked inspector-ml-api tile   --file F0201 --page 17 --level 13 --x 5 --y 3 --out /tmp/t.png
```

## Why a FastAPI service and not a CLI per request

A page of an A1 drawing takes 0.3–0.9 s to interpret the first time (open the PDF, build the MuPDF display list),
then 10–60 ms per tile from the cached display list. A CLI per request would pay the Python start-up and the
interpretation on every tile. The service keeps documents and display lists in an LRU (8 documents, 24 pages) and
the Node API keeps every PNG in a disk cache keyed by the file's sha256, so each image is rendered once.
The dependencies (fastapi, uvicorn) were already locked for this app.

## Endpoints

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/v1/render/page-info` | `{file_id, page_no}` | page size (pt), rotation, pyramid: `width_px`, `height_px`, `tile_size`, `max_level`, `max_dpi`, and the manifest `sha256` |
| POST | `/v1/render/page` | `{file_id, page_no, dpi? \| width?, bbox?}` | `image/png` (+ `X-Render-Width/Height/Dpi/Capped`) |
| POST | `/v1/render/crop` | same, `bbox` required | `image/png` |
| POST | `/v1/render/tile` | `{file_id, page_no, level, x, y}` | `image/png` |
| GET | `/health` | — | status and renderer counters |

Errors are `application/problem+json` with catalogue codes (`FILE_NOT_FOUND`, `PAGE_NOT_FOUND`, `FILE_NOT_RENDERABLE`,
`HIDDEN_TEST_ACCESS_DENIED`, `EXCLUDED_FILE_REFERENCED`, `VALIDATION_ERROR`, `UNAUTHENTICATED`). With
`INSPECTOR_ML_API_TOKEN` set, every `/v1` call needs the same value in `X-Service-Token` (the API sends it).

## Geometry

Everything is in the contract space `PDF_VISIBLE_ROTATED_TL_V1`: the displayed page after `/Rotate`, origin top-left,
the same space as `bbox_polygon_norm` of evidence fragments. `bbox` is `[x0, y0, x1, y1]` in fractions of the
displayed page. The tile pyramid follows Deep Zoom / OpenSeadragon: level `max_level = ceil(log2(max(W, H)))` is the
page at `max_dpi` (288) = W × H px, level L is scaled by `2^(L − max_level)`, tiles are 512 px without overlap.
Tests check that the tiles of a page stitch into the full render for /Rotate 0, 90 and 270.

## Integrity

- **Train objects only**: files are resolved through `inspector_registry` (manifest + recovery ledger); an object
  outside `TRAIN_PUBLIC` of `split_policy.json` is refused (`HIDDEN_TEST_ACCESS_DENIED`) before the file is opened.
  The Node API refuses such files too, from `files.split`, before calling this service.
- Organizer data is only read; nothing is written anywhere. Page renders are never persisted here (the Node API
  caches PNGs under `.cache/render/`).
