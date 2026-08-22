import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';
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

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.join(__dirname, '..', '.env') });

// ---- 启动前校验：JWT 密钥必须安全（拒绝默认/过短），否则直接退出 ----
assertJwtSecretSafe();

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
app.use(express.json({ limit: '1mb' }));

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

// ---- 启动 ----
app.listen(PORT, () => {
  console.log(`\n✅ 后端服务已启动: http://localhost:${PORT}`);
  console.log(`   API 前缀: /api`);
  console.log(`   健康检查: http://localhost:${PORT}/api/health`);
  console.log(
    `   导师数据源: ${ragData.isReady ? `已就绪（${ragData.candidates.length} 位导师）` : `不可用：${ragData.errorMessage ?? '未知错误'}`}`,
  );
  console.log(`   CORS 允许: ${allowedOrigins.join(', ')}\n`);
});