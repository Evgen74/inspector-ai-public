"""`inspector-ml-api`: run the internal ml-api, or render one page/tile from the command line.

inspector-ml-api serve                                   # 127.0.0.1:8090 (make ml-api-dev); Docker: see docs/runbook/DOCKER.md
                                                         # (INSPECTOR_ML_API_HOST=0.0.0.0 + INSPECTOR_ML_API_ALLOW_REMOTE=1)
inspector-ml-api info   --file F0201 --page 17
inspector-ml-api render --file F0201 --page 17 --width 1600 --out /tmp/p17.png
inspector-ml-api render --file F0201 --page 17 --bbox 0.1,0.2,0.4,0.5 --dpi 150 --out /tmp/crop.png
inspector-ml-api tile   --file F0201 --page 17 --level 12 --x 3 --y 2 --out /tmp/t.png
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
from pathlib import Path

from inspector_common.errors import InspectorError


def _bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ожидается x0,y0,x1,y1 (доли страницы 0…1)")
    return parts[0], parts[1], parts[2], parts[3]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="inspector-ml-api", description="Внутренний ml-api «Инспектор ИИ»: отрисовка страниц PDF"
    )
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Запустить HTTP-сервис (FastAPI + uvicorn)")
    serve.add_argument("--host", default=os.environ.get("INSPECTOR_ML_API_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("INSPECTOR_ML_API_PORT", "8090")))
    serve.add_argument("--workers", type=int, default=int(os.environ.get("INSPECTOR_ML_API_WORKERS", "1")))
    serve.add_argument("--log-level", default="info")
    for name, help_text in (
        ("info", "Геометрия страницы и пирамиды плиток"),
        ("render", "Страница или фрагмент в PNG"),
        ("tile", "Одна плитка в PNG"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--file", required=True, help="file_id манифеста (F0201)")
        cmd.add_argument("--page", type=int, required=True, help="номер страницы PDF, с 1")
        if name == "render":
            cmd.add_argument("--dpi", type=float)
            cmd.add_argument("--width", type=int)
            cmd.add_argument("--bbox", type=_bbox)
        if name == "tile":
            cmd.add_argument("--level", type=int, required=True)
            cmd.add_argument("--x", type=int, required=True)
            cmd.add_argument("--y", type=int, required=True)
        if name in ("render", "tile"):
            cmd.add_argument("--out", type=Path, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        try:
            loopback = ipaddress.ip_address(args.host).is_loopback
        except ValueError:
            loopback = args.host == "localhost"
        # Docker: the container network is the boundary, so the compose file opts in with
        # INSPECTOR_ML_API_ALLOW_REMOTE=1 (the port is not published to the host). Native runs stay loopback-only.
        allow_remote = os.environ.get("INSPECTOR_ML_API_ALLOW_REMOTE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not loopback and not allow_remote:
            print("ml-api — внутренний сервис: слушайте только 127.0.0.1 или localhost.", file=sys.stderr)
            return 2
        uvicorn.run(
            "inspector_ml_api.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level=args.log_level,
        )
        return 0

    from inspector_ml_api.files import RegistryFileResolver
    from inspector_ml_api.render import PageRenderer, RenderRequestError

    renderer = PageRenderer()
    try:
        pdf = RegistryFileResolver().resolve(args.file)
        started = time.perf_counter()
        if args.command == "info":
            print(
                json.dumps(
                    {
                        "file_id": pdf.file_id,
                        "object_id": pdf.object_id,
                        **renderer.info(pdf.path, args.page).to_json(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "render":
            png, meta = renderer.render_image(
                pdf.path, args.page, dpi=args.dpi, width=args.width, bbox=args.bbox
            )
        else:
            png = renderer.render_tile(pdf.path, args.page, args.level, args.x, args.y)
            meta = {}
        args.out.write_bytes(png)
        ms = round((time.perf_counter() - started) * 1000)
        print(
            f"{args.out}: {len(png)} байт за {ms} мс {json.dumps(meta, ensure_ascii=False) if meta else ''}".rstrip()
        )
        return 0
    except InspectorError as err:
        print(err.detail, file=sys.stderr)
        return 1
    except RenderRequestError as err:
        print(f"{err.code}: {err.details}", file=sys.stderr)
        return 1
    finally:
        renderer.close()


if __name__ == "__main__":
    sys.exit(main())
