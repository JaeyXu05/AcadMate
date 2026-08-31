import { useEffect, useState } from 'react';
import { Button, Empty, Input, Modal, Select, Tag, message } from 'antd';
import { Code2, Plus, ShieldCheck } from 'lucide-react';
import * as skillsApi from '../services/skills';
import type { CustomSkill } from '../services/skills';
import { apiErrorMessage } from '../services/axios';
import styles from './SkillsPage.module.css';

function SkillsPage() {
  const [skills, setSkills] = useState<CustomSkill[]>([]);
  const [editing, setEditing] = useState<CustomSkill | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [prompt, setPrompt] = useState('');
  const [permissions, setPermissions] = useState('read_project_papers');
  const [triggerMode, setTriggerMode] = useState<'manual' | 'manual_or_suggest'>('manual_or_suggest');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setSkills(await skillsApi.listSkills()); }
    catch (error: unknown) { message.error(apiErrorMessage(error, 'Skill 列表加载失败')); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const openCreate = () => { setEditing(null); setName(''); setDescription(''); setPrompt(''); setPermissions('read_project_papers'); setTriggerMode('manual_or_suggest'); setCreating(true); };
  const openEdit = (skill: CustomSkill) => { setEditing(skill); setName(skill.name); setDescription(skill.description); setPrompt(skill.prompt_template); setPermissions(skill.permissions.join(', ')); setTriggerMode(skill.trigger_mode === 'manual' ? 'manual' : 'manual_or_suggest'); setCreating(true); };
  const save = async () => {
    if (!name.trim()) return;
    const input = { name: name.trim(), description: description.trim(), prompt_template: prompt.trim(), trigger_mode: triggerMode, permissions: permissions.split(/[,，]/).map((item) => item.trim()).filter(Boolean), allowed_tools: editing?.allowed_tools || [] };
    try {
      const saved = editing ? await skillsApi.updateSkill(editing.id, input) : await skillsApi.createSkill(input);
      setSkills((current) => editing ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current]);
      setCreating(false);
      message.success(editing ? 'Skill 已更新' : 'Skill 已创建');
    } catch (error: unknown) { message.error(apiErrorMessage(error, 'Skill 保存失败')); }
  };
  const toggle = async (skill: CustomSkill) => {
    try { const updated = await skillsApi.setSkillStatus(skill.id, skill.status === 'enabled' ? 'disabled' : 'enabled'); setSkills((current) => current.map((item) => item.id === updated.id ? updated : item)); }
    catch (error: unknown) { message.error(apiErrorMessage(error, 'Skill 状态更新失败')); }
  };
  const validate = async (skill: CustomSkill) => {
    try { const result = await skillsApi.validateSkill(skill.id); result.valid ? message.success('Skill 配置有效') : message.warning(result.errors.join('；')); }
    catch (error: unknown) { message.error(apiErrorMessage(error, 'Skill 验证失败')); }
  };

  return <div className={styles.page}>
    <header className={styles.header}><div><div className={styles.kicker}>OTHER · SKILLS</div><h1>Skill 管理</h1><p>用声明式配置定制科研助手的工作方式；每个 Skill 都有独立版本和权限。</p></div><Button type="primary" icon={<Plus size={15} />} onClick={openCreate}>新建 Skill</Button></header>
    <div className={styles.notice}><ShieldCheck size={16} /> 当前版本只允许调用已授权的系统工具，不执行用户上传的任意代码。</div>
    {loading ? <div className={styles.loading}>加载中…</div> : skills.length === 0 ? <Empty description="还没有自定义 Skill" /> : <div className={styles.grid}>{skills.map((skill) => <article className={styles.card} key={skill.id}><div className={styles.cardHead}><Code2 size={17} /><div><h2>{skill.name}</h2><span>v{skill.version} · {skill.trigger_mode === 'manual' ? '手动触发' : '手动或建议'}</span></div><Tag color={skill.status === 'enabled' ? 'green' : 'default'}>{skill.status === 'enabled' ? '已启用' : skill.status === 'disabled' ? '已停用' : '草稿'}</Tag></div><p>{skill.description || '暂无说明'}</p><div className={styles.permissions}>{skill.permissions.map((item) => <Tag key={item}>{item}</Tag>)}</div><div className={styles.actions}><Button size="small" onClick={() => openEdit(skill)}>编辑</Button><Button size="small" onClick={() => void validate(skill)}>验证</Button><Button size="small" type={skill.status === 'enabled' ? 'default' : 'primary'} onClick={() => void toggle(skill)}>{skill.status === 'enabled' ? '停用' : '启用'}</Button></div></article>)}</div>}
    <Modal open={creating} title={editing ? '编辑 Skill' : '新建 Skill'} okText="保存" cancelText="取消" onOk={() => void save()} onCancel={() => setCreating(false)}>
      <div className={styles.form}><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="名称，例如：论文对比矩阵" /><Input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="用途说明" /><Input.TextArea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="提示词模板：告诉助手要完成什么" autoSize={{ minRows: 5, maxRows: 10 }} /><Input value={permissions} onChange={(event) => setPermissions(event.target.value)} placeholder="权限，逗号分隔，例如 read_project_papers, write_project_note" /><Select value={triggerMode} onChange={setTriggerMode} options={[{ label: '手动或建议触发', value: 'manual_or_suggest' }, { label: '仅手动触发', value: 'manual' }]} /></div>
    </Modal>
  </div>;
}

export default SkillsPage;
