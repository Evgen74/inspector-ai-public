import { Alert, Typography } from 'antd';
import { ApiError } from '../api/client';

/** Error state for a failed request: Russian title/detail from the problem body + «Код обращения». */
export function ProblemAlert({ error, action }: { error: unknown; action?: React.ReactNode }) {
  const api = error instanceof ApiError ? error : null;
  const title = api?.title ?? 'Ошибка';
  const detail = api?.detail ?? (error instanceof Error ? error.message : 'Неизвестная ошибка');
  return (
    <Alert
      type="error"
      showIcon
      title={title}
      description={
        <>
          <div>{detail}</div>
          {api?.problem?.errors?.map((e, i) => (
            <div key={`${e.code}-${i}`}>
              <Typography.Text type="secondary">{e.pointer ? `${e.pointer}: ` : ''}</Typography.Text>
              {e.detail}
            </div>
          ))}
          {api && api.status !== 0 && (
            <Typography.Text type="secondary" copyable={{ text: api.requestId }}>
              Код обращения: {api.requestId}
            </Typography.Text>
          )}
        </>
      }
      action={action}
    />
  );
}
