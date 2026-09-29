import { Button, Result } from 'antd';
import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <Result
      status="404"
      title="Страница не найдена"
      subTitle="Такого раздела нет. Выберите раздел в меню слева."
      extra={
        <Link to="/objects">
          <Button type="primary">К объектам</Button>
        </Link>
      }
    />
  );
}
