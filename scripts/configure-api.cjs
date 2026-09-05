/* Optional platform-wide LLM API setup for an administrator/developer.
 *
 * Normal users should use the authenticated API Settings page instead. This
 * script asks for BASE_URL / MODEL / API_KEY and writes a shared fallback to
 * paper-claw-master/.env only when explicitly invoked.
 * Usage:
 *   node scripts/configure-api.cjs [envPath]
 *   node scripts/configure-api.cjs [envPath] --base URL --model MODEL --api-key KEY
 */
const readline = require('readline/promises');
const fs = require('fs');
const path = require('path');
const { stdin: input, stdout: output } = process;

const envPath = process.argv[2]
  || path.join(__dirname, '..', 'paper-claw-master', '.env');

function argValue(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] || '' : '';
}

function readEnv(file) {
  try { return fs.readFileSync(file, 'utf8'); } catch { return ''; }
}

function writeEnv(file, content) {
  fs.writeFileSync(file, content, 'utf8');
}

function upsertEnv(content, key, value) {
  const pattern = new RegExp(`^${key}=.*$`, 'm');
  const line = `${key}=${value}`;
  return pattern.test(content) ? content.replace(pattern, line) : `${content.replace(/\s*$/, '')}\n${line}\n`;
}

async function askQuestion(rl, text, fallback) {
  const answer = (await rl.question(text)).trim();
  return answer || fallback || '';
}

async function main() {
  const flagBase = argValue('--base');
  const flagModel = argValue('--model');
  const flagKey = argValue('--api-key');
  const automatic = Boolean(flagBase && flagModel && flagKey);

  let content = readEnv(envPath);

  let baseUrl = flagBase || '';
  let model = flagModel || '';
  let apiKey = flagKey || '';

  if (!automatic) {
    const rl = readline.createInterface({ input, output });
    try {
      console.log('==> Configure API');
      baseUrl = await askQuestion(rl, 'Base URL: ');
      model = await askQuestion(rl, 'Model: ');
      apiKey = await askQuestion(rl, 'API Key: ');
    } finally {
      rl.close();
    }
  }

  if (!baseUrl || !model || !apiKey) {
    throw new Error('BASE_URL, MODEL and API_KEY are all required.');
  }

  content = upsertEnv(content, 'PAPER_CLAW_CHAT_BASE_URL', baseUrl);
  content = upsertEnv(content, 'PAPER_CLAW_CHAT_MODEL', model);
  content = upsertEnv(content, 'PAPER_CLAW_CHAT_API_KEY', apiKey);
  writeEnv(envPath, content);
  console.log(`[OK] Saved to ${envPath}`);
  console.log('Restart the A-side backend (or rerun the launcher) so the new values take effect.');
}

main().catch((error) => {
  console.error(`[ERROR] ${error && error.message ? error.message : error}`);
  process.exit(1);
});
