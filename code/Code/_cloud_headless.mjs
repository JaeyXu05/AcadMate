/* Headless Edge (CDP) smoke test: login → open /cloud → capture console errors + screenshot.
   Uses Node built-in WebSocket + fetch to talk to Edge's DevTools (no deps). */
import { execFileSync, spawn } from 'child_process';
import { mkdtempSync, writeFileSync, readFileSync } from 'fs';
import { tmpdir } from 'os';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const VITE = 'http://localhost:5173';
const API = 'http://localhost:3001/api';

// 1) Obtain a token via login API (auto-register)
const loginRes = await fetch(`${API}/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'cloud.debug@example.com', password: 'cloudpass123' }),
});
const { token } = await loginRes.json();
if (!token) { console.error('LOGIN FAILED'); process.exit(2); }
console.log('got token', token.slice(0, 12) + '…');

// 2) Launch Edge headless with remote debugging
const userData = mkdtempSync(tmpdir() + '/edge-cdp-');
const profile = mkdtempSync(tmpdir() + '/edge-prof-');
const port = 9223;
const proc = spawn(EDGE, [
  '--headless=new',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${userData}`,
  '--no-first-run', '--no-default-browser-check', '--window-size=1400,900',
  '--disable-gpu', '--use-gl=swiftshader', '--enable-unsafe-swiftshader', 'about:blank',
], { stdio: 'ignore', detached: true });
proc.unref();

// wait for CDP
let tab;
for (let i = 0; i < 40; i++) {
  await new Promise(r => setTimeout(r, 250));
  try {
    const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
    const page = list.find(t => t.type === 'page');
    if (page) { tab = page; break; }
  } catch {}
}
if (!tab) { console.error('CDP: no page target'); process.exit(3); }
console.log('cdp ws', tab.webSocketDebuggerUrl.slice(0, 40) + '…');

const ws = new WebSocket(tab.webSocketDebuggerUrl);
let msgId = 0;
const pending = new Map();
const consoleErrors = [];
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) {
    const txt = (m.params.args || []).map(a => a.value ?? a.description ?? '').join(' ');
    consoleErrors.push(`[${m.params.type}] ${txt}`);
  }
  if (m.method === 'Runtime.exceptionThrown' && m.params.exceptionDetails) {
    const ex = m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text || '';
    consoleErrors.push(`[exception] ${ex}`);
  }
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
};
await new Promise((res) => (ws.onopen = res));
const send = (method, params = {}) => new Promise((r) => {
  const id = ++msgId; pending.set(id, r); ws.send(JSON.stringify({ id, method, params }));
});

await send('Page.enable');
await send('Runtime.enable');

// 3) Seed localStorage token, then navigate
await send('Page.navigate', { url: VITE + '/welcome' });
await new Promise(r => setTimeout(r, 1500));
await send('Runtime.evaluate', { expression: `localStorage.setItem('token', ${JSON.stringify(token)}); 1` });

await send('Page.navigate', { url: VITE + '/cloud' });
await send('Page.reload', {});
// give React + Three time to render
await new Promise(r => setTimeout(r, 4500));

// screenshot
try {
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync('./cloud_a.png', Buffer.from(shot.result.data, 'base64'));
  console.log('screenshot written ./cloud_a.png');
} catch (e) { console.log('screenshot failed:', e.message); }

// grab some DOM telemetry: canvas present, star count impossible from DOM; check hint text
const dom = await send('Runtime.evaluate', {
  expression: `JSON.stringify({
    hasCanvas: !!document.querySelector('canvas'),
    bodyText: (document.body.innerText||'').slice(0,200)
  })`,
  returnByValue: true,
});
console.log('DOM:', dom.result.result.value);

console.log('\n=== CONSOLE ERRORS / EXCEPTIONS ===');
if (consoleErrors.length === 0) console.log('(none)');
else consoleErrors.forEach(e => console.log(e));

ws.close();
process.exit(0);