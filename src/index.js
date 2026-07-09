const REPO = 'mywu-cloud/flights';
const SUBS_PATH = 'config/subscriptions.json';
const GITHUB_API = 'https://api.github.com/repos/' + REPO + '/contents/' + SUBS_PATH;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, PUT, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Api-Key, Authorization, X-Admin-Token',
};

const IATA_RE = /^[A-Z]{3}$/;
const MAX_SUBS = 20;
const SESSION_TTL = 60 * 60 * 24 * 30;
const RESET_TTL = 60 * 60; // 1 小時

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });
}

async function ghGet(token) {
  const headers = { 'User-Agent': 'flights-worker' };
  if (token) headers['Authorization'] = 'token ' + token;
  const r = await fetch(GITHUB_API, { headers });
  if (!r.ok) {
    const e = await r.json();
    throw new Error('GitHub GET ' + r.status + ': ' + (e.message || JSON.stringify(e)));
  }
  const meta = await r.json();
  const content = JSON.parse(atob(meta.content.replace(/\n/g, '')));
  return { content, sha: meta.sha };
}

function bufToHex(buf) {
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}
function hexToBuf(hex) {
  const arr = new Uint8Array(hex.length / 2);
  for (let i = 0; i < arr.length; i++) arr[i] = parseInt(hex.substr(i * 2, 2), 16);
  return arr.buffer;
}
function randomHex(len) {
  const arr = new Uint8Array(len);
  crypto.getRandomValues(arr);
  return bufToHex(arr.buffer);
}
async function pbkdf2Hash(password, saltHex) {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  const salt = hexToBuf(saltHex);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt, iterations: 100000, hash: 'SHA-256' },
    keyMaterial,
    256
  );
  return bufToHex(bits);
}
async function hashPassword(password) {
  const salt = randomHex(16);
  const hash = await pbkdf2Hash(password, salt);
  return { salt, hash };
}
async function verifyPassword(password, salt, hash) {
  const computed = await pbkdf2Hash(password, salt);
  return computed === hash;
}
function genToken() {
  return randomHex(32);
}

async function getUser(env, username) {
  const raw = await env.FARERADAR_KV.get('user:' + username);
  return raw ? JSON.parse(raw) : null;
}
async function saveUser(env, username, record) {
  await env.FARERADAR_KV.put('user:' + username, JSON.stringify(record));
}
async function createSession(env, username) {
  const token = genToken();
  await env.FARERADAR_KV.put('session:' + token, JSON.stringify({ username }), { expirationTtl: SESSION_TTL });
  return token;
}
async function getSessionUser(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const m = auth.match(/^Bearer\s+(.+)$/i);
  if (!m) return null;
  const raw = await env.FARERADAR_KV.get('session:' + m[1]);
  if (!raw) return null;
  return JSON.parse(raw).username;
}
async function deleteSession(request, env) {
  const auth = request.headers.get('Authorization') || '';
  const m = auth.match(/^Bearer\s+(.+)$/i);
  if (!m) return;
  await env.FARERADAR_KV.delete('session:' + m[1]);
}
async function getUserSubs(env, username) {
  const raw = await env.FARERADAR_KV.get('subs:' + username);
  return raw ? JSON.parse(raw) : [];
}
async function saveUserSubs(env, username, subscriptions) {
  await env.FARERADAR_KV.put('subs:' + username, JSON.stringify(subscriptions));
}
function validUsername(u) {
  return typeof u === 'string' && /^[a-zA-Z0-9_]{3,20}$/.test(u);
}

function validEmail(e) {
  return typeof e === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
}

async function getUserByEmail(env, email) {
  const list = await env.FARERADAR_KV.list({ prefix: 'user:' });
  for (const k of list.keys) {
    const raw = await env.FARERADAR_KV.get(k.name);
    if (raw) {
      const u = JSON.parse(raw);
      if (u.email === email) return u;
    }
  }
  return null;
}
async function createResetToken(env, username) {
  const token = genToken();
  await env.FARERADAR_KV.put('reset:' + token, JSON.stringify({ username }), { expirationTtl: RESET_TTL });
  return token;
}
async function getResetUsername(env, token) {
  const raw = await env.FARERADAR_KV.get('reset:' + token);
  if (!raw) return null;
  return JSON.parse(raw).username;
}
async function deleteResetToken(env, token) {
  await env.FARERADAR_KV.delete('reset:' + token);
}
async function sendResetEmail(env, toEmail, resetLink) {
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + env.RESEND_API,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      from: env.RESET_EMAIL_FROM || 'FareRadar <onboarding@resend.dev>',
      to: [toEmail],
      subject: '重設您的 FareRadar 密碼',
      html: '<p>您好，</p><p>請點擊以下連結重設密碼（1 小時內有效）：</p><p><a href="' + resetLink + '">' + resetLink + '</a></p><p>如果您沒有要求重設密碼，請忽略此信件。</p>',
    }),
  });
  if (!r.ok) {
    const e = await r.text();
    throw new Error('Resend API error: ' + r.status + ' ' + e);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    if (url.pathname === '/api/register' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { password, email } = body;
        if (!validEmail(email)) {
          return json({ error: '請輸入有效的 Email 地址' }, 400);
        }
        const username = String(email).trim();
        if (typeof password !== 'string' || password.length < 6) {
          return json({ error: '密碼至少需要 6 個字元' }, 400);
        }
        const existing = await getUser(env, username);
        if (existing) {
          return json({ error: '此 Email 已被註冊' }, 409);
        }
        const { salt, hash } = await hashPassword(password);
        await saveUser(env, username, { username, salt, hash, email, createdAt: Date.now() });

        try {
          const list = await env.FARERADAR_KV.list({ prefix: 'user:' });
          if (list.keys.length === 1 && env.GH_TOKEN) {
            const { content } = await ghGet(env.GH_TOKEN);
            if (content && Array.isArray(content.subscriptions)) {
              await saveUserSubs(env, username, content.subscriptions);
            }
          }
        } catch (e) {
          // migration is best-effort, ignore failures
        }

        const sessionToken = await createSession(env, username);
        return json({ ok: true, token: sessionToken, username });
      } catch (e) {
        return json({ error: e.message }, 500);
      }
    }

    if (url.pathname === '/api/login' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { username, password } = body;
        const user = await getUser(env, username);
        if (!user) return json({ error: '帳號或密碼錯誤' }, 401);
        const ok = await verifyPassword(password, user.salt, user.hash);
        if (!ok) return json({ error: '帳號或密碼錯誤' }, 401);
        const sessionToken = await createSession(env, username);
        return json({ ok: true, token: sessionToken, username });
      } catch (e) {
        return json({ error: e.message }, 500);
      }
    }

    if (url.pathname === '/api/forgot-password' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { email } = body;
        if (!validEmail(email)) {
          return json({ error: '請輸入有效的 Email 地址' }, 400);
        }
        const user = await getUserByEmail(env, email);
        if (user) {
          const token = await createResetToken(env, user.username);
          const resetLink = (env.FRONTEND_URL || 'https://mywu-cloud.github.io/flights/') + '?resetToken=' + token;
          try {
            await sendResetEmail(env, email, resetLink);
          } catch (e) {
            // 寄信失敗不對外洩漏細節，避免探測帳號是否存在
          }
        }
        return json({ ok: true, message: '如果該 Email 已註冊，重設密碼連結已寄出' });
      } catch (e) {
        return json({ error: e.message }, 500);
      }
    }

    if (url.pathname === '/api/reset-password' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { token, password } = body;
        if (typeof password !== 'string' || password.length < 6) {
          return json({ error: '密碼至少需要 6 個字元' }, 400);
        }
        const username = await getResetUsername(env, token);
        if (!username) {
          return json({ error: '重設連結無效或已過期' }, 400);
        }
        const user = await getUser(env, username);
        if (!user) {
          return json({ error: '使用者不存在' }, 404);
        }
        const { salt, hash } = await hashPassword(password);
        user.salt = salt;
        user.hash = hash;
        await saveUser(env, username, user);
        await deleteResetToken(env, token);
        return json({ ok: true });
      } catch (e) {
        return json({ error: e.message }, 500);
      }
    }

    if (url.pathname === '/api/logout' && request.method === 'POST') {
      await deleteSession(request, env);
      return json({ ok: true });
    }

    if (url.pathname === '/api/me' && request.method === 'GET') {
      const username = await getSessionUser(request, env);
      if (!username) return json({ error: 'Unauthorized' }, 401);
      const user = await getUser(env, username);
      return json({ username, email: (user && user.email) || '' });
    }

    if (url.pathname === '/api/admin/all-subscriptions' && request.method === 'GET') {
      const adminToken = request.headers.get('X-Admin-Token');
      if (!env.ADMIN_TOKEN || adminToken !== env.ADMIN_TOKEN) {
        return json({ error: 'Unauthorized' }, 401);
      }
      try {
        const list = await env.FARERADAR_KV.list({ prefix: 'subs:' });
        let all = [];
        for (const k of list.keys) {
          const raw = await env.FARERADAR_KV.get(k.name);
          if (raw) {
            const arr = JSON.parse(raw);
            if (Array.isArray(arr)) all = all.concat(arr);
          }
        }
        return json({ subscriptions: all });
      } catch (e) {
        return json({ error: e.message }, 500);
      }
    }

    if (url.pathname === '/subscriptions' && request.method === 'GET') {
      const username = await getSessionUser(request, env);
      if (!username) return json({ error: 'Unauthorized' }, 401);
      try {
        const subscriptions = await getUserSubs(env, username);
        return json({ subscriptions });
      } catch (e) {
        return json({ error: e.message }, 502);
      }
    }

    if (url.pathname === '/subscriptions' && request.method === 'PUT') {
      const username = await getSessionUser(request, env);
      if (!username) return json({ error: 'Unauthorized' }, 401);
      try {
        const body = await request.json();
        const { subscriptions } = body;

        if (!Array.isArray(subscriptions)) {
          return json({ error: 'subscriptions must be array' }, 400);
        }
        if (subscriptions.length > MAX_SUBS) {
          return json({ error: 'Too many subscriptions (max ' + MAX_SUBS + ')' }, 400);
        }
        for (const s of subscriptions) {
          if (!IATA_RE.test(s.origin) || !IATA_RE.test(s.destination)) {
            return json({ error: 'Invalid IATA code: ' + s.origin + '/' + s.destination }, 400);
          }
          if (typeof s.target_price !== 'number' || s.target_price < 0 || s.target_price > 500000) {
            return json({ error: 'Invalid target_price for ' + s.id }, 400);
          }
        }

        await saveUserSubs(env, username, subscriptions);
        return json({ ok: true });
      } catch (e) {
        return json({ error: e.message }, 502);
      }
    }

    return json({ error: 'Not found' }, 404);
  },
};
