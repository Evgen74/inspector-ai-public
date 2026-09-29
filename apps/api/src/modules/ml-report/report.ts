/** Module 10: weekly retraining report built from inspector decisions. Pure functions (no I/O) — see ml-report.service.ts. */

export interface DecisionRow {
  at: Date;
  decision: string;
  reason_code: string | null;
  param_code: string;
}

/** Section label of hypotheses that are not in the 132-parameter matrix (same wording as the dashboard). */
export const OUTSIDE_MATRIX = 'Вне матрицы';

const FREE_FAMILY_RU: Record<string, string> = {
  HEATING: 'отопление',
  WATER: 'водоснабжение',
  VENTILATION: 'вентиляция',
  STRUCTURE: 'конструкции',
  SITE: 'благоустройство участка',
  SEWER: 'канализация',
  ROOF: 'кровля',
  OTHER: 'прочее',
  LIGHTING: 'освещение',
  LIFT: 'лифты',
  FIRE: 'пожарная безопасность',
  FACADE: 'фасады',
  EVACUATION: 'эвакуация',
  ENERGY: 'энергоэффективность',
  ELECTRICAL: 'электроснабжение',
  ARCHITECTURE: 'архитектурные решения',
  ACCESSIBILITY: 'доступность для маломобильных',
  CONCRETE: 'бетонные работы',
};

/** «FREE-HEATING-001» → «вне матрицы: отопление» (the code stays in its own column). */
export function freeParamName(code: string): string {
  const family = code.split('-')[1] ?? '';
  return `вне матрицы: ${FREE_FAMILY_RU[family] ?? 'гипотеза ИИ'}`;
}

const isFree = (code: string) => code.startsWith('FREE');

/** dd.mm.yyyy of an ISO instant in Moscow time (UTC+3, no DST). */
export function ruDate(iso: string): string {
  const d = new Date(Date.parse(iso) + 3 * 3600_000).toISOString();
  return `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;
}

/** dd.mm.yyyy hh:mm in Moscow time. */
export function ruDateTime(iso: string): string {
  const d = new Date(Date.parse(iso) + 3 * 3600_000).toISOString();
  return `${ruDate(iso)} ${d.slice(11, 16)}`;
}

export interface ParamInfo {
  name: string;
  section: string;
}

export interface ReasonInfo {
  label: string;
  family: string | null;
}

export interface ReportInput {
  rows: DecisionRow[];
  from: Date;
  to: Date;
  params: Map<string, ParamInfo>;
  reasons: Map<string, ReasonInfo>;
  disputes: number;
  now?: Date;
}

export interface Recommendation {
  severity: 'info' | 'warning';
  text: string;
}

type Json = Record<string, unknown>;

const CONFIRMED = 'CONFIRMED_VIOLATION';
const REJECTED = 'NEGATIVE_VERIFIED';
const DAY = 86_400_000;

const REASON_TIPS: Record<string, string> = {
  OCR_ERROR: 'проверить качество распознавания страниц (OCR) и добавить проблемные листы в набор дообучения',
  EXTRACTION_ERROR: 'уточнить шаблоны извлечения значений и единиц измерения',
  CV_ERROR: 'дообучить распознавание графики (линии, условные обозначения, масштаб)',
  LINKING_ERROR: 'улучшить привязку значений к объектам, листам и помещениям',
  WITHIN_TOLERANCE: 'пересмотреть допуски сравнения',
  EQUIVALENT_SOLUTION: 'расширить словарь равнозначных обозначений и формулировок',
  WRONG_REVISION: 'проверить выбор актуальной редакции документа',
  DUPLICATE: 'усилить склейку дублирующихся находок',
};

export const pct = (v: number | null): string => (v === null ? '—' : `${Math.round(v * 100)}%`);

const ratio = (a: number, b: number): number | null => (b > 0 ? Math.round((a / b) * 1000) / 1000 : null);

function weekStart(d: Date): Date {
  const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dow = (x.getUTCDay() + 6) % 7; // Monday = 0
  return new Date(x.getTime() - dow * DAY);
}

interface Counter {
  confirmed: number;
  rejected: number;
}

function bump(map: Map<string, Counter>, key: string, decision: string): void {
  const c = map.get(key) ?? { confirmed: 0, rejected: 0 };
  if (decision === CONFIRMED) c.confirmed += 1;
  else if (decision === REJECTED) c.rejected += 1;
  map.set(key, c);
}

const counted = (r: DecisionRow): boolean => r.decision === CONFIRMED || r.decision === REJECTED;

export function buildReport(input: ReportInput): Json {
  const { from, to, params, reasons } = input;
  const inPeriod = input.rows.filter((r) => counted(r) && r.at >= from && r.at < to);
  const clarification = input.rows.filter((r) => r.decision === 'CLARIFICATION_REQUIRED' && r.at >= from && r.at < to).length;
  const confirmed = inPeriod.filter((r) => r.decision === CONFIRMED).length;
  const rejected = inPeriod.length - confirmed;

  const byParam = new Map<string, Counter>();
  const bySection = new Map<string, Counter>();
  const reasonCount = new Map<string, number>();
  for (const r of inPeriod) {
    bump(byParam, r.param_code, r.decision);
    bump(bySection, params.get(r.param_code)?.section ?? (isFree(r.param_code) ? OUTSIDE_MATRIX : '—'), r.decision);
    if (r.decision === REJECTED) reasonCount.set(r.reason_code ?? 'OTHER', (reasonCount.get(r.reason_code ?? 'OTHER') ?? 0) + 1);
  }
  const rows = (m: Map<string, Counter>) =>
    [...m.entries()]
      .map(([key, c]) => ({ key, ...c, total: c.confirmed + c.rejected, precision: ratio(c.confirmed, c.confirmed + c.rejected) }))
      .sort((a, b) => b.total - a.total || a.key.localeCompare(b.key));
  const paramRows = rows(byParam).map(({ key, ...rest }) => ({ param_code: key, name: params.get(key)?.name ?? (isFree(key) ? freeParamName(key) : key), section: params.get(key)?.section ?? (isFree(key) ? OUTSIDE_MATRIX : '—'), ...rest }));
  const sectionRows = rows(bySection).map(({ key, ...rest }) => ({ section: key, ...rest }));
  const reasonRows = [...reasonCount.entries()]
    .map(([code, count]) => ({ reason_code: code, label: reasons.get(code)?.label ?? code, family: reasons.get(code)?.family ?? null, count, share: ratio(count, rejected) }))
    .sort((a, b) => b.count - a.count);

  // Precision trend: 8 ISO weeks (Monday start) ending with the week of `to - 1ms`.
  const lastWeek = weekStart(new Date(to.getTime() - 1));
  const trend: Array<{ week_start: string; confirmed: number; rejected: number; precision: number | null }> = [];
  for (let i = 7; i >= 0; i -= 1) {
    const start = new Date(lastWeek.getTime() - i * 7 * DAY);
    const end = new Date(start.getTime() + 7 * DAY);
    const inWeek = input.rows.filter((r) => counted(r) && r.at >= start && r.at < end);
    const c = inWeek.filter((r) => r.decision === CONFIRMED).length;
    trend.push({ week_start: start.toISOString().slice(0, 10), confirmed: c, rejected: inWeek.length - c, precision: ratio(c, inWeek.length) });
  }

  const recommendations = recommend({ decided: inPeriod.length, paramRows, sectionRows, reasonRows, rejected, trend, disputes: input.disputes });
  return {
    period: { from: from.toISOString(), to: to.toISOString() },
    generated_at: (input.now ?? new Date()).toISOString(),
    totals: { decided: inPeriod.length, confirmed, rejected, clarification, precision: ratio(confirmed, inPeriod.length), disputes: input.disputes },
    by_param: paramRows,
    by_section: sectionRows,
    by_reason: reasonRows,
    trend,
    recommendations,
  };
}

interface RecInput {
  decided: number;
  paramRows: Array<{ param_code: string; name: string; confirmed: number; rejected: number; total: number; precision: number | null }>;
  sectionRows: Array<{ section: string; confirmed: number; rejected: number; total: number; precision: number | null }>;
  reasonRows: Array<{ reason_code: string; label: string; count: number; share: number | null }>;
  rejected: number;
  trend: Array<{ week_start: string; precision: number | null; confirmed: number; rejected: number }>;
  disputes: number;
}

export function recommend(i: RecInput): Recommendation[] {
  const out: Recommendation[] = [];
  if (i.decided === 0) {
    return [{ severity: 'info', text: 'За период нет решений инспекторов: отчёт пуст. Завершите верификацию хотя бы одного протокола.' }];
  }
  if (i.decided < 10) out.push({ severity: 'info', text: `Решений за период мало (${i.decided}); выводы предварительные.` });
  for (const p of i.paramRows.filter((x) => x.total >= 3 && x.rejected / x.total >= 0.6).slice(0, 5)) {
    out.push({
      severity: 'warning',
      text: `Параметр ${p.param_code} «${p.name}»: отклонено ${p.rejected} из ${p.total} (${pct(1 - (p.precision ?? 0))}). Проверьте правило сравнения и пороги; добавьте случаи в набор дообучения.`,
    });
  }
  for (const s of i.sectionRows.filter((x) => x.total >= 5 && x.rejected / x.total >= 0.5).slice(0, 3)) {
    out.push({ severity: 'warning', text: `Раздел ${s.section}: доля отклонений ${pct(1 - (s.precision ?? 0))} (${s.rejected} из ${s.total}). Требуется разбор извлечения для этого раздела.` });
  }
  const top = i.reasonRows[0];
  if (top && i.rejected >= 3 && (top.share ?? 0) >= 0.3) {
    const tip = REASON_TIPS[top.reason_code];
    out.push({ severity: 'warning', text: `Главная причина отклонений — «${top.label}» (${top.count} из ${i.rejected}, ${pct(top.share)})${tip ? `: ${tip}` : '.'}` });
  }
  const withData = i.trend.filter((t) => t.precision !== null);
  if (withData.length >= 2) {
    const last = withData[withData.length - 1]!;
    const prev = withData[withData.length - 2]!;
    const delta = (last.precision ?? 0) - (prev.precision ?? 0);
    if (delta <= -0.1) out.push({ severity: 'warning', text: `Точность кандидатов снизилась с ${pct(prev.precision)} до ${pct(last.precision)} (неделя с ${ruDate(last.week_start)}). Проверьте последние изменения правил и моделей.` });
    else if (delta >= 0.1) out.push({ severity: 'info', text: `Точность кандидатов выросла с ${pct(prev.precision)} до ${pct(last.precision)} (неделя с ${ruDate(last.week_start)}).` });
  }
  if (i.disputes > 0) out.push({ severity: 'warning', text: `Открыто споров с ИИ: ${i.disputes}. Передайте их куратору набора данных.` });
  const stable = i.paramRows.filter((x) => x.confirmed >= 3 && x.rejected === 0).map((x) => x.param_code);
  if (stable.length) out.push({ severity: 'info', text: `Параметры без единого отклонения (${stable.slice(0, 8).join(', ')}): кандидаты в эталонный набор (GOLD).` });
  if (out.length === 0) out.push({ severity: 'info', text: 'Существенных отклонений в качестве кандидатов не выявлено.' });
  return out;
}

const esc = (v: unknown): string => String(v ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] as string);

/** Self-contained printable HTML page (browser «Печать» → PDF). */
export function renderHtml(report: Json): string {
  const t = report.totals as Json;
  const period = report.period as { from: string; to: string };
  const table = (head: string[], body: unknown[][]) =>
    `<table><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${head.length}">Нет данных</td></tr>`}</tbody></table>`;
  const byParam = report.by_param as Array<Json>;
  const bySection = report.by_section as Array<Json>;
  const byReason = report.by_reason as Array<Json>;
  const trend = report.trend as Array<Json>;
  const recs = report.recommendations as Recommendation[];
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Отчёт по дообучению</title>
<style>body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1f1f1f}h1{font-size:22px}h2{font-size:16px;margin-top:24px}
table{border-collapse:collapse;width:100%;margin-top:6px}th,td{border:1px solid #d0d0d0;padding:4px 8px;text-align:left}th{background:#f3f3f3}
.kpi{display:flex;gap:16px;flex-wrap:wrap}.kpi div{border:1px solid #d0d0d0;padding:8px 14px;border-radius:6px}.kpi b{display:block;font-size:20px}
.warning{color:#ad6800}@media print{body{margin:8mm}}</style></head><body>
<h1>Отчёт по дообучению</h1>
<p>Период: ${esc(ruDate(period.from))} — ${esc(ruDate(period.to))}. Сформирован: ${esc(ruDateTime(String(report.generated_at)))} (МСК).</p>
<div class="kpi"><div><b>${esc(t.decided)}</b>решений</div><div><b>${esc(t.confirmed)}</b>подтверждено</div><div><b>${esc(t.rejected)}</b>отклонено</div><div><b>${esc(pct(t.precision as number | null))}</b>точность кандидатов</div><div><b>${esc(t.disputes)}</b>споров с ИИ</div></div>
<h2>Рекомендации</h2><ul>${recs.map((r) => `<li class="${r.severity}">${esc(r.text)}</li>`).join('')}</ul>
<h2>Динамика точности по неделям</h2>${table(['Неделя с', 'Подтверждено', 'Отклонено', 'Точность'], trend.map((w) => [ruDate(String(w.week_start)), w.confirmed, w.rejected, pct(w.precision as number | null)]))}
<h2>По причинам отклонения</h2>${table(['Причина', 'Кол-во', 'Доля'], byReason.map((r) => [r.label, r.count, pct(r.share as number | null)]))}
<h2>По разделам</h2>${table(['Раздел', 'Подтверждено', 'Отклонено', 'Точность'], bySection.map((r) => [r.section, r.confirmed, r.rejected, pct(r.precision as number | null)]))}
<h2>По параметрам</h2>${table(['Код', 'Параметр', 'Раздел', 'Подтверждено', 'Отклонено', 'Точность'], byParam.map((r) => [r.param_code, r.name, r.section, r.confirmed, r.rejected, pct(r.precision as number | null)]))}
</body></html>`;
}
