#!/usr/bin/env node
// 从 Edge 调试实例（CDP）导出 x.com 登录 cookie 头，写入 <XDL_ROOT>/raw_cookie.txt
// 用法：先开着带 --remote-debugging-port 的 Edge 并登录 x.com，再
//   set XDL_ROOT=D:\tmp\xdl-xxx && node edge_dump_cookie.mjs
// 端口默认 9335，可用 env X_EDGE_PORT 覆盖。
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const ROOT = process.env.XDL_ROOT || 'D:\\tmp\\xdl';
const PORT = process.env.X_EDGE_PORT || '9335';

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && /^https?:/.test(t.url));
const target = pages.find(p => p.url.includes('x.com')) || pages[0];
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const r = await send('Network.getCookies', { urls: ['https://x.com/'] });
const keep = new Set(['auth_token', 'ct0', 'twid', 'kdt', 'guest_id', 'guest_id_marketing', 'guest_id_ads', 'personalization_id', 'gt', 'lang']);
const cookies = (r.result && r.result.cookies || []).filter(c => keep.has(c.name));
const byName = new Map();
for (const c of cookies) { if (!byName.has(c.name) || c.path === '/') byName.set(c.name, c); }
const header = [...byName.values()].map(c => `${c.name}=${c.value}`).join('; ');
const out = `${ROOT}\\raw_cookie.txt`;
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, header, 'utf8');
console.log(JSON.stringify({ written: out, names: [...byName.keys()], len: header.length }));
ws.close();
