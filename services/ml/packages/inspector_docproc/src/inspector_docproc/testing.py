"""Synthetic PDF and image builders for tests (no organizer data involved)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np


def models_available() -> bool:
    """True when the three runtime OCR models are present in ``.models/ocr``."""
    from inspector_common.paths import repo_root

    env = os.environ.get("INSPECTOR_MODELS_ROOT")  # same override as models.ModelRegistry
    ocr = (Path(env).expanduser() if env else repo_root() / ".models") / "ocr"
    names = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_det_medium.onnx", "cyrillic_PP-OCRv5_rec_mobile.onnx")
    return all((ocr / n).is_file() for n in names)


def make_pdf(
    path: Path,
    lines: Sequence[tuple[float, float, str, float]],
    *,
    size: tuple[float, float] = (595, 842),
    rotate: int = 0,
    cropbox: tuple[float, float, float, float] | None = None,
    mediabox: tuple[float, float, float, float] | None = None,
    font: str = "tiro",
    render_mode: int = 0,
) -> Path:
    """One-page PDF with text ``lines`` = (x, y, text, fontsize) in unrotated page coordinates."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=size[0], height=size[1])
    if mediabox is not None:
        page.set_mediabox(pymupdf.Rect(*mediabox))
    if render_mode == 0:
        tw = pymupdf.TextWriter(page.rect)
        f = pymupdf.Font(font)
        for x, y, text, fs in lines:
            tw.append((x, y), text, font=f, fontsize=fs)
        tw.write_text(page)
    else:
        for x, y, text, fs in lines:
            page.insert_text((x, y), text, fontsize=fs, render_mode=render_mode)
    if cropbox is not None:
        page.set_cropbox(pymupdf.Rect(*cropbox))
    page.set_rotation(rotate)
    doc.save(path)
    return path


def text_image(
    lines: Sequence[tuple[float, float, str, float]], size=(595, 842), dpi: int = 200
) -> np.ndarray:
    """Render text lines on a white page to an RGB array (a synthetic «scan»)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=size[0], height=size[1])
    tw = pymupdf.TextWriter(page.rect)
    f = pymupdf.Font("tiro")
    for x, y, text, fs in lines:
        tw.append((x, y), text, font=f, fontsize=fs)
    tw.write_text(page)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n).copy()


def make_scan_pdf(
    path: Path,
    img_rgb: np.ndarray,
    *,
    size: tuple[float, float] = (595, 842),
    rotate: int = 0,
    cropbox: tuple[float, float, float, float] | None = None,
    hidden_text: str | None = None,
    extra_visible: Sequence[tuple[float, float, str, float]] = (),
) -> Path:
    """One-page PDF whose content is a full-page image (optionally with an invisible text layer)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=size[0], height=size[1])
    pix = pymupdf.Pixmap(pymupdf.csRGB, img_rgb.shape[1], img_rgb.shape[0], img_rgb.tobytes(), False)
    page.insert_image(page.rect, pixmap=pix)
    if hidden_text:
        page.insert_text((50, 100), hidden_text, fontsize=10, render_mode=3)
    if extra_visible:
        tw = pymupdf.TextWriter(page.rect)
        f = pymupdf.Font("tiro")
        for x, y, text, fs in extra_visible:
            tw.append((x, y), text, font=f, fontsize=fs)
        tw.write_text(page)
    if cropbox is not None:
        page.set_cropbox(pymupdf.Rect(*cropbox))
    page.set_rotation(rotate)
    doc.save(path)
    return path


_HEX = r"<([0-9a-fA-F]+)>"


def _parse_to_unicode(cmap: str) -> dict[int, str]:
    """Expand a ToUnicode CMap (bfchar + bfrange, incl. array ranges) into {code: hex destination}."""
    import re

    out: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        for src, dst in re.findall(_HEX + r"\s*" + _HEX, block):
            out[int(src, 16)] = dst.lower()
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
        for line in block.strip().splitlines():
            codes = re.findall(_HEX, line)
            if len(codes) < 3:
                continue
            a, b = int(codes[0], 16), int(codes[1], 16)
            if "[" in line:  # <a> <b> [<d1> <d2> …]
                for i, dst in enumerate(codes[2:]):
                    out[a + i] = dst.lower()
                continue
            base = codes[2]
            head, last = base[:-4], int(base[-4:], 16)
            for i in range(b - a + 1):
                out[a + i] = f"{head}{last + i:04x}".lower()
    return out


def garble_to_unicode(pdf_path: Path, shift: int, out_path: Path | None = None) -> Path:
    """Rewrite every ToUnicode CMap so that Cyrillic letters map to ``code - shift``.

    The glyphs still render as Russian text, only the extracted Unicode is shifted: a faithful replica of
    the real garbled CAD/Office exports (95 R1, 94: e.g. «ȺɇɈ» for «АНО» with shift 0x1D6).
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    done: set[int] = set()
    for xref in range(1, doc.xref_length()):
        kind, val = doc.xref_get_key(xref, "ToUnicode")
        if kind != "xref":
            continue
        cm = int(val.split()[0])
        if cm in done:
            continue
        done.add(cm)
        mapping = _parse_to_unicode(doc.xref_stream(cm).decode("latin-1"))
        pairs = []
        for code, dst in sorted(mapping.items()):
            if len(dst) == 4:
                u = int(dst, 16)
                if 0x0410 <= u <= 0x044F or u in (0x0401, 0x0451):
                    dst = f"{u - shift:04x}"
            pairs.append(f"<{code:04x}> <{dst}>")
        chunks = [pairs[i : i + 100] for i in range(0, len(pairs), 100)]
        body = "".join(f"{len(c)} beginbfchar\n" + "\n".join(c) + "\nendbfchar\n" for c in chunks)
        cmap = (
            "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
            "/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def\n"
            "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            f"{body}endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
        )
        doc.update_stream(cm, cmap.encode("latin-1"))
    target = out_path or pdf_path.with_suffix(".garbled.pdf")
    doc.save(target)
    doc.close()
    return target


def ink_bbox(page, zoom: float = 3.0) -> list[float]:
    """Normalized bbox of dark pixels on a render of the displayed page."""
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    ys, xs = np.where(a < 128)
    return [
        xs.min() / pix.width,
        ys.min() / pix.height,
        (xs.max() + 1) / pix.width,
        (ys.max() + 1) / pix.height,
    ]


# ── Zones (R-10): synthetic seals, signatures and QR codes ─────────────────────────────────────


def qr_image(payload: str, module_px: int = 6) -> np.ndarray:
    """A QR code as a grayscale uint8 image with a quiet zone (OpenCV encoder)."""
    import cv2

    code = cv2.QRCodeEncoder.create().encode(payload)
    img = cv2.resize(code, None, fx=module_px, fy=module_px, interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(
        img, 4 * module_px, 4 * module_px, 4 * module_px, 4 * module_px, cv2.BORDER_CONSTANT, value=255
    )


def zone_page_image(dpi: int = 150) -> tuple[np.ndarray, dict[str, list[float]]]:
    """An A4 «scan» (RGB) with printed black text, a blue round seal, a blue signature and a printed QR code.

    Returns the image and the normalized boxes of the three zones (``seal``, ``signature``, ``qr``).
    """
    import cv2

    lines = [(60, 90, "ПРОТОКОЛ ИСПЫТАНИЙ № 284", 16), (60, 130, "Фактический класс бетона В25", 13),
             (60, 165, "Дата испытаний 20.02.2026 г.", 13), (60, 470, "Генеральный директор", 13),
             (60, 560, "Инженер", 13)]  # fmt: skip
    img = text_image(lines, dpi=dpi)
    h, w = img.shape[:2]
    mm = dpi / 25.4
    blue = (40, 60, 200)  # RGB
    # seal: 40 mm, double border ring, a ring of «text» dashes and a centre mark
    cx, cy, r = int(0.62 * w), int(0.52 * h), int(20 * mm)
    cv2.circle(img, (cx, cy), r, blue, max(2, int(0.5 * mm)), lineType=cv2.LINE_AA)
    cv2.circle(img, (cx, cy), int(r * 0.8), blue, max(1, int(0.3 * mm)), lineType=cv2.LINE_AA)
    for k in range(40):
        a = 2 * np.pi * k / 40
        p1 = (int(cx + 0.86 * r * np.cos(a)), int(cy + 0.86 * r * np.sin(a)))
        p2 = (int(cx + 0.94 * r * np.cos(a + 0.05)), int(cy + 0.94 * r * np.sin(a + 0.05)))
        cv2.line(img, p1, p2, blue, max(1, int(0.25 * mm)), lineType=cv2.LINE_AA)
    cv2.putText(
        img, "OOO", (cx - int(8 * mm), cy + int(2 * mm)), cv2.FONT_HERSHEY_SIMPLEX, 0.08 * mm, blue, 2
    )
    seal = [(cx - r) / w, (cy - r) / h, (cx + r) / w, (cy + r) / h]
    # signature: a looping pen stroke ~45 × 14 mm next to «Инженер»
    t = np.linspace(0, 1, 400)
    x0, y0 = 0.35 * w, 0.655 * h
    xs = x0 + 45 * mm * t
    ys = y0 + 5 * mm * np.sin(2 * np.pi * 3.2 * t) * (1 - 0.3 * t) + 2 * mm * np.cos(2 * np.pi * 7 * t)
    pts = np.stack([xs, ys], 1).astype(np.int32)
    cv2.polylines(img, [pts], False, (70, 50, 180), max(2, int(0.35 * mm)), lineType=cv2.LINE_AA)
    sig = [xs.min() / w, ys.min() / h, xs.max() / w, ys.max() / h]
    # printed QR code, 22 mm, top right
    module = max(2, int(0.75 * mm))
    q = qr_image("https://example.invalid/doc/42", module_px=module)
    qs = int(22 * mm)
    quiet = 4 * module / q.shape[0] * qs  # the code proper starts after the 4-module quiet zone
    q = cv2.resize(q, (qs, qs), interpolation=cv2.INTER_NEAREST)
    qx, qy = int(0.72 * w), int(0.06 * h)
    img[qy : qy + qs, qx : qx + qs] = q[..., None]
    qr = [(qx + quiet) / w, (qy + quiet) / h, (qx + qs - quiet) / w, (qy + qs - quiet) / h]
    return img, {"seal": seal, "signature": sig, "qr": qr}


def make_zone_pdf(
    path: Path, dpi: int = 150, embedded_qr: str | None = "https://example.invalid/sign/7"
) -> tuple[Path, dict[str, list[float]]]:
    """A one-page scan PDF of :func:`zone_page_image`, plus (optionally) a QR code placed as its own small
    image (e-document system stamp) at the bottom centre. Returns the path and the zone boxes (normalized),
    with ``qr_image`` for the embedded one."""
    import pymupdf

    img, boxes = zone_page_image(dpi)
    make_scan_pdf(path, img)
    if embedded_qr:
        doc = pymupdf.open(path)
        page = doc[0]
        q = qr_image(embedded_qr, module_px=4)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, q.shape[1], q.shape[0], q.tobytes(), False)
        rect = pymupdf.Rect(270, 780, 310, 820)  # 14 mm, like the 286×286 px stamps of the corpus
        page.insert_image(rect, pixmap=pix)
        doc.saveIncr()
        doc.close()
        boxes["qr_image"] = [rect.x0 / 595, rect.y0 / 842, rect.x1 / 595, rect.y1 / 842]
    return path, boxes
