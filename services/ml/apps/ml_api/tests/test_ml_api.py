"""ml-api: tile pyramid math, pixel agreement of tiles and crops with a full render (incl. /Rotate), HTTP
contract (problem+json codes, service token) and the train-only file resolver. Synthetic PDFs only."""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from inspector_common.errors import InspectorError
from inspector_common.paths import DOCUMENTS_DIR_PARTS, PACKAGE_DIR_NAME
from inspector_common.settings import Settings
from inspector_ml_api.app import create_app
from inspector_ml_api.files import RegistryFileResolver, ResolvedPdf
from inspector_ml_api.render import PageRenderer, RenderRequestError, level_size, pyramid

RED = (1.0, 0.0, 0.0)


def make_pdf(path: Path, *, rotation: int = 0, pages: int = 2) -> Path:
    """Landscape pages (600 × 400 pt) with a red box at unrotated (50, 50)–(150, 100)."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=600, height=400)
        page.draw_rect(pymupdf.Rect(50, 50, 150, 100), color=RED, fill=RED)
        page.insert_text((300, 300), "Помещение 012", fontsize=14)
        page.set_rotation(rotation)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path


def png_array(png: bytes) -> np.ndarray:
    pix = pymupdf.Pixmap(io.BytesIO(png).getvalue())
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]


def red_mask(arr: np.ndarray) -> np.ndarray:
    return (arr[:, :, 0] > 200) & (arr[:, :, 1] < 60) & (arr[:, :, 2] < 60)


# ── pyramid math ───────────────────────────────────────────────────────────────────────────────


def test_pyramid_follows_the_deep_zoom_convention() -> None:
    w, h, max_level = pyramid(2384.0, 3370.0, 288, 512)  # the A1-ish gold RD sheet
    assert (w, h) == (9536, 13480)
    assert max_level == math.ceil(math.log2(13480)) == 14
    assert level_size(w, h, max_level, max_level) == (w, h)
    assert level_size(w, h, max_level, max_level - 1) == (4768, 6740)
    assert level_size(w, h, max_level, 0) == (1, 1)


# ── renderer ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_tiles_stitch_to_the_full_page_render(tmp_path: Path, rotation: int) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", rotation=rotation)
    r = PageRenderer(max_dpi=72, tile_size=128)
    info = r.info(pdf, 1)
    assert (info.width_pt, info.height_pt) == ((600.0, 400.0) if rotation == 0 else (400.0, 600.0))
    assert info.rotation == rotation
    full, meta = r.render_image(pdf, 1, dpi=72)
    full_arr = png_array(full)
    assert full_arr.shape[:2] == (info.height_px, info.width_px)
    assert meta["capped"] is False
    cols = math.ceil(info.width_px / 128)
    rows = math.ceil(info.height_px / 128)
    stitched = np.zeros_like(full_arr)
    for ty in range(rows):
        for tx in range(cols):
            tile = png_array(r.render_tile(pdf, 1, info.max_level, tx, ty))
            y0, x0 = ty * 128, tx * 128
            assert tile.shape[:2] == (min(128, info.height_px - y0), min(128, info.width_px - x0))
            stitched[y0 : y0 + tile.shape[0], x0 : x0 + tile.shape[1]] = tile
    # Same content: the red box lands on the same pixels (antialiasing at tile seams aside).
    a, b = red_mask(full_arr), red_mask(stitched)
    assert a.sum() > 1000
    assert (a ^ b).sum() / a.sum() < 0.02
    # One display list per page, reused by every tile.
    assert r.stats["display_lists_built"] == 1
    r.close()


def test_crop_uses_the_displayed_space_of_bbox_polygon_norm(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "rot.pdf", rotation=90)
    r = PageRenderer(max_dpi=72)
    full = red_mask(png_array(r.render_image(pdf, 1, dpi=72)[0]))
    ys, xs = np.nonzero(full)
    h, w = full.shape
    bbox = (xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h)
    crop, meta = r.render_image(pdf, 1, dpi=144, bbox=bbox)
    arr = png_array(crop)
    assert red_mask(arr).mean() > 0.9  # the normalized bbox of the red box is (almost) all red
    assert meta["width_px"] == arr.shape[1] and meta["height_px"] == arr.shape[0]
    r.close()


def test_width_request_and_the_megapixel_cap(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf")
    r = PageRenderer()
    png, meta = r.render_image(pdf, 1, width=300)
    assert png_array(png).shape[1] == 300 and meta["width_px"] == 300
    _, meta = r.render_image(pdf, 1, dpi=600)  # 600×400 pt at 600 dpi = 5000×3334 px < cap
    assert meta["capped"] is False
    import inspector_ml_api.render as render_mod

    old = render_mod.MAX_IMAGE_PIXELS
    render_mod.MAX_IMAGE_PIXELS = 1_000_000
    try:
        png, meta = r.render_image(pdf, 1, dpi=600)
    finally:
        render_mod.MAX_IMAGE_PIXELS = old
    assert meta["capped"] is True
    arr = png_array(png)
    assert arr.shape[0] * arr.shape[1] <= 1_000_000 * 1.01
    r.close()


def test_out_of_range_requests_are_refused(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", pages=2)
    r = PageRenderer(tile_size=256)
    with pytest.raises(RenderRequestError) as page_err:
        r.info(pdf, 3)
    assert page_err.value.code == "PAGE_NOT_FOUND" and page_err.value.details == {
        "page_no": 3,
        "pdf_pages": 2,
    }
    info = r.info(pdf, 1)
    for level, x, y in [(info.max_level + 1, 0, 0), (info.max_level, 99, 0), (0, 1, 0)]:
        with pytest.raises(RenderRequestError) as tile_err:
            r.render_tile(pdf, 1, level, x, y)
        assert tile_err.value.code == "VALIDATION_ERROR"
    with pytest.raises(RenderRequestError):
        r.render_image(pdf, 1, bbox=(0.5, 0.5, 0.4, 0.9))
    with pytest.raises(RenderRequestError):
        r.render_image(pdf, 1, dpi=5)
    r.close()


# ── HTTP contract ──────────────────────────────────────────────────────────────────────────────


class FakeResolver:
    def __init__(self, files: dict[str, Path]) -> None:
        self.files = files

    def resolve(self, file_id: str) -> ResolvedPdf:
        if file_id == "F0HID":
            raise InspectorError("HIDDEN_TEST_ACCESS_DENIED", object_id="OBJ-HIDDEN-Z")
        path = self.files.get(file_id)
        if path is None:
            raise InspectorError("FILE_NOT_FOUND", file_id=file_id)
        return ResolvedPdf(file_id, "OBJ-TRAIN-A", path, "ab" * 32, 2)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        FakeResolver({"F0001": make_pdf(tmp_path / "a.pdf")}), PageRenderer(tile_size=256), token=""
    )
    return TestClient(app)


def test_http_page_info_image_crop_and_tile(client: TestClient) -> None:
    info = client.post("/v1/render/page-info", json={"file_id": "F0001", "page_no": 1})
    assert info.status_code == 200
    body = info.json()
    assert body["object_id"] == "OBJ-TRAIN-A" and body["sha256"] == "ab" * 32
    assert body["tile_size"] == 256 and body["max_level"] >= 1
    page = client.post("/v1/render/page", json={"file_id": "F0001", "page_no": 1, "width": 400})
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert page.headers["x-render-width"] == "400" and page.headers["x-file-sha256"] == "ab" * 32
    crop = client.post(
        "/v1/render/crop", json={"file_id": "F0001", "page_no": 1, "bbox": [0, 0, 0.5, 0.5], "dpi": 72}
    )
    assert crop.status_code == 200 and crop.headers["x-render-width"] == "300"
    tile = client.post(
        "/v1/render/tile", json={"file_id": "F0001", "page_no": 1, "level": body["max_level"], "x": 0, "y": 0}
    )
    assert tile.status_code == 200 and png_array(tile.content).shape[:2] == (256, 256)
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["renderer"]["renders"] == 3


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"file_id": "F9404", "page_no": 1}, 404, "FILE_NOT_FOUND"),
        ({"file_id": "F0HID", "page_no": 1}, 403, "HIDDEN_TEST_ACCESS_DENIED"),
        ({"file_id": "F0001", "page_no": 9}, 404, "PAGE_NOT_FOUND"),
        ({"file_id": "F0001", "page_no": 0}, 400, "VALIDATION_ERROR"),
        ({"file_id": "../etc/passwd", "page_no": 1}, 400, "VALIDATION_ERROR"),
        ({"file_id": "F0001", "page_no": 1, "extra": True}, 400, "VALIDATION_ERROR"),
    ],
)
def test_http_errors_are_catalogue_problems(
    client: TestClient, payload: dict, status: int, code: str
) -> None:
    r = client.post("/v1/render/page-info", json=payload, headers={"X-Request-Id": "req-12345678"})
    assert r.status_code == status
    assert r.headers["content-type"].startswith("application/problem+json")
    problem = r.json()
    assert problem["code"] == code and problem["request_id"] == "req-12345678"
    if code == "PAGE_NOT_FOUND":
        assert problem["detail"] == "В файле F0001 нет страницы 9 (всего страниц: 2)."


def test_service_token_is_required_when_configured(tmp_path: Path) -> None:
    app = create_app(
        FakeResolver({"F0001": make_pdf(tmp_path / "a.pdf")}), PageRenderer(), token="s3cret-token"
    )
    c = TestClient(app)
    assert (
        c.post("/v1/render/page-info", json={"file_id": "F0001", "page_no": 1}).json()["code"]
        == "UNAUTHENTICATED"
    )
    ok = c.post(
        "/v1/render/page-info",
        json={"file_id": "F0001", "page_no": 1},
        headers={"X-Service-Token": "s3cret-token"},
    )
    assert ok.status_code == 200
    assert c.get("/health").status_code == 200  # health is open


# ── resolver (train only) ──────────────────────────────────────────────────────────────────────


def _row(file_id: str, object_id: str, rel: str, path: Path, split: str) -> dict:
    data = path.read_bytes()
    return {
        "schema_version": "0.1.0",
        "file_id": file_id,
        "object_id": object_id,
        "corpus": object_id,
        "dataset_role": "UNLABELED_POOL",
        "split": split,
        "relative_path": rel,
        "extension": Path(rel).suffix.lower(),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "stage": "RD",
        "section": "OTHER",
        "pdf_pages": 2 if rel.endswith(".pdf") else None,
        "annotation_status": "UNLABELED",
        "exclusion_reason": None,
        "duplicate_group": None,
        "distribution_status": "INCLUDE",
        "label_visibility": "PUBLIC_TRAIN" if split == "TRAIN_PUBLIC" else "ORGANIZER_ONLY",
    }


def test_registry_resolver_serves_train_pdfs_only(tmp_path: Path) -> None:
    root = tmp_path / "data_utf8"
    docs = root.joinpath(*DOCUMENTS_DIR_PARTS)
    data = root / PACKAGE_DIR_NAME / "data"
    data.mkdir(parents=True)
    train_pdf = make_pdf(docs / "Train" / "РД" / "лист.pdf")
    hidden_pdf = make_pdf(docs / "Hidden" / "РД" / "лист.pdf")
    dwg = docs / "Train" / "РД" / "чертёж.dwg"
    dwg.write_bytes(b"AC1032" + b"\0" * 64)
    missing = make_pdf(tmp_path / "elsewhere" / "missing.pdf")
    rows = [
        _row("F0001", "OBJ-TRAIN-A", "Train/РД/лист.pdf", train_pdf, "TRAIN_PUBLIC"),
        _row("F0002", "OBJ-HIDDEN-Z", "Hidden/РД/лист.pdf", hidden_pdf, "TEST_HIDDEN"),
        _row("F0003", "OBJ-TRAIN-A", "Train/РД/чертёж.dwg", dwg, "TRAIN_PUBLIC"),
        _row("F0004", "OBJ-TRAIN-A", "Train/РД/нет.pdf", missing, "TRAIN_PUBLIC"),
    ]
    (data / "document_manifest.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )
    (data / "split_policy.json").write_text(
        json.dumps(
            {"TRAIN_PUBLIC": ["OBJ-TRAIN-A"], "TEST_HIDDEN": ["OBJ-HIDDEN-Z"], "excluded_file_ids": ["F0999"]}
        )
    )
    settings = Settings(
        data_root=root, cache_root=tmp_path / "cache", runs_root=tmp_path / "runs", models_root=tmp_path / "m"
    )
    resolver = RegistryFileResolver(settings)
    ok = resolver.resolve("F0001")
    assert ok.path == train_pdf and ok.object_id == "OBJ-TRAIN-A" and ok.pdf_pages == 2
    expected = {
        "F0002": "HIDDEN_TEST_ACCESS_DENIED",
        "F0003": "FILE_NOT_RENDERABLE",
        "F0004": "FILE_NOT_RENDERABLE",
        "F9404": "FILE_NOT_FOUND",
        "F0999": "EXCLUDED_FILE_REFERENCED",
    }
    for file_id, code in expected.items():
        with pytest.raises(InspectorError) as err:
            resolver.resolve(file_id)
        assert err.value.code == code, file_id


def test_registry_resolver_serves_uploaded_objects_from_their_own_data_root(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    proc = runs / "uploads" / "01a0ecb2-50d2-719e-a9c2-3fb5f9c3a08a"
    root = proc / "dataroot"
    docs = root.joinpath(*DOCUMENTS_DIR_PARTS)
    data = root / PACKAGE_DIR_NAME / "data"
    data.mkdir(parents=True)
    pdf = make_pdf(docs / "Корпус" / "АР.pdf")
    outside = make_pdf(tmp_path / "outside" / "x.pdf")
    (docs / "Корпус" / "link.pdf").symlink_to(outside)
    obj = "OBJ-UPLOAD-f9c3a08a"
    rows = [
        _row("Uf9c3a08a-0001", obj, "Корпус/АР.pdf", pdf, "TRAIN_PUBLIC"),
        _row("Uf9c3a08a-0002", obj, "Корпус/link.pdf", outside, "TRAIN_PUBLIC"),
    ]
    (data / "document_manifest.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )
    (data / "split_policy.json").write_text(
        json.dumps({"TRAIN_PUBLIC": [obj], "TEST_HIDDEN": [], "excluded_file_ids": []})
    )
    settings = Settings(
        data_root=tmp_path / "data_utf8",
        cache_root=tmp_path / "cache",
        runs_root=runs,
        models_root=tmp_path / "m",
    )
    resolver = RegistryFileResolver(settings)
    ok = resolver.resolve("Uf9c3a08a-0001")
    assert ok.path == pdf and ok.object_id == obj
    with pytest.raises(InspectorError) as err:  # a symlink leaving the upload directory is refused
        resolver.resolve("Uf9c3a08a-0002")
    assert err.value.code == "FILE_NOT_RENDERABLE"
    with pytest.raises(
        InspectorError
    ) as err:  # unknown upload suffix: falls through to the organizer registry
        resolver.resolve("U00000000-0001")
    assert err.value.code in {"FILE_NOT_FOUND", "DATA_ROOT_NOT_FOUND"}


def test_serve_refuses_non_loopback_host_unless_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from inspector_ml_api import cli

    started: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: started.append(kw))
    monkeypatch.delenv("INSPECTOR_ML_API_ALLOW_REMOTE", raising=False)
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2
    assert started == []
    monkeypatch.setenv("INSPECTOR_ML_API_ALLOW_REMOTE", "1")
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "18090"]) == 0
    assert started[0]["host"] == "0.0.0.0"
    monkeypatch.delenv("INSPECTOR_ML_API_ALLOW_REMOTE")
    assert cli.main(["serve", "--host", "127.0.0.1"]) == 0
