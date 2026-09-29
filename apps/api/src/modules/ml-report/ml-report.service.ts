/** Weekly retraining report (ТЗ §7 module 10): decisions of inspectors, never of the hidden-test object. */
import { Inject, Injectable } from '@nestjs/common';
import { validationProblem } from '../shared/tz-validation';
import { APP_CONFIG, type AppConfig } from '../../config/config';
import { loadEnums } from '../../contracts/contracts';
import { Database } from '../../db/database';
import { loadCatalog } from '../normative/params-catalog';
import { buildReport, type DecisionRow, type ParamInfo, type ReasonInfo, renderHtml } from './report';

export abstract class MlReportSource {
  abstract decisions(from: Date, to: Date): Promise<DecisionRow[]>;
  abstract disputes(from: Date, to: Date): Promise<number>;
}

@Injectable()
export class PgMlReportSource extends MlReportSource {
  constructor(private readonly database: Database) {
    super();
  }

  /** Latest decision per finding inside the window; reverts and hidden-test objects are excluded. */
  async decisions(from: Date, to: Date): Promise<DecisionRow[]> {
    const r = await this.database.pool.query(
      `SELECT * FROM (
         SELECT DISTINCT ON (d.check_id) d.created_at, d.decision, d.reason_code, c.param_code
         FROM verification_decisions d
         JOIN checks c ON c.id = d.check_id
         JOIN objects o ON o.id = d.object_id
         WHERE d.created_at >= $1 AND d.created_at < $2 AND COALESCE(o.split, '') <> 'TEST_HIDDEN'
         ORDER BY d.check_id, d.created_at DESC
       ) t`,
      [from, to],
    );
    return r.rows.map((x) => ({ at: x.created_at as Date, decision: x.decision as string, reason_code: (x.reason_code as string | null) ?? null, param_code: x.param_code as string }));
  }

  async disputes(from: Date, to: Date): Promise<number> {
    const r = await this.database.pool.query(
      `SELECT count(*)::int AS n FROM dispute_log l JOIN objects o ON o.id = (SELECT object_id FROM processes WHERE id = l.process_id)
       WHERE l.created_at >= $1 AND l.created_at < $2 AND COALESCE(o.split, '') <> 'TEST_HIDDEN'`,
      [from, to],
    );
    return (r.rows[0]?.n as number | undefined) ?? 0;
  }
}

export class InMemoryMlReportSource extends MlReportSource {
  constructor(
    public rows: DecisionRow[] = [],
    public disputeCount = 0,
  ) {
    super();
  }
  async decisions(): Promise<DecisionRow[]> {
    return this.rows;
  }
  async disputes(): Promise<number> {
    return this.disputeCount;
  }
}

function parseDate(v: string | undefined, fallback: Date): Date {
  if (!v) return fallback;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) {
    throw validationProblem('INVALID_DATE', 'Некорректная дата', `Не удалось разобрать дату «${v}».`);
  }
  return d;
}

@Injectable()
export class MlReportService {
  private lookups: { params: Map<string, ParamInfo>; reasons: Map<string, ReasonInfo> } | null = null;

  constructor(
    @Inject(APP_CONFIG) private readonly config: AppConfig,
    private readonly source: MlReportSource,
  ) {}

  private get maps() {
    if (!this.lookups) {
      const params = new Map(loadCatalog(this.config.contractsDir).params.map((p) => [p.code, { name: p.name, section: p.section }]));
      const def = loadEnums(this.config.contractsDir).DecisionRejectReason;
      const reasons = new Map((def?.values ?? []).map((v) => [v.code, { label: v.label_ru ?? v.code, family: typeof v.family === 'string' ? v.family : null }]));
      this.lookups = { params, reasons };
    }
    return this.lookups;
  }

  async weekly(fromStr?: string, toStr?: string, now: Date = new Date()): Promise<Record<string, unknown>> {
    const to = parseDate(toStr, now);
    const from = parseDate(fromStr, new Date(to.getTime() - 7 * 86_400_000));
    if (from >= to) throw validationProblem('INVALID_PERIOD', 'Некорректный период', 'Начало периода должно быть раньше конца.');
    const trendFrom = new Date(Math.min(from.getTime(), to.getTime() - 9 * 7 * 86_400_000));
    const [rows, disputes] = await Promise.all([this.source.decisions(trendFrom, to), this.source.disputes(from, to)]);
    return buildReport({ rows, from, to, params: this.maps.params, reasons: this.maps.reasons, disputes, now });
  }

  async weeklyHtml(fromStr?: string, toStr?: string): Promise<string> {
    return renderHtml(await this.weekly(fromStr, toStr));
  }
}
