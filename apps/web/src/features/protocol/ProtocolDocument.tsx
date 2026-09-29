/**
 * Приложение 2 on screen (93 §5.1–5.5): the seven sections verbatim — titles, column sets, order, emoji markers
 * and percent text exactly as the protocol contract carries them — then Приложения А (the five ТЗ §9.2 п.4
 * tables), Б (evidence cards) and В (input registry, versions, hashes) and the signature block.
 *
 * Cell text is printed as given (the builder, AG-04, renders it); the viewer only adds navigation: «[карточка
 * Б.n]» references and the rows of Разделы 4–6 open the evidence card.
 */
import { Fragment } from 'react';
import type {
  CardSource,
  CompletenessRow,
  EvidenceCard,
  NegativeRow,
  Protocol,
  ViolationRow,
} from '../../contracts/protocol';
import { splitCardRef } from '../../contracts/protocol';
import { enumLabel } from '../../contracts/enums';
import { completenessBasisLabel, withoutScenarioCode } from '../../contracts/labels';
import { formatDateTime, formatInt, withoutInternalCodes } from '../../format';
import { placeLocations, titlePlace } from '../evidence/cardText';
import './protocol.css';

export interface ProtocolDocumentProps {
  protocol: Protocol;
  /** Card referenced in the URL (highlighted). */
  activeCard?: string | null;
  onOpenCard?: (cardNo: string) => void;
}

export const SECTION_IDS = {
  header: 'p2-header',
  s1: 'p2-s1',
  s2: 'p2-s2',
  s3: 'p2-s3',
  s4: 'p2-s4',
  s5: 'p2-s5',
  s6: 'p2-s6',
  s7: 'p2-s7',
  a: 'p2-app-a',
  b: 'p2-app-b',
  v: 'p2-app-v',
} as const;

const dash = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v));

function EmptyRow({ span, text = 'Отсутствуют' }: { span: number; text?: string }) {
  return (
    <tr className="p2-empty">
      <td colSpan={span}>{text}</td>
    </tr>
  );
}

function CardRefButton({ cardRef, onOpenCard }: { cardRef: string; onOpenCard?: (c: string) => void }) {
  return (
    <button
      type="button"
      className="p2-cardref"
      onClick={(e) => {
        e.stopPropagation();
        onOpenCard?.(cardRef);
      }}
      aria-label={`Открыть карточку ${cardRef}`}
    >
      [карточка {cardRef}]
    </button>
  );
}

/** «{short_name} ({code}), пом. 140, 142 [карточка Б.3]» with the reference as a link. */
function LabelWithCard({ label, onOpenCard }: { label: string; onOpenCard?: (c: string) => void }) {
  const { text, cardRef } = splitCardRef(label);
  return (
    <>
      {text}
      {cardRef && (
        <>
          {' '}
          <CardRefButton cardRef={cardRef} onOpenCard={onOpenCard} />
        </>
      )}
    </>
  );
}

function Decision({ status, text }: { status: string; text: string }) {
  return (
    <span className={`p2-dec-${status}`} data-code={status}>
      {text}
    </span>
  );
}

function HeaderBlock({ p }: { p: Protocol }) {
  const scenario = p.header.scenario_line ? withoutScenarioCode(p.header.scenario_line) : null;
  const [scenarioLabel, ...scenarioRest] = (scenario ?? '').split(': ');
  const line = (label: string, value: React.ReactNode) => (
    <div>
      <b>{label}</b> {value}
    </div>
  );
  return (
    <section id={SECTION_IDS.header} aria-label="Заголовок протокола">
      <h1>{p.header.title}</h1>
      <div className="p2-header">
        {line('Объект:', dash(p.object.name ?? p.object.object_id))}
        {line('Адрес:', dash(p.object.address))}
        {line('Номер надзорного дела:', dash(p.object.supervision_case_no))}
        {line('Застройщик:', dash(p.object.customer))}
        {line('Подрядчик:', dash(p.object.contractor))}
        {line('Дата формирования:', p.header.generated_at_ru)}
        {line('Версия протокола:', p.header.version_line)}
        {line(
          'Статус:',
          <>
            {p.header.status_line}
            {p.header.recheck_running ? ' · выполняется инкрементальная проверка' : ''}
          </>,
        )}
        {scenario && line(`${scenarioLabel}:`, scenarioRest.join(': '))}
      </div>
    </section>
  );
}

function Section1({ p }: { p: Protocol }) {
  const s = p.appendix2.section1_load_status;
  return (
    <section id={SECTION_IDS.s1}>
      <h2>РАЗДЕЛ 1. СТАТУС ЗАГРУЗКИ ДОКУМЕНТОВ</h2>
      <table className="p2-table">
        <thead>
          <tr>
            <th>Тип документа</th>
            <th>Статус</th>
            <th>Загружено файлов</th>
            <th>Ожидается</th>
            <th>Комментарий</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.length === 0 && <EmptyRow span={5} />}
          {s.rows.map((r) => (
            <tr key={r.stage}>
              <td>{r.stage_ru}</td>
              <td data-code={r.status}>{r.status_ru}</td>
              <td className="num">{r.files_loaded_text}</td>
              <td className="num">{r.files_expected === null || r.files_expected === undefined ? '—' : formatInt(r.files_expected)}</td>
              <td>{r.comment}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {s.scenario_line && <p className="p2-line">{withoutScenarioCode(s.scenario_line)}</p>}
    </section>
  );
}

function Section2({ p }: { p: Protocol }) {
  const s = p.appendix2.section2_summary;
  return (
    <section id={SECTION_IDS.s2}>
      <h2>РАЗДЕЛ 2. СВОДНАЯ СТАТИСТИКА (С ПРОЦЕНТАМИ)</h2>
      <table className="p2-table">
        <thead>
          <tr>
            <th>Показатель</th>
            <th className="num">Количество</th>
            <th className="num">% от общего</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.map((r) => (
            <tr key={r.key} data-code={r.key}>
              <td>{r.label_ru.startsWith('─') ? <span className="p2-indent">{r.label_ru}</span> : r.label_ru}</td>
              <td className="num">{formatInt(r.count)}</td>
              <td className="num">{r.percent_text}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(s.footnotes ?? []).map((f, i) => (
        <p key={i} className="p2-footnote">
          {'*'.repeat(i + 1)} {f}
        </p>
      ))}
    </section>
  );
}

function Section3({ p }: { p: Protocol }) {
  const s = p.appendix2.section3_not_checked_no_id;
  return (
    <section id={SECTION_IDS.s3}>
      <h2>РАЗДЕЛ 3. ПАРАМЕТРЫ, НЕ ПРОВЕРЕННЫЕ ИЗ-ЗА ОТСУТСТВИЯ ИД — {s.count}</h2>
      <table className="p2-table">
        <thead>
          <tr>
            <th className="num">№</th>
            <th>Код</th>
            <th>Раздел</th>
            <th>Параметр</th>
            <th>Отсутствующий файл</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.length === 0 && <EmptyRow span={5} />}
          {s.rows.map((r) => (
            <tr key={r.no}>
              <td className="num">{r.no}</td>
              <td style={{ whiteSpace: 'nowrap' }}>{r.parameter_code}</td>
              <td>{r.section_ru}</td>
              <td>{r.parameter_name}</td>
              <td>{r.missing_document}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {s.rows.length < s.count && (
        <p className="p2-footnote">
          Показано {s.rows.length} из {s.count}; полный перечень — в Приложении А.1.
        </p>
      )}
    </section>
  );
}

function ViolationTable({
  rows,
  activeCard,
  onOpenCard,
}: {
  rows: ViolationRow[];
  activeCard?: string | null;
  onOpenCard?: (c: string) => void;
}) {
  return (
    <table className="p2-table">
      <thead>
        <tr>
          <th className="num">№</th>
          <th>Раздел</th>
          <th>Параметр (код)</th>
          <th>ПД</th>
          <th>РД</th>
          <th>ИД</th>
          <th>Отклонение</th>
          <th>Решение инспектора</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && <EmptyRow span={8} text="Не выявлено" />}
        {rows.map((r) => (
          <tr
            key={`${r.no}-${r.card_ref}`}
            className={`p2-clickable${activeCard === r.card_ref ? ' p2-active' : ''}`}
            onClick={() => onOpenCard?.(r.card_ref)}
            data-card={r.card_ref}
          >
            <td className="num">{r.no}</td>
            <td>{r.section_ru}</td>
            <td>
              <LabelWithCard label={r.parameter_label} onOpenCard={onOpenCard} />
            </td>
            <td>{r.pd}</td>
            <td>{r.rd}</td>
            <td>{r.id}</td>
            <td data-code={r.deviation.direction ?? undefined}>{r.deviation.text}</td>
            <td>
              <Decision status={r.inspector_status} text={r.inspector_decision_ru} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Section4And5({ p, activeCard, onOpenCard }: ProtocolDocumentProps & { p: Protocol }) {
  const s4 = p.appendix2.section4_critical;
  const s5 = p.appendix2.section5_substantial;
  return (
    <>
      <section id={SECTION_IDS.s4}>
        <h2>РАЗДЕЛ 4. КРИТИЧЕСКИЕ НАРУШЕНИЯ — {s4.count}</h2>
        <ViolationTable rows={s4.rows} activeCard={activeCard} onOpenCard={onOpenCard} />
      </section>
      <section id={SECTION_IDS.s5}>
        <h2>РАЗДЕЛ 5. СУЩЕСТВЕННЫЕ НАРУШЕНИЯ — {s5.count}</h2>
        <ViolationTable rows={s5.rows} activeCard={activeCard} onOpenCard={onOpenCard} />
      </section>
    </>
  );
}

function Section6({ p, activeCard, onOpenCard }: ProtocolDocumentProps & { p: Protocol }) {
  const s = p.appendix2.section6_ai_suspicions;
  return (
    <section id={SECTION_IDS.s6}>
      <h2>РАЗДЕЛ 6. ПОДОЗРЕНИЯ ИИ — {s.count}</h2>
      <table className="p2-table">
        <thead>
          <tr>
            <th className="num">№</th>
            <th>Метод</th>
            <th>Описание</th>
            <th>ПД</th>
            <th>РД</th>
            <th>ИД</th>
            <th>Решение инспектора</th>
            <th>Причина отклонения</th>
            <th>Комментарий ИИ</th>
          </tr>
        </thead>
        <tbody>
          {s.rows.length === 0 && <EmptyRow span={9} text="Не выявлено" />}
          {s.rows.map((r) => (
            <tr
              key={`${r.no}-${r.card_ref}`}
              className={`p2-clickable${activeCard === r.card_ref ? ' p2-active' : ''}`}
              onClick={() => onOpenCard?.(r.card_ref)}
              data-card={r.card_ref}
            >
              <td className="num">{r.no}</td>
              <td data-code={r.method}>{r.method_ru}</td>
              <td>
                {r.description} <CardRefButton cardRef={r.card_ref} onOpenCard={onOpenCard} />
              </td>
              <td>{r.pd}</td>
              <td>{r.rd}</td>
              <td>{r.id}</td>
              <td>
                <Decision status={r.inspector_status} text={r.inspector_decision_ru} />
              </td>
              <td>{r.rejection_reason}</td>
              <td>{r.ai_comment}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Section7({ p }: { p: Protocol }) {
  const s = p.appendix2.section7_resolution;
  return (
    <section id={SECTION_IDS.s7}>
      <h2>РАЗДЕЛ 7. РЕЗОЛЮТИВНАЯ ЧАСТЬ</h2>
      <h3>7.1. По критическим нарушениям</h3>
      <table className="p2-table">
        <thead>
          <tr>
            <th className="num">№</th>
            <th>Вид работ</th>
            <th>Конкретная рекомендация</th>
          </tr>
        </thead>
        <tbody>
          {s.critical.length === 0 && <EmptyRow span={3} text="Не требуется" />}
          {s.critical.map((r) => (
            <tr key={r.no} data-draft={r.is_draft ? 'true' : undefined}>
              <td className="num">{r.no}</td>
              <td>{r.work_type}</td>
              <td>{r.recommendation}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>7.2. По существенным нарушениям</h3>
      <table className="p2-table">
        <thead>
          <tr>
            <th className="num">№</th>
            <th>Вид нарушения</th>
            <th>Конкретная рекомендация</th>
          </tr>
        </thead>
        <tbody>
          {s.substantial.length === 0 && <EmptyRow span={3} text="Не требуется" />}
          {s.substantial.map((r) => (
            <tr key={r.no} data-draft={r.is_draft ? 'true' : undefined}>
              <td className="num">{r.no}</td>
              <td>{r.violation_kind}</td>
              <td>{r.recommendation}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(p.appendix2.footnotes ?? []).map((f, i) => (
        <p key={i} className="p2-footnote">
          {f}
        </p>
      ))}
    </section>
  );
}

const statusRu = (status: string) => enumLabel('InspectorStatus', status);

function completenessRow(r: CompletenessRow, i: number) {
  return (
    <tr key={`${r.parameter_code}-${i}`}>
      <td style={{ whiteSpace: 'nowrap' }}>{r.parameter_code}</td>
      <td>{dash(r.section_ru)}</td>
      <td>{r.parameter_name}</td>
      <td data-code={r.protocol_status}>{enumLabel('ProtocolParamStatus', r.protocol_status)}</td>
      <td data-code={r.completeness_status}>
        {r.completeness_status ? enumLabel('CompletenessStatus', r.completeness_status) : '—'}
        {r.completeness_basis ? (
          <div className="p2-basis" data-code={r.completeness_basis}>
            {completenessBasisLabel(r.completeness_basis)}
          </div>
        ) : null}
      </td>
      <td>{r.missing_stage ? enumLabel('DocStage', r.missing_stage) : '—'}</td>
      <td>{dash(r.document)}</td>
      <td>{dash(r.reason_ru)}</td>
      <td>{dash(r.action_ru)}</td>
    </tr>
  );
}

function negativeRow(r: NegativeRow, i: number, onOpenCard?: (c: string) => void) {
  return (
    <tr key={`${r.parameter_code}-${i}`}>
      <td>{r.card_ref ? <CardRefButton cardRef={r.card_ref} onOpenCard={onOpenCard} /> : '—'}</td>
      <td>
        {r.parameter_label}
        {r.locations?.length ? titlePlace(r.locations) : ''}
      </td>
      <td data-code={r.decided_by}>{r.decided_by === 'INSPECTOR' ? 'Инспектор' : 'Система'}</td>
      <td>
        {dash(r.reason_ru)}
        {r.reason_code ? <div className="p2-mono">{r.reason_code}</div> : null}
      </td>
      <td>{dash(r.comment)}</td>
      <td>{dash(r.ai_comment)}</td>
      <td>{r.decided_at ? formatDateTime(r.decided_at) : '—'}</td>
    </tr>
  );
}

function AppendixA({ p, onOpenCard }: ProtocolDocumentProps & { p: Protocol }) {
  const t = p.tz92_tables;
  const banner = t.banner_ru ?? 'Не являются нарушениями до решения инспектора';
  const candidateTable = (rows: NonNullable<typeof t.a2_candidates>, empty: string) => (
    <table className="p2-table">
      <thead>
        <tr>
          <th>Карточка</th>
          <th>Параметр</th>
          <th>Помещения / место</th>
          <th>Ожидаемое (эталон)</th>
          <th>Фактическое</th>
          <th>Отклонение</th>
          <th>Уровень риска</th>
          <th>Решение инспектора</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && <EmptyRow span={8} text={empty} />}
        {rows.map((r) => (
          <tr key={r.card_ref} className="p2-clickable" onClick={() => onOpenCard?.(r.card_ref)}>
            <td>
              <CardRefButton cardRef={r.card_ref} onOpenCard={onOpenCard} />
            </td>
            <td>{r.parameter_label}</td>
            <td>{r.locations?.length ? (placeLocations(r.locations).length ? placeLocations(r.locations).join(', ') : 'объект в целом') : '—'}</td>
            <td>{dash(r.expected)}</td>
            <td>{dash(r.actual)}</td>
            <td>{dash(r.deviation_text)}</td>
            <td data-code={r.risk_level}>{r.risk_level ? enumLabel('RiskLevel', r.risk_level) : '—'}</td>
            <td>
              <Decision status={r.inspector_status} text={statusRu(r.inspector_status)} />
              {r.comment ? <div className="p2-footnote">{r.comment}</div> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <section id={SECTION_IDS.a}>
      <h2>ПРИЛОЖЕНИЕ А. РАЗДЕЛЬНЫЕ ТАБЛИЦЫ (п. 9.2 ТЗ)</h2>
      <h3>А.1. Комплектность и сопоставимость</h3>
      <table className="p2-table">
        <thead>
          <tr>
            <th>Код</th>
            <th>Раздел</th>
            <th>Параметр</th>
            <th>Статус</th>
            <th>Комплектность / основание</th>
            <th>Нет стадии</th>
            <th>Документ</th>
            <th>Причина</th>
            <th>Действие</th>
          </tr>
        </thead>
        <tbody>
          {(t.a1_completeness ?? []).length === 0 && <EmptyRow span={9} text="Все параметры комплектны" />}
          {(t.a1_completeness ?? []).map(completenessRow)}
        </tbody>
      </table>
      <h3>А.2. Предварительные кандидаты</h3>
      <div className="p2-banner">{banner}</div>
      {candidateTable(t.a2_candidates ?? [], 'Кандидатов нет')}
      <h3>А.3. Подтверждённые инспектором нарушения</h3>
      {candidateTable(t.a3_confirmed ?? [], 'Подтверждённых нарушений нет')}
      <h3>А.4. Проверенные отрицательные результаты</h3>
      <table className="p2-table">
        <thead>
          <tr>
            <th>Карточка</th>
            <th>Параметр</th>
            <th>Решение принято</th>
            <th>Причина</th>
            <th>Комментарий</th>
            <th>Комментарий ИИ</th>
            <th>Дата</th>
          </tr>
        </thead>
        <tbody>
          {(t.a4_negative_verified ?? []).length === 0 && <EmptyRow span={7} text="Нет" />}
          {(t.a4_negative_verified ?? []).map((r, i) => negativeRow(r, i, onOpenCard))}
        </tbody>
      </table>
      <h3>А.5. Гипотезы свободного поиска</h3>
      <div className="p2-banner">{banner}</div>
      <table className="p2-table">
        <thead>
          <tr>
            <th>Карточка</th>
            <th>Код</th>
            <th>Метод</th>
            <th>Описание</th>
            <th className="num">Уверенность</th>
            <th>Нормативная база</th>
            <th>Привязка доказательств</th>
            <th>Решение инспектора</th>
          </tr>
        </thead>
        <tbody>
          {(t.a5_hypotheses ?? []).length === 0 && <EmptyRow span={8} text="Гипотез нет" />}
          {(t.a5_hypotheses ?? []).map((r) => (
            <tr key={r.card_ref} className="p2-clickable" onClick={() => onOpenCard?.(r.card_ref)}>
              <td>
                <CardRefButton cardRef={r.card_ref} onOpenCard={onOpenCard} />
              </td>
              <td style={{ whiteSpace: 'nowrap' }}>{dash(r.parameter_code)}</td>
              <td data-code={r.method}>{enumLabel('DiscoveryMethod', r.method)}</td>
              <td>{r.description}</td>
              <td className="num">{r.confidence === undefined ? '—' : `${Math.round(r.confidence * 100)}%`}</td>
              <td>{dash(r.normative_base)}</td>
              <td data-code={r.evidence_bind_status ?? undefined}>
                {r.evidence_bind_status === 'BOUND' ? 'Привязаны' : r.evidence_bind_status === 'PARTIAL' ? 'Частично' : r.evidence_bind_status === 'UNBOUND' ? 'Не привязаны' : '—'}
              </td>
              <td>
                <Decision status={r.inspector_status} text={enumLabel('SuspicionInspectorStatus', r.inspector_status)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** Page thumbnail: where the region sits on the sheet (aspect of the sheet is unknown → square frame). */
export function MiniMap({ source, size = 64 }: { source: CardSource; size?: number }) {
  const boxes = source.geometry?.boxes ?? [];
  const color = source.stage === 'PD' ? '#1D4ED8' : '#C62828';
  return (
    <svg className="p2-minimap" width={size} height={size} viewBox="0 0 100 100" role="img" aria-label={`Область на странице ${source.pdf_page_number}`}>
      <rect x="1" y="1" width="98" height="98" fill="#fff" stroke="#9aa0a6" strokeWidth="1.5" />
      {boxes.length === 0 ? (
        <rect x="4" y="4" width="92" height="92" fill="none" stroke={color} strokeWidth="2" strokeDasharray="4 3" />
      ) : (
        boxes.map((b, i) => (
          <rect
            key={i}
            x={b[0] * 100}
            y={b[1] * 100}
            width={Math.max(2, (b[2] - b[0]) * 100)}
            height={Math.max(2, (b[3] - b[1]) * 100)}
            fill={color}
            fillOpacity="0.25"
            stroke={color}
            strokeWidth="2"
          />
        ))
      )}
    </svg>
  );
}

export function sourceRoleLabel(s: CardSource): string {
  if (s.role) return enumLabel('EvidenceRole', s.role);
  return s.stage === 'PD' ? 'Эталон (ожидаемое значение)' : 'Факт (фактическое значение)';
}

export function bboxText(s: CardSource): string {
  const boxes = s.geometry?.boxes ?? [];
  if (boxes.length === 0) return 'вся страница';
  return boxes.map((b) => `[${b.map((v) => v.toFixed(3).replace('.', ',')).join('; ')}]`).join(' ');
}

export function CardBlock({ card, active, onOpenCard }: { card: EvidenceCard; active?: boolean; onOpenCard?: (c: string) => void }) {
  const decisionReason = card.inspector.reason_code ?? card.inspector.basis_code ?? card.inspector.clarify_code ?? null;
  return (
    <article id={`card-${card.card_no}`} className={`p2-card${active ? ' p2-active' : ''}`} aria-label={`Карточка ${card.card_no}`}>
      <div className="p2-card-head">
        <strong>
          Карточка {card.card_no}. {card.parameter_label}
          {titlePlace(card.locations)}
        </strong>
        {onOpenCard && (
          <button type="button" className="p2-cardref" onClick={() => onOpenCard(card.card_no)}>
            Открыть доказательства
          </button>
        )}
      </div>
      <dl className="p2-kv">
        {card.finding_ids?.length ? (
          <>
            <dt>ID находки</dt>
            <dd className="p2-mono">{card.finding_ids.join(', ')}</dd>
          </>
        ) : null}
        <dt>Код параметра / правило</dt>
        <dd>
          {card.parameter_code}
          {card.rule_version ? ` · ${card.rule_version}` : ''}
        </dd>
        <dt>Ожидаемое значение (эталон)</dt>
        <dd>{dash(card.expected_value)}</dd>
        <dt>Фактическое значение</dt>
        <dd>{dash(card.actual_value)}</dd>
        <dt>Обоснование</dt>
        <dd>{dash(card.rationale)}</dd>
        <dt>Уровень риска</dt>
        <dd>
          {card.risk_level ? enumLabel('RiskLevel', card.risk_level) : '—'}
          <span className="p2-footnote"> — очерёдность экспертной проверки, не статус нарушения</span>
        </dd>
        <dt>Критичность</dt>
        <dd>{dash(card.criticality)}</dd>
        <dt>Согласованное изменение</dt>
        <dd>{card.approved_change_ref === 'NONE' ? 'не найдено' : dash(card.approved_change_ref)}</dd>
        <dt>Решение инспектора</dt>
        <dd>
          <Decision status={card.inspector.status} text={statusRu(card.inspector.status)} />
          {card.inspector.decided_at ? ` · ${formatDateTime(card.inspector.decided_at)}` : ''}
        </dd>
        <dt>Причина решения</dt>
        <dd>
          {decisionReason ? <span className="p2-mono">{decisionReason}</span> : '—'}
          {card.inspector.comment ? ` · ${card.inspector.comment}` : ''}
        </dd>
        {card.ai_comment ? (
          <>
            <dt>Комментарий ИИ</dt>
            <dd>{card.ai_comment}</dd>
          </>
        ) : null}
      </dl>
      <table className="p2-table">
        <thead>
          <tr>
            <th>Роль</th>
            <th>Стадия</th>
            <th>file_id / файл</th>
            <th>SHA-256</th>
            <th>Шифр</th>
            <th>Ред.</th>
            <th>Статус утверждения</th>
            <th>Лист / стр.</th>
            <th>bbox (норм.)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {card.sources.map((s, i) => (
            <tr key={i}>
              <td data-code={s.role}>{sourceRoleLabel(s)}</td>
              <td>{enumLabel('DocStage', s.stage)}</td>
              <td>
                <span className="p2-mono">{s.file_id}</span>
                {s.file_name ? <div className="p2-footnote">{s.file_name}</div> : null}
              </td>
              <td className="p2-mono" title={s.file_sha256 ?? undefined}>
                {s.file_sha256 ? `${s.file_sha256.slice(0, 8)}…${s.file_sha256.slice(-4)}` : '—'}
              </td>
              <td>{dash(s.document_code)}</td>
              <td>{dash(s.revision)}</td>
              <td>{s.approval_status ? enumLabel('ApprovalStatus', s.approval_status) : '—'}</td>
              <td style={{ whiteSpace: 'nowrap' }}>
                л. {dash(s.sheet_number)} / стр. {s.pdf_page_number}
              </td>
              <td className="p2-mono">{bboxText(s)}</td>
              <td>
                <MiniMap source={s} size={44} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}

function AppendixB({ p, activeCard, onOpenCard }: ProtocolDocumentProps & { p: Protocol }) {
  return (
    <section id={SECTION_IDS.b}>
      <h2>ПРИЛОЖЕНИЕ Б. КАРТОЧКИ ДОКАЗАТЕЛЬСТВ</h2>
      {p.evidence_cards.length === 0 && <p className="p2-footnote">Карточек нет.</p>}
      {p.evidence_cards.map((c) => (
        <CardBlock key={c.card_no} card={c} active={activeCard === c.card_no} onOpenCard={onOpenCard} />
      ))}
    </section>
  );
}

function AppendixV({ p }: { p: Protocol }) {
  const v = p.versions;
  return (
    <section id={SECTION_IDS.v}>
      <h2>ПРИЛОЖЕНИЕ В. РЕЕСТР ВХОДНЫХ ФАЙЛОВ И ВЕРСИИ</h2>
      <table className="p2-table">
        <thead>
          <tr>
            <th>file_id</th>
            <th>Файл</th>
            <th>Стадия</th>
            <th>Раздел</th>
            <th>Шифр</th>
            <th>Ред.</th>
            <th>Статус утверждения</th>
            <th className="num">Страниц</th>
            <th>SHA-256</th>
            <th>Использован</th>
          </tr>
        </thead>
        <tbody>
          {p.input_registry.files.length === 0 && <EmptyRow span={10} />}
          {p.input_registry.files.map((f) => (
            <tr key={f.file_id}>
              <td className="p2-mono">{f.file_id}</td>
              <td>{dash(f.file_name)}</td>
              <td>{f.stage ? enumLabel('DocStage', f.stage) : '—'}</td>
              <td>{f.section ? enumLabel('ManifestSection', f.section) : '—'}</td>
              <td>{dash(f.document_code)}</td>
              <td>{dash(f.revision)}</td>
              <td>{f.approval_status ? enumLabel('ApprovalStatus', f.approval_status) : '—'}</td>
              <td className="num">{formatInt(f.pages ?? null)}</td>
              <td className="p2-mono p2-hash" title={f.sha256}>
                {f.sha256}
              </td>
              <td>{f.used ? 'да' : `нет — ${dash(withoutInternalCodes(f.exclusion_reason))}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="p2-kv" style={{ marginTop: 10 }}>
        <dt>Версия конвейера</dt>
        <dd className="p2-mono">{v.pipeline_version}</dd>
        <dt>Версия матрицы</dt>
        <dd className="p2-mono">{dash(v.matrix_version)}</dd>
        <dt>Версия набора данных / модели</dt>
        <dd className="p2-mono">
          {dash(v.dataset_version)} / {dash(v.model_version)}
        </dd>
        <dt>Версия контрактов / кода</dt>
        <dd className="p2-mono">
          {dash(v.contract_version)} / {dash(v.code_version)}
        </dd>
        {Object.entries(p.input_registry.parser_versions ?? {}).map(([k, val]) => (
          <Fragment key={k}>
            <dt>Парсер {k}</dt>
            <dd className="p2-mono">{val}</dd>
          </Fragment>
        ))}
        <dt>input_manifest_hash</dt>
        <dd className="p2-mono p2-hash">{p.input_manifest_hash}</dd>
        <dt>content_sha256</dt>
        <dd className="p2-mono p2-hash">{dash(p.content_sha256)}</dd>
      </dl>
    </section>
  );
}

function SignatureBlock({ p }: { p: Protocol }) {
  const s = p.signature;
  return (
    <section aria-label="Подпись">
      <div className="p2-signature">
        <div>
          <div>Инспектор: {dash(s?.inspector_name)}</div>
          <div className="p2-footnote">{dash(s?.inspector_position)}</div>
          <div className="p2-sign-line" />
          <div className="p2-footnote">(подпись)</div>
        </div>
        <div>
          <div>Дата подписания: {s?.signed_at ? formatDateTime(s.signed_at) : '—'}</div>
          {p.is_final ? (
            <div>
              🔒 Протокол финализирован {s?.finalized_at ? formatDateTime(s.finalized_at) : ''}
              {s?.content_sha256 ? <div className="p2-mono">SHA-256: {s.content_sha256}</div> : null}
            </div>
          ) : (
            <div className="p2-footnote">Протокол не финализирован: данные предварительные.</div>
          )}
        </div>
      </div>
    </section>
  );
}

export function ProtocolDocument({ protocol, activeCard, onOpenCard }: ProtocolDocumentProps) {
  const p = protocol;
  return (
    <div className="p2-sheet" data-testid="protocol-sheet">
      <HeaderBlock p={p} />
      <Section1 p={p} />
      <Section2 p={p} />
      <Section3 p={p} />
      <Section4And5 p={p} protocol={p} activeCard={activeCard} onOpenCard={onOpenCard} />
      <Section6 p={p} protocol={p} activeCard={activeCard} onOpenCard={onOpenCard} />
      <Section7 p={p} />
      <AppendixA p={p} protocol={p} onOpenCard={onOpenCard} />
      <AppendixB p={p} protocol={p} activeCard={activeCard} onOpenCard={onOpenCard} />
      <AppendixV p={p} />
      <SignatureBlock p={p} />
    </div>
  );
}

export const TOC: Array<{ id: string; label: (p: Protocol) => string }> = [
  { id: SECTION_IDS.header, label: () => 'Заголовок' },
  { id: SECTION_IDS.s1, label: () => '1. Статус загрузки' },
  { id: SECTION_IDS.s2, label: () => '2. Сводная статистика' },
  { id: SECTION_IDS.s3, label: (p) => `3. Нет ИД — ${p.appendix2.section3_not_checked_no_id.count}` },
  { id: SECTION_IDS.s4, label: (p) => `4. Критические — ${p.appendix2.section4_critical.count}` },
  { id: SECTION_IDS.s5, label: (p) => `5. Существенные — ${p.appendix2.section5_substantial.count}` },
  { id: SECTION_IDS.s6, label: (p) => `6. Подозрения ИИ — ${p.appendix2.section6_ai_suspicions.count}` },
  { id: SECTION_IDS.s7, label: () => '7. Резолютивная часть' },
  { id: SECTION_IDS.a, label: () => 'Приложение А' },
  { id: SECTION_IDS.b, label: (p) => `Приложение Б — ${p.evidence_cards.length}` },
  { id: SECTION_IDS.v, label: () => 'Приложение В' },
];
