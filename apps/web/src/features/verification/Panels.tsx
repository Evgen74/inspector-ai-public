/**
 * Completeness shown apart from the candidates (ТЗ §9.3 п.1, §7 row 2; VER-07): «Статус загрузки документов»,
 * «Тип проверки», parameters not checked for want of ИД, table А.1 and imported rows that need no decision.
 * And the usability report of the protocol (ТЗ §9.3 «Критерии юзабилити»: ≤ 30 min, ≤ 3 clicks per violation).
 */
import { Alert, Descriptions, Empty, Flex, Progress, Skeleton, Statistic, Table, Tag, Typography } from 'antd';
import { ProblemAlert } from '../../components/ProblemAlert';
import { enumLabel } from '../../contracts/enums';
import { useCompleteness, useUsability } from './api';
import { formatElapsed } from './telemetry';

export function CompletenessPanel({ pid }: { pid: string }) {
  const q = useCompleteness(pid);
  if (q.isPending) return <Skeleton active />;
  if (q.error) return <ProblemAlert error={q.error} />;
  const c = q.data;
  return (
    <Flex vertical gap={12} data-testid="completeness-panel">
      <Alert type="info" showIcon title={c.scenario_line ?? `Тип проверки: ${c.scenario ?? '—'}`} description={c.note} />
      <Table
        size="small"
        pagination={false}
        rowKey="stage"
        dataSource={c.load_status_rows}
        title={() => <Typography.Text strong>Статус загрузки документов</Typography.Text>}
        columns={[
          { title: 'Тип документа', dataIndex: 'stage_ru' },
          { title: 'Статус', dataIndex: 'status_ru' },
          { title: 'Загружено файлов', dataIndex: 'files_loaded_text' },
          { title: 'Ожидается', dataIndex: 'files_expected', render: (v: number | null | undefined) => v ?? '—' },
          { title: 'Комментарий', dataIndex: 'comment' },
        ]}
      />
      <Table
        size="small"
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        rowKey={(r) => `${r.parameter_code}-${r.protocol_status}`}
        dataSource={c.completeness_rows}
        title={() => <Typography.Text strong>Комплектность и сопоставимость (Приложение А.1)</Typography.Text>}
        locale={{ emptyText: <Empty description="Нет строк комплектности" /> }}
        columns={[
          { title: 'Параметр', key: 'p', render: (_, r) => `${r.parameter_name} (${r.parameter_code})` },
          { title: 'Статус', key: 's', render: (_, r) => <Tag>{enumLabel('ProtocolParamStatus', r.protocol_status)}</Tag> },
          { title: 'Документ', dataIndex: 'document', render: (v: string | null) => v ?? '—' },
          { title: 'Причина', dataIndex: 'reason_ru', render: (v: string | null) => v ?? '—' },
          { title: 'Действие', dataIndex: 'action_ru', render: (v: string | null) => v ?? '—' },
        ]}
      />
      <Typography.Text type="secondary">
        Не проверено из-за отсутствия ИД: {c.not_checked_no_id.count}. Строк без решения инспектора: {c.non_reviewable.length}.
      </Typography.Text>
    </Flex>
  );
}

export function UsabilityPanel({ pid }: { pid: string }) {
  const q = useUsability(pid);
  if (q.isPending) return <Skeleton active />;
  if (q.error) return <ProblemAlert error={q.error} />;
  const r = q.data;
  const minutes = r.protocol_time_ms !== null ? r.protocol_time_ms / 60_000 : null;
  return (
    <Flex vertical gap={12} data-testid="usability-panel">
      <Flex gap={32} wrap>
        <Statistic title="Время на протокол" value={r.protocol_time_ms !== null ? formatElapsed(r.protocol_time_ms) : '—'} suffix={`/ ${r.targets.protocol_minutes}:00`} />
        <Statistic title="Кликов на решение (медиана / макс.)" value={`${r.clicks.median ?? '—'} / ${r.clicks.max ?? '—'}`} suffix={`≤ ${r.targets.clicks_per_decision}`} />
        <Statistic title="Доля решений ≤ 3 кликов" value={r.clicks.share_within_target !== null ? Math.round(r.clicks.share_within_target * 100) : '—'} suffix="%" />
        <Statistic title="Только клавиатурой" value={r.keyboard_only_share !== null ? Math.round(r.keyboard_only_share * 100) : '—'} suffix="%" />
      </Flex>
      {minutes !== null && (
        <Progress percent={Math.min(100, Math.round((minutes / r.targets.protocol_minutes) * 100))} status={r.met.protocol_time === false ? 'exception' : 'normal'} format={() => `${minutes.toFixed(1)} мин`} />
      )}
      <Descriptions
        size="small"
        column={2}
        items={[
          { key: 'n', label: 'Решений (с замером)', children: `${r.decisions} (${r.measured_decisions})` },
          { key: 'card', label: 'Время на карточку (медиана / p90)', children: `${r.time_on_card_ms.median !== null ? formatElapsed(r.time_on_card_ms.median) : '—'} / ${r.time_on_card_ms.p90 !== null ? formatElapsed(r.time_on_card_ms.p90) : '—'}` },
          { key: 'keys', label: 'Клавиш на решение (медиана)', children: r.keys.median ?? '—' },
          { key: 'insp', label: 'Инспекторов', children: r.inspectors },
        ]}
      />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Цели п. 9.3 ТЗ: полный цикл ≤ {r.targets.protocol_minutes} мин, ≤ {r.targets.clicks_per_decision} кликов на нарушение.
        {r.met.clicks === false || r.met.protocol_time === false ? ' Есть превышения — см. карточки с наибольшим числом кликов.' : ''}
      </Typography.Text>
    </Flex>
  );
}
