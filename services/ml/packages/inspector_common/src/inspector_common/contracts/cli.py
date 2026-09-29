"""`inspector-contracts`: regenerate and check the contract artifacts, validate JSON files.

inspector-contracts gen                    # rewrite generated files (enums.schema.json, enums.py)
inspector-contracts check                  # exit 1 on drift or on an invalid contract/example
inspector-contracts validate finding a.json [b.json …]
inspector-contracts list                   # schema names
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from inspector_common.contracts import codegen, loader


def _cmd_gen(_: argparse.Namespace) -> int:
    changed = codegen.generate(write=True)
    for path, did_change in changed.items():
        print(f"{'обновлён' if did_change else 'без изменений'}: {path}")
    return 0


def _cmd_check(_: argparse.Namespace) -> int:
    from inspector_common.contracts.selfcheck import run_selfcheck

    problems = run_selfcheck()
    for problem in problems:
        print(f"ОШИБКА: {problem}", file=sys.stderr)
    if not problems:
        print(
            f"Контракты в порядке: {len(loader.schema_names())} схем, {len(loader.load_enums())} перечислений, "
            f"{len(loader.load_errors())} кодов ошибок."
        )
    return 1 if problems else 0


def _cmd_validate(args: argparse.Namespace) -> int:
    failed = 0
    for file in args.files:
        path = Path(file)
        text = path.read_text(encoding="utf-8")
        docs = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if path.suffix == ".jsonl"
            else [json.loads(text)]
        )
        for index, doc in enumerate(docs):
            errors = loader.validation_errors(args.schema, doc)
            where = f"{path}#{index + 1}" if len(docs) > 1 else str(path)
            if errors:
                failed += 1
                print(f"НЕВАЛИДНО {where}:", file=sys.stderr)
                for error in errors[:20]:
                    print(f"  {error}", file=sys.stderr)
            else:
                print(f"ок {where}")
    return 1 if failed else 0


def _cmd_list(_: argparse.Namespace) -> int:
    for name in loader.schema_names():
        print(name)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inspector-contracts", description="Контракты «Инспектор ИИ»: генерация и проверка."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gen", help="Перегенерировать производные файлы из enums.yaml и errors.yaml").set_defaults(
        func=_cmd_gen
    )
    sub.add_parser("check", help="Проверить контракты, примеры и отсутствие расхождений").set_defaults(
        func=_cmd_check
    )
    p_validate = sub.add_parser("validate", help="Проверить JSON/JSONL-файлы по схеме")
    p_validate.add_argument("schema", help="Имя схемы, например finding или submission.strict")
    p_validate.add_argument("files", nargs="+")
    p_validate.set_defaults(func=_cmd_validate)
    sub.add_parser("list", help="Список схем").set_defaults(func=_cmd_list)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
