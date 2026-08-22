import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { SearchOutlined, CloudOutlined, FilePdfOutlined, CommentOutlined } from '@ant-design/icons';
import BackgroundLayer from '../components/BackgroundLayer';
import LoginModal from '../components/LoginModal';
import Button from '../components/Button';
import styles from './WelcomePage.module.css';

/** 平台品牌数据（与 RAG 库构建对齐，真实数字） */
const STATS = [
  { value: '715', label: '入选导师' },
  { value: '10', label: '研究领域' },
  { value: '1580', label: '结构化证据' },
  { value: '24/7', label: '智能检索' },
];

/** 核心功能速览（欢迎页使用，落地页抓眼球） */
const FEATURES = [
  { icon: <SearchOutlined />, title: '智能检索', desc: '多智能体理解你的研究方向，综合评分推荐最匹配导师' },
  { icon: <CloudOutlined />, title: '3D 研究星图', desc: '在银河星图中探索中国科大导师，按领域与亮度直觉浏览' },
  { icon: <CommentOutlined />, title: '深度分析', desc: '从官网、论文、招生意向多源证据提炼导师画像与任职信息' },
  { icon: <FilePdfOutlined />, title: '材料辅助', desc: '上传简历 / 研究计划，辅助生成推荐与邮件草稿' },
];

function WelcomePage() {
  const [loginOpen, setLoginOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const openLogin = () => setLoginOpen(true);

  return (
    <div className={styles.container}>
      <BackgroundLayer />

      <div className={styles.content}>
        {/* 品牌区 */}
        <div className={styles.hero}>
          <div className={styles.logoBadge}>
            <CloudOutlined style={{ fontSize: 40, color: '#a8c0ff' }} />
          </div>
          <h1 className={styles.title}>
            科研导师推荐平台
          </h1>
          <p className={styles.subtitle}>
            面向中国科大的多智能体导师检索 · 论文证据驱动 · 3D 研究星图
          </p>
        </div>

        {/* 真实数据统计 */}
        <div className={styles.stats}>
          {STATS.map((s) => (
            <div key={s.label} className={styles.statItem}>
              <span className={styles.statValue}>{s.value}</span>
              <span className={styles.statLabel}>{s.label}</span>
            </div>
          ))}
        </div>

        {/* 功能速览 */}
        <div className={styles.features}>
          {FEATURES.map((f) => (
            <div key={f.title} className={styles.feature}>
              <div className={styles.featureIcon}>{f.icon}</div>
              <div>
                <div className={styles.featureTitle}>{f.title}</div>
                <div className={styles.featureDesc}>{f.desc}</div>
              </div>
            </div>
          ))}
        </div>

        {/* CTA */}
        <div className={styles.actions}>
          <Button
            variant="brand"
            size="large"
            onClick={openLogin}
            data-testid="welcome-login"
          >
            登录
          </Button>
        </div>
        <p className={styles.hint}>首次登录即自动注册</p>
      </div>

      <LoginModal
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          // 若从被踢回的场景回来，回到之前想去的页；默认去检索
          const from = (location.state as { from?: string } | null)?.from;
          navigate(from && from !== '/welcome' ? from : '/search', { replace: true });
        }}
      />
    </div>
  );
}

export default WelcomePage;