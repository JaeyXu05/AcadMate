import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const CODE_ROOT = path.resolve(__dirname, '..');
const ENV_PATH = path.join(CODE_ROOT, '.env');
const EXAMPLE_PATH = path.join(CODE_ROOT, '.env.example');

function ensureLocalEnvFile(): void {
  if (fs.existsSync(ENV_PATH)) return;
  let template = '';
  if (fs.existsSync(EXAMPLE_PATH)) {
    template = fs.readFileSync(EXAMPLE_PATH, 'utf8');
  }
  const secret = crypto.randomBytes(32).toString('hex');
  if (/^JWT_SECRET=/m.test(template)) {
    template = template.replace(/^JWT_SECRET=.*$/m, `JWT_SECRET=${secret}`);
  } else {
    template += `\nJWT_SECRET=${secret}\n`;
  }
  if (!/MENTOR_AGENT_BASE_URL=/.test(template)) {
    template += 'MENTOR_AGENT_BASE_URL=http://127.0.0.1:8000\n';
  }
  fs.writeFileSync(ENV_PATH, template, 'utf8');
}

ensureLocalEnvFile();
dotenv.config({ path: ENV_PATH, override: false });

const DANGEROUS_SECRETS = new Set([
  'dev-secret-change-me',
  'secret',
  'changeme',
  '',
  'your-secret-key',
]);

function persistEnvValue(key: string, value: string): void {
  let text = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, 'utf8') : '';
  const line = new RegExp(`^${key}=.*$`, 'm');
  if (line.test(text)) {
    text = text.replace(line, `${key}=${value}`);
  } else {
    text += `\n${key}=${value}\n`;
  }
  fs.writeFileSync(ENV_PATH, text, 'utf8');
}

const jwtSecret = String(process.env.JWT_SECRET || '').trim();
if (DANGEROUS_SECRETS.has(jwtSecret) || jwtSecret.length < 16) {
  const secret = crypto.randomBytes(32).toString('hex');
  process.env.JWT_SECRET = secret;
  persistEnvValue('JWT_SECRET', secret);
}
if (!String(process.env.MENTOR_AGENT_BASE_URL || '').trim()) {
  process.env.MENTOR_AGENT_BASE_URL = 'http://127.0.0.1:8000';
  persistEnvValue('MENTOR_AGENT_BASE_URL', process.env.MENTOR_AGENT_BASE_URL);
}
