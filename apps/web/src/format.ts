/** Russian formatting (08 §3.4): ru-RU numbers, Europe/Moscow times, plural forms. */

const dateTime = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

const dateTimeSec = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

const dateOnly = new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', year: 'numeric' });

const integer = new Intl.NumberFormat('ru-RU');
const oneDecimal = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const plural = new Intl.PluralRules('ru-RU');

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : dateTime.format(d).replace(',', '');
}

/** dd.mm.yyyy hh:mm:ss in Moscow time (log lines). */
export function formatDateTimeSec(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : dateTimeSec.format(d).replace(',', '');
}

/** dd.mm.yyyy in Moscow time; a bare YYYY-MM-DD is reformatted without any timezone shift. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (m) return `${m[3]}.${m[2]}.${m[1]}`;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : dateOnly.format(d);
}

export function formatInt(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : integer.format(n);
}

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  if (n < 1024) return `${integer.format(n)} Б`;
  if (n < 1024 * 1024) return `${oneDecimal.format(n / 1024)} КБ`;
  if (n < 1024 * 1024 * 1024) return `${oneDecimal.format(n / 1024 / 1024)} МБ`;
  return `${oneDecimal.format(n / 1024 / 1024 / 1024)} ГБ`;
}

/** pluralRu(5, ['файл', 'файла', 'файлов']) → «файлов» */
export function pluralRu(n: number, forms: [one: string, few: string, many: string]): string {
  const rule = plural.select(n);
  return rule === 'one' ? forms[0] : rule === 'few' ? forms[1] : forms[2];
}

export function shortHash(sha: string | null | undefined, n = 8): string {
  if (!sha) return '—';
  return `${sha.slice(0, n)}…${sha.slice(-4)}`;
}

/** Batch texts sometimes carry an internal code in brackets («… (GROUND_TRUTH_INDEX)»): drop it for the reader. */
export function withoutInternalCodes(text: string | null | undefined): string {
  return (text ?? '').replace(/\s*\([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\)/g, '').trim();
}
