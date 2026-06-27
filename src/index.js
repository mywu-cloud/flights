const REPO = 'mywu-cloud/flights';
const SUBS_PATH = 'config/subscriptions.json';
const GITHUB_API = 'https://api.github.com/repos/' + REPO + '/contents/' + SUBS_PATH;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, PUT, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

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

async function ghPut(token, content, sha) {
  const body = JSON.stringify(content, null, 2);
  const encoded = btoa(unescape(encodeURIComponent(body)));
  const r = await fetch(GITHUB_API, {
    method: 'PUT',
    headers: {
      Authorization: 'token ' + token,
      'Content-Type': 'application/json',
      'User-Agent': 'flights-worker',
    },
    body: JSON.stringify({
      message: 'feat: update subscriptions via Worker API',
      content: encoded,
      sha,
    }),
  });
  const resBody = await r.json();
  if (!r.ok) {
    throw new Error('GitHub PUT ' + r.status + ': ' + (resBody.message || JSON.stringify(resBody)));
  }
  return resBody.content.sha;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    const token = env.GH_TOKEN;
    if (!token) return json({ error: 'GH_TOKEN not configured' }, 500);

    // GET /subscriptions
    if (url.pathname === '/subscriptions' && request.method === 'GET') {
      try {
        const { content, sha } = await ghGet(token);
        return json({ ...content, sha });
      } catch (e) {
        return json({ error: e.message }, 502);
      }
    }

    // PUT /subscriptions
    if (url.pathname === '/subscriptions' && request.method === 'PUT') {
      try {
        const body = await request.json();
        const { subscriptions, sha } = body;
        if (!Array.isArray(subscriptions)) return json({ error: 'subscriptions must be array' }, 400);
        if (!sha) return json({ error: 'sha is required' }, 400);
        const newSha = await ghPut(token, { subscriptions }, sha);
        return json({ ok: true, sha: newSha });
      } catch (e) {
        return json({ error: e.message }, 502);
      }
    }

    // GET /debug — check token scope
    if (url.pathname === '/debug' && request.method === 'GET') {
      const r = await fetch('https://api.github.com/user', {
        headers: { Authorization: 'token ' + token, 'User-Agent': 'flights-worker' },
      });
      const d = await r.json();
      const scopes = r.headers.get('x-oauth-scopes') || 'N/A';
      return json({ status: r.status, login: d.login, scopes, token_prefix: token.substring(0, 12) });
    }

    return json({ error: 'Not found' }, 404);
  },
};
