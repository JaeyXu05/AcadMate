/**
 * 极简内存限流中间件（无第三方依赖）。
 *
 * 按 IP + 路径 在滑动窗口内计数，超限返回 429。适合本地/演示部署在进程内存
 * 中跑；若将来水平扩展/多实例，请换成 Redis 等共享方案。
 *
 * 用法：router.use(rateLimit({ windowMs: 60_000, max: 30, label: 'auth' }));
 */
import { Request, Response, NextFunction } from 'express';

interface RateLimitOptions {
  /** 窗口时长 ms */
  windowMs: number;
  /** 窗口内允许的最大请求数 */
  max: number;
  /** 计数 key 前缀（区分不同限流点） */
  label: string;
  /** 命中上限后提示文案 */
  message?: string;
}

export function rateLimit(options: RateLimitOptions) {
  const { windowMs, max, label, message } = options;
  // label -> key(ip) -> { count, resetAt }
  const buckets = new Map<
    string,
    Map<string, { count: number; resetAt: number }>
  >();

  // 惰性清理过期桶，防止 Map 无限增长
  setInterval(() => {
    const now = Date.now();
    for (const [lbl, byIp] of buckets) {
      for (const [ip, rec] of byIp) {
        if (now > rec.resetAt) byIp.delete(ip);
      }
      if (byIp.size === 0) buckets.delete(lbl);
    }
  }, 60_000).unref();

  return (req: Request, res: Response, next: NextFunction): void => {
    const ip = req.ip || req.socket.remoteAddress || 'unknown';
    const now = Date.now();
    let byIp = buckets.get(label);
    if (!byIp) {
      byIp = new Map();
      buckets.set(label, byIp);
    }
    let rec = byIp.get(ip);
    if (!rec || now > rec.resetAt) {
      rec = { count: 0, resetAt: now + windowMs };
      byIp.set(ip, rec);
    }
    rec.count += 1;
    if (rec.count > max) {
      res.status(429).json({ message: message ?? '请求过于频繁，请稍后再试' });
      return;
    }
    next();
  };
}