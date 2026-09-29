/**
 * «Протокол» (08 S-08): Приложение 2 with Приложения А/Б/В, version history, DOCX/PDF/JSON download (AG-04's
 * export files through the API). Read-only: decisions are made in the verification workspace (AG-05).
 */
import { Alert, Breadcrumb, Button, Card, Empty, Flex, Result, Select, Skeleton, Space, Tag, Tooltip, Typography } from 'antd';
import { PrinterOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { ApiError } from '../../api/client';
import { useProtocol, useProtocolVersions } from '../../api/d1';
import { ProblemAlert } from '../../components/ProblemAlert';
import { enumLabel } from '../../contracts/enums';
import { protocolStatusColor, protocolStatusText } from '../../contracts/labels';
import { RinSyncCard } from '../rin/RinSyncCard';
import { ExportButtons, versionOption } from './ExportButtons';
import { ProtocolDocument, TOC } from './ProtocolDocument';

export function ProtocolPage() {
  const { objectId = '', runId = '' } = useParams();
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const view = useProtocol(objectId, runId);
  const versions = useProtocolVersions(objectId);
  const activeCard = sp.get('card');
  const openCard = (cardNo: string) =>
    navigate(`/objects/${encodeURIComponent(objectId)}/protocols/${runId}/cards/${encodeURIComponent(cardNo)}`);

  if (view.isError && view.error instanceof ApiError && view.error.status === 404) {
    return (
      <Result
        status="404"
        title="Протокол не найден"
        subTitle="В этом запуске нет протокола объекта. Выберите другую версию на карточке объекта."
        extra={
          <Link to={`/objects/${encodeURIComponent(objectId)}?tab=protocols`}>
            <Button type="primary">К версиям протокола</Button>
          </Link>
        }
      />
    );
  }
  if (view.isError && view.error instanceof ApiError && view.error.status === 403) {
    return (
      <Result
        status="403"
        title="Доступ к протоколу закрыт"
        subTitle="Объект входит в скрытую тестовую выборку: результаты не показываются до отправки итогового ответа."
      />
    );
  }

  const data = view.data;
  const p = data?.protocol;
  const note = typeof p?.ext?.note === 'string' ? p.ext.note : null;

  return (
    <Flex vertical gap={12}>
      <Breadcrumb
        items={[
          { title: <Link to="/dashboard">Дашборд</Link> },
          { title: <Link to={`/objects/${encodeURIComponent(objectId)}`}>{p?.object.name ?? objectId}</Link> },
          { title: <Link to={`/objects/${encodeURIComponent(objectId)}?tab=protocols`}>Протоколы</Link> },
          { title: p ? `№ ${p.protocol_no}` : '…' },
        ]}
      />
      {view.isError ? (
        <ProblemAlert error={view.error} action={<Button onClick={() => void view.refetch()}>Повторить</Button>} />
      ) : !data || !p ? (
        <Card>
          <Skeleton active paragraph={{ rows: 12 }} />
        </Card>
      ) : (
        <>
          <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
            <Flex justify="space-between" align="center" wrap gap={12}>
              <Flex vertical gap={4}>
                <Typography.Title level={4} style={{ margin: 0 }}>
                  Протокол № {p.protocol_no}
                </Typography.Title>
                <Space size={6} wrap>
                  <Tag color={protocolStatusColor(data.version.status)} data-code={data.version.status}>
                    {protocolStatusText(data.version.status, data.version.web_version)}
                  </Tag>
                  <Tag>{data.version.is_final ? 'окончательная' : 'предварительная'}</Tag>
                  <Tag data-code={p.scenario}>Тип проверки: {enumLabel('LoadScenario', p.scenario)}</Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    запуск {data.version.batch_run_id} · конвейер {p.versions.pipeline_version}
                    {p.versions.matrix_version ? ` · матрица ${p.versions.matrix_version}` : ''}
                  </Typography.Text>
                </Space>
              </Flex>
              <Space wrap>
                <Select
                  style={{ minWidth: 320 }}
                  value={runId}
                  loading={versions.isLoading}
                  onChange={(v) => navigate(`/objects/${encodeURIComponent(objectId)}/protocols/${v}`)}
                  options={(versions.data?.items ?? [data.version]).map(versionOption)}
                  aria-label="Версия протокола"
                />
                <ExportButtons objectId={objectId} version={data.version} />
                <Tooltip title="Печать экранной формы">
                  <Button icon={<PrinterOutlined />} onClick={() => window.print()} aria-label="Печать" />
                </Tooltip>
                <Tooltip title="Решения по находкам принимаются в модуле верификации">
                  <Link to={`/verification?object=${encodeURIComponent(objectId)}&run=${runId}`}>
                    <Button type="primary" icon={<SafetyCertificateOutlined />}>
                      Верификация
                    </Button>
                  </Link>
                </Tooltip>
              </Space>
            </Flex>
          </Card>
          <RinSyncCard objectId={objectId} runId={runId} />
          {note && <Alert type="info" showIcon title="Примечание к протоколу" description={note} />}
          {data.warnings.length > 0 && (
            <Alert
              type="warning"
              showIcon
              title="Часть артефактов запуска не прошла проверку контракта"
              description={data.warnings.map((w, i) => (
                <div key={i}>{w.detail}</div>
              ))}
            />
          )}
          <Flex gap={16} align="flex-start">
            <Card
              size="small"
              title="Содержание"
              style={{ width: 230, flex: '0 0 230px', position: 'sticky', top: 12 }}
              className="p2-toc"
            >
              <nav aria-label="Разделы протокола" className="p2-toc">
                {TOC.map((t) => (
                  <a key={t.id} href={`#${t.id}`}>
                    {t.label(p)}
                  </a>
                ))}
              </nav>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
                Карточки доказательств
              </Typography.Text>
              {p.evidence_cards.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Нет" />}
              <Flex vertical gap={2}>
                {p.evidence_cards.map((c) => (
                  <Button
                    key={c.card_no}
                    size="small"
                    type={activeCard === c.card_no ? 'primary' : 'text'}
                    style={{ justifyContent: 'flex-start', textAlign: 'left', height: 'auto', whiteSpace: 'normal' }}
                    onClick={() => openCard(c.card_no)}
                  >
                    {c.card_no} · {c.parameter_code}
                    {c.locations.length ? ` · ${c.locations.join(', ')}` : ''}
                  </Button>
                ))}
              </Flex>
            </Card>
            <div style={{ flex: 1, minWidth: 0 }}>
              <ProtocolDocument protocol={p} activeCard={activeCard} onOpenCard={openCard} />
            </div>
          </Flex>
        </>
      )}
    </Flex>
  );
}
