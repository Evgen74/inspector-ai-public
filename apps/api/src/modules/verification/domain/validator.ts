/**
 * AI rejection validator (05 §3.7, VER-22/23): a deterministic, explainable rule engine that runs on every
 * «Отклонить». It never sets a status by itself: AGREE/UNCERTAIN → NEGATIVE_VERIFIED, DISAGREE → the rejection
 * is held in CLARIFICATION_REQUIRED with an OPEN Dispute_Log row until the inspector re-decides (ТЗ §9.4 sample 2).
 *
 * Rules use only data the batch run provides (finding record, evidence refs, file registry). Rules that need
 * per-page text sources (R-OCR-1: «значение из текстового слоя, OCR не применялся») take them from
 * `textSources` and stay silent when the caller has none.
 */

export type AiVerdict = 'AGREE' | 'UNCERTAIN' | 'DISAGREE';

export interface ValidatorEvidence {
  stage: string;
  file_id: string;
  pdf_page_number: number;
  role?: string | null;
  localization?: string | null;
  geometry?: { boxes?: unknown[]; polygons?: unknown[] } | null;
}

export interface ValidatorFinding {
  findingId: string;
  paramCode: string;
  location: string;
  locationType: string | null;
  axis: string | null;
  comparisonResult: string | null;
  criticalityLevel: string | null;
  riskLevel: string | null;
  confidence: number | null;
  evidence: ValidatorEvidence[];
  /** Locations of the finding group (the room index behind the atomic split). */
  groupLocations: string[];
}

export interface ValidatorFile {
  fileId: string;
  objectId: string;
  docStage: string | null;
  manifestStage: string | null;
}

export interface ValidatorDuplicate {
  findingId: string;
  paramCode: string;
  location: string;
}

export interface ValidatorInput {
  reasonCode: string;
  finding: ValidatorFinding;
  approvedChangeRef?: string | null;
  approvedChangeFileId?: string | null;
  correctFileId?: string | null;
  duplicate?: ValidatorDuplicate | null;
  files: ReadonlyMap<string, ValidatorFile>;
  /** `${file_id}#${page}` → TextSource codes of the tokens behind the value (empty when unknown). */
  textSources?: ReadonlyMap<string, string[]>;
  /** Russian label of an enum code (ComparisonResult, …). */
  label: (enumName: string, code: string | null | undefined) => string;
}

export interface ValidatorResult {
  verdict: AiVerdict;
  /** Shown as «NN%» in the AI comment (Приложение 2 §6). */
  confidence: number;
  ruleIds: string[];
  /** Russian argument appended to the §9.4 comment; null for a plain AGREE. */
  argument: string | null;
  /** Pages the dispute banner shows (the contested fragments). */
  evidence: ValidatorEvidence[];
}

interface Hit {
  rule: string;
  verdict: Exclude<AiVerdict, 'AGREE'>;
  confidence: number;
  argument: string;
}

/** Discrepancies that are not measured, so a tolerance cannot absorb them (R-TOL-1). */
const QUALITATIVE_RESULTS = new Set(['CONFIGURATION_MISMATCH', 'MISSING_DESIGN_ELEMENT', 'EXTRA_ELEMENT', 'MATERIAL_SUBSTITUTION']);

/** Wording of an RD change-registration record («Изм.», «лист регистрации изменений»), not an approval (R-APC-1). */
const RD_CHANGE_LOG_RE = /(^|[^а-яё])изм\.|регистрац\S*\s+изменени|лист\S*\s+изменени|таблиц\S*\s+(регистрации\s+)?изменени|извещени\S*\s+об\s+изменени/i;

const round2 = (x: number) => Math.round(x * 100) / 100;

/** AGREE strength: the lower the model's own confidence in the violation, the more the AI agrees with a rejection. */
export function agreeConfidence(modelConfidence: number | null): number {
  const c = modelConfidence ?? 0.5;
  return round2(Math.min(0.95, Math.max(0.5, 1 - c / 2)));
}

function contested(f: ValidatorFinding): ValidatorEvidence[] {
  const actual = f.evidence.filter((e) => e.role === 'ACTUAL' || e.role === 'SUPPORTING_ACTUAL');
  return actual.length ? actual : f.evidence;
}

function hits(input: ValidatorInput): Hit[] {
  const f = input.finding;
  const out: Hit[] = [];
  switch (input.reasonCode) {
    case 'APPROVED_CHANGE': {
      const ref = (input.approvedChangeRef ?? '').trim();
      const file = input.approvedChangeFileId ? input.files.get(input.approvedChangeFileId) : undefined;
      const ownEvidence = input.approvedChangeFileId ? f.evidence.some((e) => e.file_id === input.approvedChangeFileId) : false;
      const rdFile = file && (file.docStage === 'RD' || file.manifestStage === 'RD');
      if (RD_CHANGE_LOG_RE.test(ref) || ownEvidence || rdFile) {
        out.push({
          rule: 'R-APC-1',
          verdict: 'DISAGREE',
          confidence: 0.9,
          argument:
            'Запись в таблице регистрации изменений РД (или сам лист РД) не является согласованием изменения ПД; ' +
            'требуется документ утверждения изменения или заключение экспертизы.',
        });
      } else if (!input.approvedChangeFileId) {
        out.push({
          rule: 'R-APC-2',
          verdict: 'UNCERTAIN',
          confidence: 0.6,
          argument: 'Документ согласования не загружен в комплект; для трассируемости рекомендуется его дозагрузка.',
        });
      }
      break;
    }
    case 'WRONG_REVISION': {
      const target = input.correctFileId ?? '';
      const used = f.evidence.find((e) => e.file_id === target);
      if (used) {
        out.push({
          rule: 'R-REV-1',
          verdict: 'DISAGREE',
          confidence: 0.9,
          argument: `Указанная редакция (${target}) уже использована как источник сравнения (${used.stage}, стр. ${used.pdf_page_number}).`,
        });
      } else {
        const file = input.files.get(target);
        const replaced = contested(f)[0];
        const stage = file?.docStage ?? file?.manifestStage ?? null;
        if (file && replaced && stage && stage !== replaced.stage && !(stage === 'RD_ID_MIXED')) {
          out.push({
            rule: 'R-REV-2',
            verdict: 'UNCERTAIN',
            confidence: 0.6,
            argument: `Выбранный файл относится к стадии ${stage}, а оспариваемый источник — к стадии ${replaced.stage}.`,
          });
        }
      }
      break;
    }
    case 'WITHIN_TOLERANCE': {
      if (f.comparisonResult && QUALITATIVE_RESULTS.has(f.comparisonResult)) {
        out.push({
          rule: 'R-TOL-1',
          verdict: 'DISAGREE',
          confidence: 0.95,
          argument:
            `Расхождение «${input.label('ComparisonResult', f.comparisonResult)}» качественное: допуск к нему не ` +
            'применяется (отсутствие или изменение элемента не измеряется величиной отклонения).',
        });
      }
      break;
    }
    case 'OCR_ERROR': {
      const sources = input.textSources;
      const pages = contested(f);
      if (sources && pages.length) {
        const all = pages.map((e) => sources.get(`${e.file_id}#${e.pdf_page_number}`) ?? []);
        if (all.every((s) => s.length > 0 && s.every((x) => x === 'TEXT_LAYER'))) {
          const p = pages[0]!;
          out.push({
            rule: 'R-OCR-1',
            verdict: 'DISAGREE',
            confidence: 0.9,
            argument: `Значение извлечено из текстового слоя PDF без OCR (${p.file_id}, стр. ${p.pdf_page_number}); ошибка распознавания исключена. Проверьте привязку или извлечение.`,
          });
        }
      }
      break;
    }
    case 'LINKING_ERROR': {
      const localized = contested(f).every((e) => (e.geometry?.boxes?.length ?? 0) + (e.geometry?.polygons?.length ?? 0) > 0);
      if (f.locationType === 'ROOM' && localized && f.groupLocations.includes(f.location)) {
        out.push({
          rule: 'R-LNK-1',
          verdict: 'UNCERTAIN',
          confidence: 0.6,
          argument: `Привязка локализована рамкой на листе, помещение ${f.location} указано в группе доказательств.`,
        });
      }
      break;
    }
    case 'DUPLICATE': {
      const d = input.duplicate;
      if (d && d.location !== f.location) {
        out.push({
          rule: 'R-DUP-1',
          verdict: 'DISAGREE',
          confidence: 0.9,
          argument: `Находки относятся к разным местоположениям (${f.location} и ${d.location}); атомарные проверки по помещениям не дублируют друг друга.`,
        });
      } else if (d && d.paramCode !== f.paramCode) {
        out.push({
          rule: 'R-DUP-2',
          verdict: 'UNCERTAIN',
          confidence: 0.6,
          argument: `Находки относятся к разным параметрам (${f.paramCode} и ${d.paramCode}); проверьте, не является ли это ограниченным хеджированием кода.`,
        });
      }
      break;
    }
    case 'NOT_APPLICABLE_PARAM': {
      if (f.criticalityLevel === 'CRITICAL_SUSPEND') {
        out.push({
          rule: 'R-NA-1',
          verdict: 'UNCERTAIN',
          confidence: 0.6,
          argument: 'Параметр отнесён к критическим («Критическое (приостановка работ)»); неприменимость проверяется куратором данных.',
        });
      }
      break;
    }
    default:
      break;
  }
  if ((input.reasonCode === 'EQUIVALENT_SOLUTION' || input.reasonCode === 'OTHER') && f.riskLevel === 'HIGH' && (f.confidence ?? 0) >= 0.95) {
    out.push({
      rule: 'R-HIGH-1',
      verdict: 'UNCERTAIN',
      confidence: 0.6,
      argument: `Высокая уверенность модели (${Math.round((f.confidence ?? 0) * 100)}%) при высоком уровне риска; запись помечена для куратора.`,
    });
  }
  return out;
}

/** Runs every rule; the first DISAGREE wins, else UNCERTAIN, else AGREE (05 §3.7 table). */
export function validateRejection(input: ValidatorInput): ValidatorResult {
  const found = hits(input);
  const pages = contested(input.finding);
  const disagree = found.find((h) => h.verdict === 'DISAGREE');
  if (disagree) {
    return { verdict: 'DISAGREE', confidence: disagree.confidence, ruleIds: [disagree.rule], argument: disagree.argument, evidence: pages };
  }
  const uncertain = found.filter((h) => h.verdict === 'UNCERTAIN');
  if (uncertain.length) {
    return {
      verdict: 'UNCERTAIN',
      confidence: Math.min(...uncertain.map((h) => h.confidence)),
      ruleIds: uncertain.map((h) => h.rule),
      argument: uncertain.map((h) => h.argument).join(' '),
      evidence: pages,
    };
  }
  return { verdict: 'AGREE', confidence: agreeConfidence(input.finding.confidence), ruleIds: [], argument: null, evidence: pages };
}
