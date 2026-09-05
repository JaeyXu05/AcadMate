import { useEffect } from 'react';
import { Card, Radio, App } from 'antd';
import type { RadioChangeEvent } from 'antd';
import { useSettingsStore, SortType, DensityType } from '../stores/settingsStore';
import PageCloseButton from '../components/PageCloseButton';
import styles from './SettingsPage.module.css';

function SettingsPage() {
  const defaultSort = useSettingsStore((s) => s.defaultSort);
  const cardDensity = useSettingsStore((s) => s.cardDensity);
  const setDefaultSort = useSettingsStore((s) => s.setDefaultSort);
  const setCardDensity = useSettingsStore((s) => s.setCardDensity);
  const syncFromServer = useSettingsStore((s) => s.syncFromServer);
  const { message } = App.useApp();

  useEffect(() => {
    syncFromServer();
  }, [syncFromServer]);

  const handleSortChange = (e: RadioChangeEvent) => {
    setDefaultSort(e.target.value as SortType);
  };

  const handleDensityChange = (e: RadioChangeEvent) => {
    setCardDensity(e.target.value as DensityType);
  };

  const reset = () => {
    setDefaultSort('match');
    setCardDensity('standard');
    message.success('已恢复默认设置');
  };

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />

      <Card className={styles.card} title="默认排序方式">
        <Radio.Group value={defaultSort} onChange={handleSortChange} size="middle">
          <Radio.Button value="match">研究方向匹配</Radio.Button>
          <Radio.Button value="staffId">工号</Radio.Button>
          <Radio.Button value="papers">论文数</Radio.Button>
        </Radio.Group>
      </Card>

      <Card className={styles.card} title="导师卡片密度">
        <Radio.Group value={cardDensity} onChange={handleDensityChange} size="middle">
          <Radio.Button value="compact">紧凑</Radio.Button>
          <Radio.Button value="standard">标准</Radio.Button>
        </Radio.Group>
      </Card>

      <div className={styles.resetRow}>
        <button className={styles.resetBtn} onClick={reset}>
          恢复默认设置
        </button>
      </div>
    </div>
  );
}

export default SettingsPage;
