/**
 * «Доказательства» of one evidence card (Приложение Б): side-by-side ПД/РД panes with the regions, the card
 * fields next to them, previous/next card. Deep link: /objects/:objectId/protocols/:runId/cards/:cardNo.
 */
import { useEffect, useMemo } from 'react';
import { Breadcrumb, Button, Card, Descriptions, Flex, Result, Skeleton, Space, Tag, Tooltip, Typography } from 'antd';
import { ArrowLeftOutlined, ArrowRightOutlined, FileTextOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { useProtocol } from '../../api/d1';
import { ProblemAlert } from '../../components/ProblemAlert';
import type { EvidenceCard, Protocol, ViolationRow } from '../../contracts/protocol';
import { enumLabel } from '../../contracts/enums';
import { EvidenceViewer } from './EvidenceViewer';
import { locationsText, placeLocations, stageValueText, titlePlace } from './cardText';

/** The protocol row (Разделы 4–6) that references the card: deviation text and the rendered decision. */
function rowOf(p: Protocol, cardNo: string): { deviation: string | null; decision: string | null; section: string } | null {
  const v = [...p.appendix2.section4_critical.rows, ...p.appendix2.section5_substantial.rows].find(
    (r: ViolationRow) => r.card_ref === cardNo,
  );
  if (v) {
    const section = p.appendix2.section4_critical.rows.includes(v) ? 'Раздел 4 · критическое' : 'Раздел 5 · существенное';
    return { deviation: v.deviation.text, decision: v.inspector_decision_ru, section };
  }
  const s = p.appendix2.section6_ai_suspicions.rows.find((r) => r.card_ref === cardNo);
  if (s) return { deviation: null, decision: s.inspector_decision_ru, section: `Раздел 6 · ${s.method_ru}` };
  return null;
}

/** «Помещения» for rooms; «Место» when the card is about the object as a whole. */
function placeLabel(locations: readonly string[]): string {
  return placeLocations(locations).length ? 'Помещения' : 'Место';
}

export function CardSummary({ card, protocol }: { card: EvidenceCard; protocol: Protocol }) {
  const row = rowOf(protocol, card.card_no);
  const suspicion = Boolean(card.stage_values) || row?.section.startsWith('Раздел 6') === true;
  const sv = card.stage_values ?? null;
  const findingIds = (card.finding_ids ?? []).join(', ');
  return (
    <Descriptions size="small" column={1} bordered styles={{ label: { width: 104, padding: '6px 8px', fontSize: 12.5 }, content: { padding: '6px 8px' } }}>
      <Descriptions.Item label="Параметр">
        {card.parameter_label}
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {card.parameter_code}
            {card.rule_version ? ` · правило ${card.rule_version}` : ''}
          </Typography.Text>
        </div>
      </Descriptions.Item>
      <Descriptions.Item label={placeLabel(card.locations)}>{locationsText(card.locations)}</Descriptions.Item>
      {row && <Descriptions.Item label="В протоколе">{row.section}</Descriptions.Item>}
      {suspicion ? (
        <>
          <Descriptions.Item label="Значения в ПД">
            <span data-testid="stage-pd">{stageValueText(sv?.PD)}</span>
          </Descriptions.Item>
          <Descriptions.Item label="Значения в РД">
            <span data-testid="stage-rd">{stageValueText(sv?.RD)}</span>
          </Descriptions.Item>
          {sv?.ID ? <Descriptions.Item label="Значения в ИД">{sv.ID}</Descriptions.Item> : null}
        </>
      ) : (
        <>
          <Descriptions.Item label="ПД (эталон)">{String(card.expected_value ?? '—')}</Descriptions.Item>
          <Descriptions.Item label="РД (факт)">{String(card.actual_value ?? '—')}</Descriptions.Item>
        </>
      )}
      {row?.deviation && <Descriptions.Item label="Отклонение">{row.deviation}</Descriptions.Item>}
      <Descriptions.Item label="Обоснование">{card.rationale ?? '—'}</Descriptions.Item>
      <Descriptions.Item label="Критичность">
        {card.criticality ?? '—'}
        {suspicion && (
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              критичность параметра по каталогу; это подозрение ИИ, а не нарушение
            </Typography.Text>
          </div>
        )}
      </Descriptions.Item>
      <Descriptions.Item label="Уровень риска">
        {card.risk_level ? enumLabel('RiskLevel', card.risk_level) : '—'}
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            очерёдность проверки, не статус нарушения
          </Typography.Text>
        </div>
      </Descriptions.Item>
      <Descriptions.Item label="Решение инспектора">
        <Tag data-code={card.inspector.status}>{row?.decision ?? enumLabel('InspectorStatus', card.inspector.status)}</Tag>
      </Descriptions.Item>
      {findingIds && (
        <Descriptions.Item label="ID находки">
          <Typography.Text style={{ fontSize: 12 }} code>
            {findingIds}
          </Typography.Text>
        </Descriptions.Item>
      )}
    </Descriptions>
  );
}

export function EvidencePage() {
  const { objectId = '', runId = '', cardNo = '' } = useParams();
  const navigate = useNavigate();
  const view = useProtocol(objectId, runId);
  const p = view.data?.protocol;
  const cards = p?.evidence_cards ?? [];
  const index = cards.findIndex((c) => c.card_no === cardNo);
  const card = index >= 0 ? cards[index] : undefined;
  const names = useMemo(
    () => Object.fromEntries((p?.input_registry?.files ?? []).map((f) => [f.file_id, f.file_name ?? null])),
    [p],
  );
  const group = card ? view.data?.finding_groups.find((g) => g.finding_group_id === card.finding_group_id) ?? null : null;
  const go = (c: EvidenceCard | undefined) =>
    c && navigate(`/objects/${encodeURIComponent(objectId)}/protocols/${runId}/cards/${encodeURIComponent(c.card_no)}`);
  const protocolUrl = `/objects/${encodeURIComponent(objectId)}/protocols/${runId}?card=${encodeURIComponent(cardNo)}`;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.altKey && e.key === 'ArrowRight') go(cards[index + 1]);
      if (e.altKey && e.key === 'ArrowLeft') go(cards[index - 1]);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  if (view.isError) return <ProblemAlert error={view.error} />;
  if (!p) {
    return (
      <Card>
        <Skeleton active />
      </Card>
    );
  }
  if (!card) {
    return (
      <Result
        status="404"
        title={`Карточка ${cardNo} не найдена`}
        extra={
          <Link to={protocolUrl}>
            <Button type="primary">К протоколу</Button>
          </Link>
        }
      />
    );
  }
  return (
    <Flex vertical gap={12} style={{ height: 'calc(100vh - 104px)', minHeight: 640 }}>
      <Flex justify="space-between" align="center" wrap gap={8}>
        <Breadcrumb
          items={[
            { title: <Link to="/dashboard">Дашборд</Link> },
            { title: <Link to={`/objects/${encodeURIComponent(objectId)}`}>{p.object.name ?? objectId}</Link> },
            { title: <Link to={protocolUrl}>Протокол № {p.protocol_no}</Link> },
            { title: `Карточка ${card.card_no}` },
          ]}
        />
        <Space>
          <Tooltip title="Предыдущая карточка (Alt+←)">
            <Button icon={<ArrowLeftOutlined />} disabled={index <= 0} onClick={() => go(cards[index - 1])}>
              {cards[index - 1]?.card_no ?? ''}
            </Button>
          </Tooltip>
          <Typography.Text type="secondary">
            {index + 1} из {cards.length}
          </Typography.Text>
          <Tooltip title="Следующая карточка (Alt+→)">
            <Button disabled={index >= cards.length - 1} onClick={() => go(cards[index + 1])}>
              {cards[index + 1]?.card_no ?? ''} <ArrowRightOutlined />
            </Button>
          </Tooltip>
          <Link to={protocolUrl}>
            <Button icon={<FileTextOutlined />}>В протокол</Button>
          </Link>
        </Space>
      </Flex>
      <Typography.Title level={4} style={{ margin: 0 }}>
        Карточка {card.card_no}. {card.parameter_label}
        {titlePlace(card.locations)}
      </Typography.Title>
      <Flex gap={12} style={{ flex: 1, minHeight: 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <EvidenceViewer key={card.card_no} card={card} group={group} names={names} />
        </div>
        <div style={{ width: 360, flex: '0 0 360px', overflow: 'auto' }}>
          <CardSummary card={card} protocol={p} />
        </div>
      </Flex>
    </Flex>
  );
}
