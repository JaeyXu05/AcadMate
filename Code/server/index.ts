import './loadEnv.js';
import express from 'express';
import cors from 'cors';
import { assertJwtSecretSafe } from './middleware/auth.js';
import { ragData } from './data/ragAdvisors.js';
import { authRouter } from './routes/auth.js';
import { userRouter } from './routes/user.js';
import { favoritesRouter } from './routes/favorites.js';
import { historyRouter } from './routes/history.js';
import { agentRouter } from './routes/agent.js';
import { settingsRouter } from './routes/settings.js';
import { advisorsRouter } from './routes/advisors.js';
import { emailRouter } from './routes/email.js';
import { pdfRouter, uploadRouter } from './routes/pdf.js';
import { recommendRouter } from './routes/recommend.js';
import { cloudRouter } from './routes/cloud.js';
import { missionRouter } from './routes/mission.js';
import { feedbackRouter } from './routes/feedback.js';
import { reportsRouter, runReportScheduler } from './routes/reports.js';
import { plansRouter, runPlanReminderScheduler } from './routes/plans.js';
import { conversationsRouter } from './routes/conversations.js';
import { researchRouter } from './routes/research.js';
import { skillsRouter } from './routes/skills.js';
import { integrationsRouter } from './routes/integrations.js';
import { papersRouter } from './routes/papers.js';
import { getDb } from './db.js';
import { reconcilePendingGrowthWrites } from './routes/agent.js';
import { agentBase, probeAgent } from './harnessClient.js';

assertJwtSecretSafe();
getDb();

const app = express();
const PORT = Number(process.env.PORT) || 3001;

// ---- 中间件 ----
// CORS：本地开发只放行 Vite 前端源（5173），生产按 .env CORS_ORIGINS 配置
const allowedOrigins = (process.env.CORS_ORIGINS || 'http://localhost:5173')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);
app.use(
  cors({
    origin: allowedOrigins,
    credentials: true,
  }),
);
app.use(express.json({ limit: '30mb' }));

// ---- 路由 ----
app.use('/api/auth', authRouter);
app.use('/api/user', userRouter);
app.use('/api/favorites', favoritesRouter);
app.use('/api/history', historyRouter);
app.use('/api/agent', agentRouter);
app.use('/api/settings', settingsRouter);
app.use('/api/advisors', advisorsRouter);
app.use('/api/email', emailRouter);
app.use('/api/upload', uploadRouter);
app.use('/api/pdf', pdfRouter);
app.use('/api/recommend', recommendRouter);
app.use('/api/cloud', cloudRouter);
app.use('/api/mission', missionRouter);
app.use('/api/feedback', feedbackRouter);
app.use('/api/reports', reportsRouter);
app.use('/api/plans', plansRouter);
app.use('/api/conversations', conversationsRouter);
app.use('/api/research', researchRouter);
app.use('/api/skills', skillsRouter);
app.use('/api/integrations', integrationsRouter);
app.use('/api/papers', papersRouter);

// ---- 健康检查 ----
app.get('/api/health', (_req, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    rag: {
      ready: ragData.isReady,
      count: ragData.candidates.length,
      source: ragData.sourcePath || null,
      error: ragData.errorMessage,
    },
  });
});

app.get('/api/ready', async (_req, res) => {
  const agentConfigured = Boolean(agentBase());
  const agentReady = agentConfigured ? await probeAgent(1500) : false;
  const ready = ragData.isReady && agentReady;
  res.status(ready ? 200 : 503).json({
    status: ready ? 'ready' : 'degraded',
    rag: { ready: ragData.isReady, count: ragData.candidates.length },
    mentor_agent: { configured: agentConfigured, ready: agentReady },
  });
});

app.use((err: unknown, _req: express.Request, res: express.Response, next: express.NextFunction) => {
  if (res.headersSent) { next(err); return; }
  const message = err instanceof Error ? err.message : '服务器错误';
  const status = Number((err as { status?: number })?.status) || 500;
  res.status(status).json({ message });
});

// ---- 启动 ----
// 为长任务保留足够时间，但不再允许死连接无限占用资源。
const server = app.listen(PORT, () => {
  console.log(`\n✅ 后端服务已启动: http://localhost:${PORT}`);
  console.log(`   API 前缀: /api`);
  console.log(`   健康检查: http://localhost:${PORT}/api/health`);
  console.log(
    `   导师数据源: ${ragData.isReady ? `已就绪（${ragData.candidates.length} 位导师）` : `不可用：${ragData.errorMessage ?? '未知错误'}`}`,
  );
  console.log(`   CORS 允许: ${allowedOrigins.join(', ')}\n`);
  void reconcilePendingGrowthWrites();
  setInterval(() => {
    void reconcilePendingGrowthWrites();
  }, 30_000).unref?.();
  const productivityTimer = setInterval(() => {
    void runReportScheduler();
    void runPlanReminderScheduler();
  }, 60_000);
  productivityTimer.unref?.();
  // 启动后立即补跑已到发送时间但因服务重启错过的日报/周报/月报。
  void runReportScheduler();
});
server.requestTimeout = 480_000;
server.headersTimeout = 490_000;
server.timeout = 480_000;
