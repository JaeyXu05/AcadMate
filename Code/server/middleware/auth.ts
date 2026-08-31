import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import '../loadEnv.js';

export function getJwtSecret(): string {
  return String(process.env.JWT_SECRET || '').trim();
}

/** 拒绝使用公开默认密钥：生产/演示环境应配置随机密钥，否则任一客户端可伪造 userId token。 */
export function assertJwtSecretSafe(jwtSecret: string = getJwtSecret()): void {
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

export function authMiddleware(req: AuthRequest, _res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    _res.status(401).json({ message: '未登录，请先登录' });
    return;
  }

  const token = authHeader.slice(7);
  try {
    const payload = jwt.verify(token, getJwtSecret()) as { userId: number };
    req.userId = payload.userId;
    next();
  } catch {
    _res.status(401).json({ message: '登录已过期，请重新登录' });
  }
}

export function generateToken(userId: number): string {
  return jwt.sign({ userId }, getJwtSecret(), { expiresIn: '7d' });
}
