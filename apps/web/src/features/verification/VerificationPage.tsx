/**
 * Routes of the verification feature (AG-05; wiring in App.tsx by AG-08):
 * - /verification                          → objects with their verification sessions;
 * - /objects/:objectId/verify              → the latest process of the object;
 * - /verification/:processId/:findingId?   → the workspace (deep link to a card).
 */
import { Card, Empty, Flex, Skeleton, Table, Tag, Typography } from 'antd';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useDashboard } from '../../api/d1';
import { IndicatorTag } from '../../components/indicator';
import { enumLabel } from '../../contracts/enums';
import { ProblemAlert } from '../../components/ProblemAlert';
import { useObjectVerification } from './api';
import { Workspace } from './Workspace';

export function verificationPath(processId: string, findingId?: string | null): string {
  return `/verification/${encodeURIComponent(processId)}${findingId ? `/${encodeURIComponent(findingId)}` : ''}`;
}

function ObjectRedirect({ objectId }: { objectId: string }) {
  const q = useObjectVerification(objectId);
  if (q.isPending) return <Skeleton active style={{ padding: 24 }} />;
  if (q.error) return <ProblemAlert error={q.error} />;
  const latest = q.data.processes[0];
  if (!latest) {
    return (
      <Flex vertical gap={12} style={{ padding: 24 }} data-testid="verify-empty">
        <Link to="/verification">← К списку верификации</Link>
        <Typography.Title level={3} style={{ margin: 0 }}>
          Верификация
        </Typography.Title>
        <Empty description="Для этого объекта пока нет проверки с протоколом. Загрузите комплект документов и запустите проверку — после этого здесь появятся кандидаты на верификацию." />
        <Link to={`/objects/${encodeURIComponent(objectId)}`}>К странице объекта</Link>
      </Flex>
    );
  }
  return <Navigate to={verificationPath(latest.process_id, latest.next_finding_id)} replace />;
}

function VerificationIndex() {
  // The dashboard carries the server-computed indicator and the protocol's scenario (the raw objects list does not).
  const objects = useDashboard({});
  return (
    <Flex vertical gap={12} style={{ padding: 24 }}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        Верификация
      </Typography.Title>
      <Typography.Text type="secondary">
        Проверка кандидатов по карточкам доказательств: подтверждение, отклонение с кодом причины или запрос уточнения
        (п. 9.3 ТЗ). Выберите объект.
      </Typography.Text>
      <Card size="small">
        {objects.error ? (
          <ProblemAlert error={objects.error} />
        ) : (
          <Table
            size="small"
            loading={objects.isPending}
            rowKey="object_id"
            pagination={false}
            dataSource={(objects.data?.items ?? []).filter((o) => o.split !== 'TEST_HIDDEN')}
            columns={[
              { title: 'Объект', key: 'o', render: (_, o) => <Link to={`/objects/${encodeURIComponent(o.object_id)}/verify`}>{o.name ?? o.object_id}</Link> },
              {
                title: 'Тип проверки',
                key: 'scenario',
                render: (_, o) => (o.latest_protocol ? enumLabel('LoadScenario', o.latest_protocol.scenario) : '—'),
              },
              { title: 'Индикация', key: 'indicator', render: (_, o) => <IndicatorTag indicator={o.indicator} /> },
            ]}
          />
        )}
      </Card>
    </Flex>
  );
}

export function VerificationPage() {
  const { processId, findingId, objectId } = useParams();
  const navigate = useNavigate();
  if (processId) {
    return (
      <Workspace
        pid={processId}
        findingId={findingId ?? null}
        onSelect={(fid, replace) => navigate(verificationPath(processId, fid), { replace: Boolean(replace) })}
      />
    );
  }
  if (objectId) return <ObjectRedirect objectId={objectId} />;
  return <VerificationIndex />;
}
