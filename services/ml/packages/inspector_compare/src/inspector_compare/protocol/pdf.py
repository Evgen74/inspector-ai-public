"""Protocol HTML → PDF with a local engine (no network, no LibreOffice).

Engines, in the order of ``auto``:

1. **Chromium headless** (Google Chrome / Chromium / Edge found on the host, or ``$INSPECTOR_CHROMIUM``): the
   same engine as the planned Gotenberg route (97 §2.2), so emoji markers and «Segoe UI»/Selawik fallbacks render
   as in the browser. Chrome may keep running after ``--print-to-pdf`` has written the file, so the PDF is polled
   until complete (``%%EOF``, stable size) and the process group is terminated.
2. **PyMuPDF Story** (always available: pymupdf is a dependency): HTML subset → PDF with a system TTF font that has
   Cyrillic; colour emoji are mapped to plain symbols because MuPDF cannot draw colour glyphs.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
CHROMIUM_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge")
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)
EMOJI_FALLBACK = {
    "⚠️": "(!)",
    "✅": "✓",
    "🟡": "●",
    "❌": "✗",
    "⬇️": "↓",
    "⬆️": "↑",
    "⏳": "…",
    "🤖": "ИИ:",
    "🔄": "↻",
    "🔒": "",
    "☑️": "✓",
    "❓": "?",
    "️": "",
}


class PdfEngineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PdfResult:
    path: Path
    engine: str
    seconds: float
    pages: int


def find_chromium() -> str | None:
    env = os.environ.get("INSPECTOR_CHROMIUM")
    if env and Path(env).is_file():
        return env
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    for name in CHROMIUM_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _pdf_complete(path: Path) -> bool:
    try:
        size = path.stat().st_size
        if size < 64:
            return False
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 1024))
            return b"%%EOF" in fh.read()
    except OSError:
        return False


def _page_count(path: Path) -> int:
    import pymupdf

    with pymupdf.open(path) as doc:
        return doc.page_count


def chromium_pdf(
    html_text: str, out: Path, *, binary: str | None = None, timeout_s: float = 90.0
) -> PdfResult:
    binary = binary or find_chromium()
    if binary is None:
        raise PdfEngineError("Chromium не найден")
    t0 = time.perf_counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="inspector-pdf-") as tmp:
        tmp_dir = Path(tmp)
        page = tmp_dir / "protocol.html"
        page.write_text(html_text, encoding="utf-8")
        target = tmp_dir / "protocol.pdf"
        args = [
            binary,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-pdf-header-footer",
            f"--user-data-dir={tmp_dir / 'profile'}",
            f"--print-to-pdf={target}",
            page.as_uri(),
        ]
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        try:
            last_size = -1
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if _pdf_complete(target):
                    size = target.stat().st_size
                    if size == last_size:
                        break
                    last_size = size
                elif proc.poll() is not None and not target.exists():
                    raise PdfEngineError(f"Chromium завершился с кодом {proc.returncode} без PDF")
                time.sleep(0.25)
            else:
                raise PdfEngineError(f"Chromium не сформировал PDF за {timeout_s:.0f} с")
        finally:
            _terminate(proc)
        tmp_out = out.with_suffix(".pdf.tmp")
        shutil.copyfile(target, tmp_out)
        tmp_out.replace(out)
    return PdfResult(out, "chromium", time.perf_counter() - t0, _page_count(out))


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def _font() -> Path | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def plain_symbols(text: str) -> str:
    for emoji, repl in EMOJI_FALLBACK.items():
        text = text.replace(emoji, repl)
    return text


def pymupdf_pdf(html_text: str, out: Path) -> PdfResult:
    """HTML → PDF with PyMuPDF Story (A4, margins 20/15/20/30 mm)."""
    import pymupdf

    t0 = time.perf_counter()
    font = _font()
    css = "* { font-family: sans-serif; }"
    archive = None
    if font is not None:
        archive = pymupdf.Archive(str(font.parent))
        css = f'@font-face {{ font-family: protocolfont; src: url("{font.name}"); }} * {{ font-family: protocolfont; }}'
    # Story has no data-URI images: the fallback PDF lists the sources without thumbnails (DOCX keeps them).
    text = re.sub(r'<div class="thumbs">.*?</div>', "", plain_symbols(html_text), flags=re.S)
    story = pymupdf.Story(html=text, user_css=css, archive=archive)
    mm = 72 / 25.4
    mediabox = pymupdf.paper_rect("a4")
    where = pymupdf.Rect(
        mediabox.x0 + 30 * mm, mediabox.y0 + 20 * mm, mediabox.x1 - 15 * mm, mediabox.y1 - 20 * mm
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(".pdf.tmp")
    writer = pymupdf.DocumentWriter(str(tmp_out))
    more = True
    pages = 0
    while more and pages < 2000:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
        pages += 1
    writer.close()
    tmp_out.replace(out)
    return PdfResult(out, "pymupdf", time.perf_counter() - t0, pages)


def render_pdf(html_text: str, out: Path, engine: str = "auto") -> PdfResult:
    """Render with the requested engine; ``auto`` tries Chromium, then PyMuPDF."""
    if engine == "none":
        raise PdfEngineError("PDF отключён (--pdf-engine none)")
    errors = []
    if engine in ("auto", "chromium"):
        try:
            return chromium_pdf(html_text, out)
        except PdfEngineError as exc:
            errors.append(f"chromium: {exc}")
            if engine == "chromium":
                raise
    try:
        return pymupdf_pdf(html_text, out)
    except Exception as exc:  # MuPDF raises plain RuntimeError on layout problems
        errors.append(f"pymupdf: {exc}")
        raise PdfEngineError("; ".join(errors)) from exc
