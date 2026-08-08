import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });

export const JWT_SECRET = process.env.JWT_SECRET || 'dev-secret-change-me';

/** 拒绝使用公开默认密钥：生产/演示环境应配置随机密钥，否则任一客户端可伪造 userId token。 */
export function assertJwtSecretSafe(jwtSecret: string = JWT_SECRET): void {
  const dangerous = new Set([
    'dev-secret-change-me',
    'secret',
    'changeme',
    '',
    'your-secret-key',
  ]);
  if (dangerous.has(jwtSecret) || jwtSecret.length < 16) {
    throw new Error(
      `JWT_SECRET 不安全（${jwtSecret ? '使用了默认/过短密钥' : '未配置'}）。` +
        `请在 Code/.env 设置一个随机长密钥，例如：openssl rand -hex 32`,
    );
  }
}

export interface AuthRequest extends Request {
  userId?: number;
}

/**
 * JWT 验证中间件。
 * 从 Authorization: Bearer <token> 中解析 userId，
 * 挂载到 req.userId 上供后续路由使用。
 */
export function authMiddleware(req: AuthRequest, _res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    _res.status(401).json({ message: '未登录，请先登录' });
    return;
  }

  const token = authHeader.slice(7);
  try {
    const payload = jwt.verify(token, JWT_SECRET) as { userId: number };
    req.userId = payload.userId;
    next();
  } catch {
    _res.status(401).json({ message: '登录已过期，请重新登录' });
  }
}

/** 生成 JWT token，默认 7 天过期 */
export function generateToken(userId: number): string {
  return jwt.sign({ userId }, JWT_SECRET, { expiresIn: '7d' });
}