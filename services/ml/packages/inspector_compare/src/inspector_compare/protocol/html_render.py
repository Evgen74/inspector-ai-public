"""Protocol JSON → self-contained HTML in the Приложение 2 look (the source of the PDF; also usable by the web UI).

The page CSS mirrors the DOCX: A4 portrait, @page margins 20/15/20/30 mm, «Segoe UI» with Selawik and system
fallbacks, #0F1115 ink, 16.5 pt section headings, 11.5 pt tables with 0.5 pt single borders, repeated table headers.
No external resources are referenced (no network), so any local HTML→PDF engine can print it.
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from inspector_compare.protocol import texts as T

CSS = """
@page { size: A4 portrait; margin: 20mm 15mm 20mm 30mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Segoe UI", "Selawik", "Helvetica Neue", Arial, "Apple Color Emoji", "Noto Color Emoji",
       sans-serif; color: #0F1115; font-size: 12pt; line-height: 1.35; margin: 0; }
h1, h2 { font-size: 16.5pt; font-weight: 700; margin: 24pt 0 12pt; page-break-after: avoid; }
h1 { margin-top: 0; }
h3 { font-size: 15pt; font-weight: 700; margin: 18pt 0 8pt; page-break-after: avoid; }
h4 { font-size: 12.5pt; font-weight: 700; margin: 12pt 0 4pt; page-break-after: avoid; }
p.header { margin: 0 0 8pt; }
p.header b { font-weight: 700; }
p.note { font-size: 10pt; font-style: italic; color: #555B66; margin: 2pt 0; }
p.banner { font-size: 11pt; font-style: italic; color: #555B66; margin: 0 0 6pt; }
table { border-collapse: collapse; width: 100%; margin: 0 0 10pt; font-size: 11.5pt; }
table.small { font-size: 9.5pt; }
table.tiny { font-size: 8pt; }
th, td { border: 0.5pt solid #0F1115; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { font-weight: 700; background: #FFFFFF; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
td.num, td.code { white-space: nowrap; }
.appendix { page-break-before: always; }
.card { margin-bottom: 8pt; }
.card > table { page-break-inside: auto; }
.thumbs { margin: 0 0 12pt; }
figure.thumb { display: inline-block; width: 48%; margin: 0 1% 8pt 0; vertical-align: top;
               page-break-inside: avoid; }
figure.thumb img { width: 100%; max-height: 95mm; object-fit: contain; border: 0.5pt solid #555B66; }
figure.thumb figcaption { font-size: 8.5pt; color: #555B66; margin-top: 2pt; }
.kv th { width: 32%; }
.sign { margin-top: 24pt; }
"""


def _e(value: Any, default: str = "—") -> str:
    if value is None or value == "":
        return html.escape(default)
    return html.escape(str(value))


_CODE_CELL = re.compile(
    r"^(?:[A-Z]{1,4}\d?-\d{3}|FREE-[A-Z]+-\d{3}|(?:F\d{4}|U[0-9a-f]{8}-\d{4})|Б\.\d+|\d{1,3})$"
)


def _td(value: Any) -> str:
    cls = ' class="code"' if isinstance(value, int) or _CODE_CELL.match(str(value or "")) else ""
    return f"<td{cls}>{_e(value, '')}</td>"


def _table(header: Sequence[str], rows: Iterable[Sequence[Any]], cls: str = "") -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in header)
    body = "".join("<tr>" + "".join(_td(v) for v in row) + "</tr>" for row in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _kv(pairs: Sequence[tuple[str, Any]]) -> str:
    rows = "".join(f"<tr><th>{_e(k)}</th><td>{_e(v).replace(chr(10), '<br>')}</td></tr>" for k, v in pairs)
    return f'<table class="kv small"><tbody>{rows}</tbody></table>'


def _thumbs_html(thumbs: Sequence[Any]) -> str:
    figures = "".join(
        f'<figure class="thumb"><img alt="{_e(t.caption)}" '
        f'src="data:image/png;base64,{base64.b64encode(t.png).decode("ascii")}">'
        f"<figcaption>{_e(t.caption)}</figcaption></figure>"
        for t in thumbs
    )
    return f'<div class="thumbs">{figures}</div>'


def render_html(protocol: dict[str, Any], thumbnails: Mapping[str, Sequence[Any]] | None = None) -> str:
    """The protocol as one self-contained HTML page (the PDF view); ``thumbnails`` (card_no → Thumbnail) are
    embedded as data URIs under their evidence cards."""
    h = protocol["header"]
    obj = protocol["object"]
    L = T.HEADER_LABELS
    a2 = protocol["appendix2"]
    parts: list[str] = [
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">',
        f"<title>{_e(h['title'])}</title><style>{CSS}</style></head><body>",
        f"<h1>{_e(h['title'])}</h1>",
        f'<p class="header"><b>{L["object"]}</b> {_e(obj.get("name"), "нет данных")}<br>'
        f"<b>{L['address']}</b> {_e(obj.get('address'), 'нет данных')}</p>",
        f'<p class="header"><b>{L["case"]}</b> {_e(obj.get("supervision_case_no"), "нет данных")}<br>'
        f"<b>{L['customer']}</b> {_e(obj.get('customer'), 'нет данных')}<br>"
        f"<b>{L['contractor']}</b> {_e(obj.get('contractor'), 'нет данных')}<br>"
        f"<b>{L['date']}</b> {_e(h['generated_at_ru'])}<br>"
        f"<b>{L['version']}</b> {_e(h['version_line'])}<br>"
        f"<b>{L['status']}</b> {_e(h['status_line'])}"
        + (
            f"<br><b>{L['scenario']}</b> {_e(h['scenario_line'].removeprefix(L['scenario']).strip())}"
            if h.get("scenario_line")
            else ""
        )
        + "</p>",
    ]
    s1 = a2["section1_load_status"]
    parts.append(f"<h2>{T.SECTION_TITLES[1]}</h2>")
    parts.append(
        _table(
            T.COLUMNS[1],
            [
                (
                    r["stage_ru"],
                    r["status_ru"],
                    r["files_loaded_text"],
                    r.get("files_expected") or "—",
                    r["comment"],
                )
                for r in s1["rows"]
            ],
        )
    )
    if s1.get("scenario_line"):
        parts.append(f'<p class="header">{_e(s1["scenario_line"])}</p>')
    s2 = a2["section2_summary"]
    parts.append(f"<h2>{T.SECTION_TITLES[2]}</h2>")
    parts.append(_table(T.COLUMNS[2], [(r["label_ru"], r["count"], r["percent_text"]) for r in s2["rows"]]))
    parts += [f'<p class="note">* {_e(n)}</p>' for n in s2.get("footnotes") or []]
    s3 = a2["section3_not_checked_no_id"]
    parts.append(f"<h2>{_e(T.SECTION_TITLES[3].format(n=s3['count']))}</h2>")
    if not s3["rows"]:
        parts.append(f"<p>{T.EMPTY_SECTION}</p>")
    else:
        parts.append(
            _table(
                T.COLUMNS[3],
                [
                    (
                        r["no"],
                        r["parameter_code"],
                        r["section_ru"],
                        r["parameter_name"],
                        r["missing_document"],
                    )
                    for r in s3["rows"]
                ],
            )
        )
    for key, num in (("section4_critical", 4), ("section5_substantial", 5)):
        sec = a2[key]
        parts.append(f"<h2>{_e(T.SECTION_TITLES[num].format(n=sec['count']))}</h2>")
        if not sec["rows"]:
            parts.append(f"<p>{T.EMPTY_SECTION}</p>")
        else:
            parts.append(
                _table(
                    T.COLUMNS[4],
                    [
                        (
                            r["no"],
                            r["section_ru"],
                            r["parameter_label"],
                            r["pd"],
                            r["rd"],
                            r["id"],
                            r["deviation"]["text"],
                            r["inspector_decision_ru"],
                        )
                        for r in sec["rows"]
                    ],
                    "small",
                )
            )
    s6 = a2["section6_ai_suspicions"]
    parts.append(f"<h2>{_e(T.SECTION_TITLES[6].format(n=s6['count']))}</h2>")
    if not s6["rows"]:
        parts.append(f"<p>{T.EMPTY_SECTION}</p>")
    else:
        parts.append(
            _table(
                T.COLUMNS[6],
                [
                    (
                        r["no"],
                        r["method_ru"],
                        f"{r['description']} [карточка {r['card_ref']}]",
                        r["pd"],
                        r["rd"],
                        r["id"],
                        r["inspector_decision_ru"],
                        r["rejection_reason"],
                        r["ai_comment"],
                    )
                    for r in s6["rows"]
                ],
                "small",
            )
        )
    s7 = a2["section7_resolution"]
    parts.append(f"<h2>{T.SECTION_TITLES[7]}</h2><h3>{T.SUBSECTION_71}</h3>")
    if not s7["critical"]:
        parts.append(f"<p>{T.EMPTY_SECTION}</p>")
    else:
        parts.append(
            _table(
                T.COLUMNS[71],
                [(r["no"], r["work_type"], r["recommendation"]) for r in s7["critical"]],
                "small",
            )
        )
    parts.append(f"<h3>{T.SUBSECTION_72}</h3>")
    if not s7["substantial"]:
        parts.append(f"<p>{T.EMPTY_SECTION}</p>")
    else:
        parts.append(
            _table(
                T.COLUMNS[72],
                [(r["no"], r["violation_kind"], r["recommendation"]) for r in s7["substantial"]],
                "small",
            )
        )

    tz = protocol["tz92_tables"]
    parts.append(
        f'<div class="appendix"><h2>{T.APPENDIX_TITLES["A"]}</h2><p class="banner">{_e(tz.get("banner_ru"))}</p>'
    )
    parts.append(f"<h4>{T.APPENDIX_TITLES['A1']}</h4>")
    if tz.get("a1_completeness"):
        parts.append(
            _table(
                (
                    "Код",
                    "Параметр",
                    "Статус",
                    "Отсутствует стадия",
                    "Документ",
                    "Комплектность / основание",
                    "Действие",
                ),
                [
                    (
                        r["parameter_code"],
                        r["parameter_name"],
                        T.a1_cells(r)[0],
                        T.a1_cells(r)[1],
                        r.get("document") or "—",
                        T.a1_cells(r)[2],
                        r.get("action_ru") or "—",
                    )
                    for r in tz["a1_completeness"]
                ],
                "tiny",
            )
        )
    parts.append(f"<h4>{T.APPENDIX_TITLES['A2']}</h4>")
    if tz.get("a2_candidates"):
        parts.append(
            _table(
                (
                    "Карточка",
                    "Параметр",
                    "Места",
                    "Ожидаемое",
                    "Фактическое",
                    "Отклонение",
                    "Риск",
                    "Уверенность",
                ),
                [
                    (
                        r["card_ref"],
                        r["parameter_label"],
                        ", ".join(r.get("locations") or []),
                        r.get("expected") or "—",
                        r.get("actual") or "—",
                        r.get("deviation_text") or "—",
                        T.enum_ru("RiskLevel", r.get("risk_level")),
                        f"{float(r.get('confidence') or 0):.2f}".replace(".", ","),
                    )
                    for r in tz["a2_candidates"]
                ],
                "tiny",
            )
        )
    parts.append(
        f"<h4>{T.APPENDIX_TITLES['A3']}</h4><p>Решений инспектора нет (протокол предварительный).</p>"
    )
    parts.append(f"<h4>{T.APPENDIX_TITLES['A4']}</h4>")
    parts.append(
        _table(
            ("Параметр", "Кем", "Основание"),
            [
                (r["parameter_label"], "система", r.get("reason_ru") or "—")
                for r in tz["a4_negative_verified"]
            ],
            "small",
        )
        if tz.get("a4_negative_verified")
        else "<p>Нет.</p>"
    )
    parts.append(f"<h4>{T.APPENDIX_TITLES['A5']}</h4>")
    if tz.get("a5_hypotheses"):
        parts.append(
            _table(
                ("Карточка", "Код", "Описание", "Уверенность", "Нормативная база", "Привязка"),
                [
                    (
                        r["card_ref"],
                        r.get("parameter_code") or "—",
                        r["description"],
                        f"{float(r.get('confidence') or 0):.2f}".replace(".", ","),
                        r.get("normative_base") or "—",
                        r.get("evidence_bind_status") or "—",
                    )
                    for r in tz["a5_hypotheses"]
                ],
                "tiny",
            )
        )
    parts.append("</div>")

    parts.append(f'<div class="appendix"><h2>{T.APPENDIX_TITLES["B"]}</h2>')
    for card in protocol.get("evidence_cards") or []:
        sources = T.source_lines(card.get("sources"))
        parts.append(
            f'<div class="card"><h4>Карточка {_e(card["card_no"])}. {_e(card["parameter_label"])}</h4>'
        )
        parts.append(
            _kv(
                [
                    ("Идентификаторы находок", ", ".join(card.get("finding_ids") or [])),
                    ("Код параметра", card["parameter_code"]),
                    ("Места", ", ".join(card.get("locations") or [])),
                    ("Ожидаемое значение", card.get("expected_value")),
                    ("Фактическое значение", card.get("actual_value")),
                    ("Критичность", card.get("criticality")),
                    (
                        "Уровень риска / приоритет",
                        T.risk_priority(card.get("risk_level"), card.get("review_priority")),
                    ),
                    ("Источники", sources),
                    ("Обоснование", card.get("rationale")),
                    ("Версия правила", card.get("rule_version")),
                    ("Согласованное изменение", card.get("approved_change_ref") or "не найдено"),
                    (
                        "Решение инспектора",
                        T.DECISION_RU.get(card["inspector"]["status"], card["inspector"]["status"]),
                    ),
                ]
            )
        )
        if thumbnails and thumbnails.get(card["card_no"]):
            parts.append(_thumbs_html(thumbnails[card["card_no"]]))
        parts.append("</div>")
    parts.append("</div>")

    reg = protocol["input_registry"]
    parts.append(f'<div class="appendix"><h2>{T.APPENDIX_TITLES["V"]}</h2>')
    parts.append(
        _table(
            ("Файл", "Наименование", "Стадия", "Раздел", "Стр.", "SHA-256", "Использован", "Исключение"),
            [
                (
                    r["file_id"],
                    r.get("file_name") or "—",
                    T.file_stage_ru(r.get("stage"), r.get("manifest_stage")),
                    T.section_ru(r.get("section")),
                    r.get("pages") if r.get("pages") is not None else "—",
                    str(r["sha256"])[:12] + "…",
                    "да" if r["used"] else "нет",
                    r.get("exclusion_reason") or "—",
                )
                for r in reg["files"]
            ],
            "tiny",
        )
    )
    v = protocol["versions"]
    parts.append(
        _kv(
            [
                ("Версия конвейера", v.get("pipeline_version")),
                ("Версия Матрицы", v.get("matrix_version")),
                ("Версия правил сравнения", v.get("model_version")),
                ("Версия кода", v.get("code_version")),
                ("Версия контрактов", v.get("contract_version")),
                ("Хеш входного манифеста", protocol["input_manifest_hash"]),
                ("Хеш содержания протокола", protocol.get("content_sha256")),
            ]
        )
    )
    parts.append(
        '<p class="sign">Инспектор: ______________________ / ______________________ /<br>Дата: «____» ______________ 20__ г.</p>'
    )
    parts.append("</div></body></html>")
    return "".join(parts)
