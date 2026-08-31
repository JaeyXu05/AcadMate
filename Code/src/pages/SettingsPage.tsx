import { useState, useEffect } from 'react';
import { Card, Radio, ColorPicker, App } from 'antd';
import type { RadioChangeEvent } from 'antd';
import { useSettingsStore, PRESET_THEMES, BgThemeKey, SortType, DensityType } from '../stores/settingsStore';
import PageCloseButton from '../components/PageCloseButton';
import styles from './SettingsPage.module.css';

function SettingsPage() {
  const bgTheme = useSettingsStore((s) => s.bgTheme);
  const bgColor = useSettingsStore((s) => s.bgColor);
  const defaultSort = useSettingsStore((s) => s.defaultSort);
  const cardDensity = useSettingsStore((s) => s.cardDensity);
  const setBgTheme = useSettingsStore((s) => s.setBgTheme);
  const setDefaultSort = useSettingsStore((s) => s.setDefaultSort);
  const setCardDensity = useSettingsStore((s) => s.setCardDensity);
  const syncFromServer = useSettingsStore((s) => s.syncFromServer);

  // 页面加载时从服务端拉取设置
  useEffect(() => {
    syncFromServer();
  }, [syncFromServer]);

  const [customColor, setCustomColor] = useState(
    bgTheme === 'custom' ? bgColor : PRESET_THEMES['pure-black'].color,
  );
  const { message } = App.useApp();

  const handleThemeChange = (theme: string) => {
    if (theme === 'custom') {
      setBgTheme('custom', customColor);
    } else {
      setBgTheme(theme as BgThemeKey);
    }
  };

  const handleCustomColorChange = (_: unknown, hex: string) => {
    setCustomColor(hex);
    setBgTheme('custom', hex);
  };

  const handleSortChange = (e: RadioChangeEvent) => {
    setDefaultSort(e.target.value as SortType);
  };

  const handleDensityChange = (e: RadioChangeEvent) => {
    setCardDensity(e.target.value as DensityType);
  };

  const clearAll = () => {
    setBgTheme('pure-black');
    setDefaultSort('match');
    setCardDensity('standard');
    setCustomColor(PRESET_THEMES['pure-black'].color);
    message.success('已恢复默认设置');
  };

  const themeEntries = Object.entries(PRESET_THEMES);

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />
      {/* 背景颜色主题 */}
      <Card className={styles.card} title="背景颜色主题">
        <div className={styles.themeGrid}>
          {themeEntries.map(([key, { label, color }]) => (
            <button
              key={key}
              className={`${styles.themeBtn} ${bgTheme === key ? styles.themeBtnActive : ''}`}
              onClick={() => handleThemeChange(key)}
              title={label}
            >
              <span
                className={styles.themeColor}
                style={{ backgroundColor: color }}
              />
              <span className={styles.themeLabel}>{label}</span>
              {bgTheme === key && (
                <span className={styles.themeCheck}>✓</span>
              )}
            </button>
          ))}
          {/* 自定义 */}
          <button
            className={`${styles.themeBtn} ${bgTheme === 'custom' ? styles.themeBtnActive : ''}`}
            onClick={() => handleThemeChange('custom')}
          >
            <ColorPicker
              value={customColor}
              onChange={handleCustomColorChange}
              disabledAlpha
            >
              <span
                className={styles.themeColor}
                style={{
                  backgroundColor: customColor,
                  cursor: 'pointer',
                }}
              />
            </ColorPicker>
            <span className={styles.themeLabel}>自定义</span>
            {bgTheme === 'custom' && (
              <span className={styles.themeCheck}>✓</span>
            )}
          </button>
        </div>
      </Card>

      {/* 默认排序方式 */}
      <Card className={styles.card} title="默认排序方式">
        <Radio.Group value={defaultSort} onChange={handleSortChange} size="middle">
          <Radio.Button value="match">研究方向匹配</Radio.Button>
          <Radio.Button value="staffId">工号</Radio.Button>
          <Radio.Button value="papers">论文数</Radio.Button>
        </Radio.Group>
      </Card>

      {/* 导师卡片密度 */}
      <Card className={styles.card} title="导师卡片密度">
        <Radio.Group value={cardDensity} onChange={handleDensityChange} size="middle">
          <Radio.Button value="compact">紧凑</Radio.Button>
          <Radio.Button value="standard">标准</Radio.Button>
        </Radio.Group>
      </Card>

      {/* 重置 */}
      <div className={styles.resetRow}>
        <button className={styles.resetBtn} onClick={clearAll}>
          恢复默认设置
        </button>
      </div>
    </div>
  );
}

export default SettingsPage;