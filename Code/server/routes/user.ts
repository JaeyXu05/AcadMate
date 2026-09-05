import { Router, Response } from 'express';
import { createHash } from 'crypto';
import { getDb } from '../db';
import { loadGrowthState, loadTrustedAgentContext } from '../data/growthStore';
import { postHarnessRun } from '../harnessClient';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { explainResearchProfileError, researchProfileTimeoutMs } from '../researchRuntime';
import { getLlmApiSettings, saveLlmApiSettings } from '../services/llmSettings';

export const userRouter = Router();

// 所有路由需要登录
userRouter.use(authMiddleware);

/** GET /api/user/profile — 获取用户信息 */
userRouter.get('/profile', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const user = db
    .prepare('SELECT id, email, nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
    .get(req.userId!) as Record<string, unknown> | undefined;

  if (!user) {
    res.status(404).json({ message: '用户不存在' });
    return;
  }

  res.json({
    id: user.id,
    email: user.email,
    nickname: user.nickname,
    grade: user.grade,
    major: user.major,
    interests: safeParse(user.interests as string),
    skills: safeParse(user.skills as string),
    bio: user.bio,
  });
});

/** PUT /api/user/profile — 更新用户信息 */
userRouter.put('/profile', (req: AuthRequest, res: Response) => {
  const { nickname, grade, major, interests, skills, bio } = req.body ?? {};

  const db = getDb();

  // 只允许这些字段
  const updates: string[] = [];
  const params: unknown[] = [];

  if (nickname !== undefined) {
    updates.push('nickname = ?');
    params.push(nickname);
  }
  if (grade !== undefined) {
    updates.push('grade = ?');
    params.push(grade);
  }
  if (major !== undefined) {
    updates.push('major = ?');
    params.push(major);
  }
  if (interests !== undefined) {
    updates.push('interests = ?');
    params.push(JSON.stringify(interests));
  }
  if (skills !== undefined) {
    updates.push('skills = ?');
    params.push(JSON.stringify(skills));
  }
  if (bio !== undefined) {
    updates.push('bio = ?');
    params.push(bio);
  }

  if (updates.length > 0) {
    updates.push("updated_at = datetime('now','localtime')");
    params.push(req.userId!);
    db.prepare(`UPDATE users SET ${updates.join(', ')} WHERE id = ?`).run(...params);
  }

  // 返回更新后的用户
  const user = db
    .prepare('SELECT id, email, nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
    .get(req.userId!) as Record<string, unknown>;

  res.json({
    id: user.id,
    email: user.email,
    nickname: user.nickname,
    grade: user.grade,
    major: user.major,
    interests: safeParse(user.interests as string),
    skills: safeParse(user.skills as string),
    bio: user.bio,
  });
});

function researchProfileSignature(context: ReturnType<typeof loadTrustedAgentContext>): string {
  return createHash('sha256').update(JSON.stringify({
    profile: context.profile,
    growth: context.growth,
  })).digest('hex');
}

function savedResearchProfile(userId: number): Record<string, unknown> | null {
  const row = getDb().prepare(
    'SELECT research_profile_json FROM users WHERE id=?',
  ).get(userId) as { research_profile_json?: string } | undefined;
  if (!row?.research_profile_json) return null;
  try {
    const parsed = JSON.parse(row.research_profile_json);
    return parsed
      && typeof parsed === 'object'
      && !Array.isArray(parsed)
      && parsed.type === 'research_profile'
      && typeof parsed.summary === 'string'
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

/** GET /api/user/research-profile — 读取最近一次模型生成的科研画像。 */
userRouter.get('/research-profile', (req: AuthRequest, res: Response) => {
  const profile = savedResearchProfile(req.userId!);
  const signature = researchProfileSignature(loadTrustedAgentContext(req.userId!));
  res.json({
    profile,
    stale: Boolean(profile && profile.source_signature !== signature),
  });
});

/** GET /api/user/api-settings — 当前登录用户自己的大模型 API 配置（不回传明文 key）。 */
userRouter.get('/api-settings', (req: AuthRequest, res: Response) => {
  const settings = getLlmApiSettings(req.userId!);
  res.json({
    enabled: settings.enabled,
    base_url: settings.baseUrl,
    model: settings.model,
    api_key_saved: settings.apiKeySaved,
    updated_at: settings.updatedAt,
  });
});

/** PUT /api/user/api-settings — 保存当前用户自己的大模型 API 配置。 */
userRouter.put('/api-settings', (req: AuthRequest, res: Response) => {
  const body = (req.body ?? {}) as {
    enabled?: unknown;
    base_url?: unknown;
    model?: unknown;
    api_key?: unknown;
    remove_key?: unknown;
  };
  const settings = saveLlmApiSettings(req.userId!, {
    enabled: body.enabled === undefined ? undefined : Boolean(body.enabled),
    baseUrl: body.base_url === undefined ? undefined : String(body.base_url || ''),
    model: body.model === undefined ? undefined : String(body.model || ''),
    apiKey: body.api_key === undefined ? undefined : String(body.api_key || ''),
    removeKey: body.remove_key === true,
  });
  res.json({
    enabled: settings.enabled,
    base_url: settings.baseUrl,
    model: settings.model,
    api_key_saved: settings.apiKeySaved,
    updated_at: settings.updatedAt,
  });
});

/** POST /api/user/research-profile — 用 A 端真实模型生成证据受限的科研画像。 */
userRouter.post('/research-profile', async (req: AuthRequest, res: Response) => {
  const context = loadTrustedAgentContext(req.userId!);
  const signature = researchProfileSignature(context);
  try {
    const result = await postHarnessRun({
      skill_id: 'profile_analyze',
      message: '根据个人信息与已审核成长记录生成科研画像',
      context: {
        user_id: String(req.userId!),
        profile: context.profile,
        growth: context.growth,
      },
      // Allow the same 120s provider budget as other model features plus
      // headroom for the synchronous A-side profile call. A 28s cap caused
      // valid slow DeepSeek responses to surface as "生成超时".
    }, researchProfileTimeoutMs());
    const artifact = result?.artifact;
    const runStatus = String(result?.status || '');
    const reviewStatus = String(result?.review_status || artifact?.review_status || '');
    if (runStatus === 'waiting_for_user') {
      const error = new Error(String(artifact?.error || '请先完善个人信息，再生成科研画像。'));
      (error as Error & { status?: number }).status = 400;
      throw error;
    }
    if (
      runStatus !== 'succeeded'
      || reviewStatus !== 'PASS'
      || artifact?.type !== 'research_profile'
      || typeof artifact?.summary !== 'string'
    ) {
      const detail = String(artifact?.error || '科研画像未通过证据审核，已保留原有画像，请补充资料后重试。');
      const error = new Error(detail);
      (error as Error & { status?: number }).status = 502;
      throw error;
    }
    const saved = { ...artifact, source_signature: signature };
    getDb().prepare(
      "UPDATE users SET research_profile_json=?, research_profile_updated_at=datetime('now','localtime') WHERE id=?",
    ).run(JSON.stringify(saved), req.userId!);
    res.json({ profile: saved, stale: false });
  } catch (error) {
    const mapped = explainResearchProfileError(error, researchProfileTimeoutMs());
    const status = Number((error as { status?: number })?.status) || (mapped.timedOut ? 504 : 502);
    res.status(status).json({ message: mapped.message });
  }
});

/** DELETE /api/user/account — 注销账号（级联删除 favorites/settings/history） */
userRouter.delete('/account', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const result = db.prepare('DELETE FROM users WHERE id = ?').run(req.userId!);
  if (result.changes === 0) {
    res.status(404).json({ message: '用户不存在' });
    return;
  }
  // favorites / user_settings / search_history / chat_history / growth_state 均有 ON DELETE CASCADE，自动清理
  res.json({ deleted: true });
});

/** GET /api/user/growth — 科研成长状态 */
userRouter.get('/growth', (req: AuthRequest, res: Response) => {
  res.json(loadGrowthState(req.userId!));
});

/** PUT /api/user/growth — 成长状态只允许服务端从 Review PASS 的 AgentRun 写回。 */
userRouter.put('/growth', (_req: AuthRequest, res: Response) => {
  res.status(403).json({
    message: '科研成长状态为审核结果，只能由 Review PASS 的 AgentRun 写回',
  });
});

function safeParse(val: string): string[] {
  if (!val) return [];
  try {
    const parsed = JSON.parse(val);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
