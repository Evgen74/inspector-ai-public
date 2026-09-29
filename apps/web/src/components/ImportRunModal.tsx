import { useState } from 'react';
import { App as AntApp, Form, Input, List, Modal, Typography } from 'antd';
import { useImportBatchRun } from '../api/hooks';
import type { ImportResult } from '../api/types';
import { formatInt, pluralRu } from '../format';
import { ProblemAlert } from './ProblemAlert';

/** Admin action: import an inspector-batch run directory (POST /admin/batch-runs/import). */
export function ImportRunModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form] = Form.useForm<{ run_dir: string }>();
  const mutation = useImportBatchRun();
  const { message } = AntApp.useApp();
  const [result, setResult] = useState<ImportResult | null>(null);

  const submit = async () => {
    const { run_dir } = await form.validateFields();
    setResult(null);
    const res = await mutation.mutateAsync(run_dir.trim()).catch(() => null);
    if (!res) return;
    setResult(res);
    const files = res.files_imported;
    void message.success(
      `${res.created ? 'Импортирован' : 'Обновлён'} запуск ${res.run.batch_run_id}: ${res.objects.length} ${pluralRu(
        res.objects.length,
        ['объект', 'объекта', 'объектов'],
      )}, ${formatInt(files)} ${pluralRu(files, ['файл', 'файла', 'файлов'])}`,
    );
    if (res.warnings.length === 0) {
      form.resetFields();
      onClose();
    }
  };

  const close = () => {
    mutation.reset();
    setResult(null);
    onClose();
  };

  return (
    <Modal
      title="Импорт запуска inspector-batch"
      open={open}
      onOk={submit}
      onCancel={close}
      okText="Импортировать"
      cancelText="Закрыть"
      confirmLoading={mutation.isPending}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        Укажите каталог запуска внутри каталога <Typography.Text code>runs/</Typography.Text> (например,{' '}
        <Typography.Text code>20260927T120000Z-inventory</Typography.Text>) или абсолютный путь к нему. Будет прочитан
        файл <Typography.Text code>run_manifest.json</Typography.Text>.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={submit}>
        <Form.Item
          name="run_dir"
          label="Каталог запуска"
          rules={[{ required: true, whitespace: true, message: 'Укажите каталог запуска' }]}
        >
          <Input placeholder="runs/<run_id>" autoFocus />
        </Form.Item>
      </Form>
      {mutation.isError && <ProblemAlert error={mutation.error} />}
      {result && result.warnings.length > 0 && (
        <List
          size="small"
          header={
            <Typography.Text strong>
              Импорт выполнен с предупреждениями ({formatInt(result.warnings.length)})
            </Typography.Text>
          }
          dataSource={result.warnings.slice(0, 20)}
          renderItem={(w) => (
            <List.Item>
              <Typography.Text type="warning">{w.title}:</Typography.Text>&nbsp;{w.detail}
            </List.Item>
          )}
        />
      )}
    </Modal>
  );
}
