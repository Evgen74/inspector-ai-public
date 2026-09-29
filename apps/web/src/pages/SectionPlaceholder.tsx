import { Card, Flex, Result, Tag, Typography } from 'antd';

/** A module that is part of the product map but lands in a later milestone (all 12 modules stay visible, 97 §2.15). */
export function SectionPlaceholder({ title, description, milestone }: { title: string; description: string; milestone: string }) {
  return (
    <Flex vertical gap={16}>
      <Typography.Title level={3} style={{ margin: 0 }}>
        {title}
      </Typography.Title>
      <Card>
        <Result
          status="info"
          title="Раздел в разработке"
          subTitle={description}
          extra={<Tag color="blue">Этап {milestone}</Tag>}
        />
      </Card>
    </Flex>
  );
}
