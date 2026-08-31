import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Search, Orbit, FileText, MessageSquare } from 'lucide-react';
import LoginModal from '../components/LoginModal';
import KnowledgeGraphWatermark from '../components/shell/KnowledgeGraphWatermark';
import styles from './WelcomePage.module.css';

const STATS = [
  { value: '721', label: '入选导师' },
  { value: '11', label: '研究领域' },
  { value: '1747', label: '结构化证据' },
  { value: '多智能体', label: '检索与审核' },
];

const FEATURES = [
  { icon: <Search size={18} strokeWidth={1.5} className="text-indigo-500" />, title: '智能检索', desc: '多智能体理解研究方向，综合评分推荐导师' },
  { icon: <Orbit size={18} strokeWidth={1.5} className="text-indigo-500" />, title: '3D 研究星图', desc: '在星图中探索导师，按领域与近邻浏览关联' },
  { icon: <MessageSquare size={18} strokeWidth={1.5} className="text-indigo-500" />, title: '深度分析', desc: '从官网、论文、招生意向提炼导师画像' },
  { icon: <FileText size={18} strokeWidth={1.5} className="text-indigo-500" />, title: '材料辅助', desc: '上传简历或研究计划，辅助生成推荐与邮件' },
];

function WelcomePage() {
  const [loginOpen, setLoginOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className={styles.container}>
      <div className="pointer-events-none absolute -left-24 top-[-80px] h-80 w-80 rounded-full bg-purple-200 opacity-40 blur-3xl" />
      <div className="pointer-events-none absolute right-[-40px] top-24 h-96 w-96 rounded-full bg-indigo-200 opacity-40 blur-3xl" />
      <KnowledgeGraphWatermark />

      <div className={styles.content}>
        <div className={styles.hero}>
          <p className="font-mono text-[11px] tracking-[0.22em] text-stone-400">01 · USTC</p>
          <h1 className={styles.title}>科研导师推荐平台</h1>
          <p className={styles.subtitle}>
            面向中国科大的多智能体导师检索 · 论文证据驱动 · 3D 研究星图
          </p>
        </div>

        <div className={styles.stats}>
          {STATS.map((s) => (
            <div key={s.label} className={styles.statItem}>
              <span className={styles.statValue}>{s.value}</span>
              <span className={styles.statLabel}>{s.label}</span>
            </div>
          ))}
        </div>

        <div className={styles.features}>
          {FEATURES.map((f, i) => (
            <div key={f.title} className={styles.feature}>
              <div className="mb-3 font-mono text-[10px] text-stone-400">{String(i + 1).padStart(2, '0')}</div>
              <div className={styles.featureIcon}>{f.icon}</div>
              <div>
                <div className={styles.featureTitle}>{f.title}</div>
                <div className={styles.featureDesc}>{f.desc}</div>
              </div>
            </div>
          ))}
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className="h-11 px-8 text-[15px] font-medium text-white"
            style={{ background: '#1c1917' }}
            onClick={() => setLoginOpen(true)}
            data-testid="welcome-login"
          >
            登录
          </button>
        </div>
        <p className={styles.hint}>首次登录即自动注册</p>
      </div>

      <LoginModal
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          const from = (location.state as { from?: string } | null)?.from;
          navigate(from && from !== '/welcome' ? from : '/search', { replace: true });
        }}
      />
    </div>
  );
}

export default WelcomePage;
