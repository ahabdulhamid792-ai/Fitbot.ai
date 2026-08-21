'use strict';
// ════════════════════════════════════════════════════════════════
// FITBOT BACKEND — v3
// AI Priority: Cerebras → Groq → OpenRouter → Gemini → Cache
// Video: Pexels stock clips + ffmpeg assembly (free, unlimited)
// ════════════════════════════════════════════════════════════════

require('dotenv').config();

const http   = require('http');
const https  = require('https');
const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');

// ── ENV VALIDATION ────────────────────────────────────────────
(function validateEnv() {
  const required = ['DASHBOARD_PASSWORD_HASH', 'SESSION_SECRET'];
  const missing  = required.filter(k => !process.env[k]);
  if (missing.length) {
    missing.forEach(k => console.error(`[FATAL] Missing .env: ${k}`));
    process.exit(1);
  }
  if (process.env.SESSION_SECRET.length < 32) {
    console.error('[FATAL] SESSION_SECRET must be at least 32 characters');
    process.exit(1);
  }
  // AI keys — all optional, pipeline falls back to script cache
  const AI_KEYS = {
    'CEREBRAS_API_KEY' : 'cloud.cerebras.ai  — 1,000,000 tokens/day FREE ← BEST',
    'GROQ_API_KEY'     : 'console.groq.com   — 14,400 req/day FREE',
    'OPENROUTER_API_KEY': 'openrouter.ai      — 200 req/day FREE',
    'GEMINI_API_KEY'   : 'aistudio.google.com — 1,500 req/day FREE',
  };
  const found = Object.keys(AI_KEYS).filter(k => process.env[k]);
  if (!found.length) {
    console.warn('[WARN] No AI key set — using pre-written script cache');
    console.warn('[BEST] Add CEREBRAS_API_KEY from cloud.cerebras.ai (email only, no card)');
    Object.entries(AI_KEYS).forEach(([k, v]) => console.warn(`       ${k}: ${v}`));
  } else {
    console.log(`[INFO] AI providers ready: ${found.join(', ')}`);
  }
})();

const PORT     = parseInt(process.env.PORT) || 3000;
const PWD_HASH = process.env.DASHBOARD_PASSWORD_HASH;

// ── AI Provider keys ──────────────────────────────────────────
const AI = {
  cerebras  : { key: process.env.CEREBRAS_API_KEY   || '', host: 'api.cerebras.ai',    path: '/v1/chat/completions',            models: ['llama-3.3-70b','llama3.1-70b','llama3.1-8b'] },
  groq      : { key: process.env.GROQ_API_KEY        || '', host: 'api.groq.com',       path: '/openai/v1/chat/completions',     models: ['llama-3.3-70b-versatile','llama3-70b-8192','llama-3.1-8b-instant'] },
  openrouter: { key: process.env.OPENROUTER_API_KEY  || '', host: 'openrouter.ai',      path: '/api/v1/chat/completions',        models: ['meta-llama/llama-3.3-70b-instruct:free','deepseek/deepseek-chat:free'] },
};

// ── LOGGING ───────────────────────────────────────────────────
const log = (msg, level = 'INFO') => {
  const safe = String(msg).replace(/[\r\n]/g, ' ').slice(0, 500);
  console.log(`[${new Date().toISOString()}] [${level}] ${safe}`);
};

// ════════════════════════════════════════════════════════════════
// SESSION STORE
// ════════════════════════════════════════════════════════════════
const sessions = new Map();

function generateToken() { return crypto.randomBytes(32).toString('hex'); }

function createSession(email) {
  const token = generateToken(), csrfToken = generateToken();
  sessions.set(token, { email, csrfToken, createdAt: Date.now(), trends: [], queue: [] });
  return { token, csrfToken };
}

function validateSession(sessionToken, csrfToken) {
  if (!sessionToken || !csrfToken) return null;
  const s = sessions.get(sessionToken);
  if (!s || s.csrfToken !== csrfToken) return null;
  if (Date.now() - s.createdAt > 86400000) { sessions.delete(sessionToken); return null; }
  return s;
}

setInterval(() => {
  const cutoff = Date.now() - 86400000;
  for (const [t, s] of sessions) if (s.createdAt < cutoff) sessions.delete(t);
}, 1800000);

// ── RATE LIMITING ─────────────────────────────────────────────
const loginAttempts = new Map();
function checkRateLimit(ip) {
  const e = loginAttempts.get(ip) || { count: 0, lockedUntil: 0 };
  if (Date.now() < e.lockedUntil) return { blocked: true, secs: Math.ceil((e.lockedUntil - Date.now()) / 1000) };
  return { blocked: false };
}
function recordFail(ip) {
  const e = loginAttempts.get(ip) || { count: 0, lockedUntil: 0 };
  e.count++;
  if (e.count >= 5) { e.lockedUntil = Date.now() + 60000; e.count = 0; }
  loginAttempts.set(ip, e);
}
function resetFails(ip) { loginAttempts.delete(ip); }

// ── HELPERS ───────────────────────────────────────────────────
const ALLOWED_SOURCES = new Set(['YouTube', 'TikTok', 'Google Trends', 'Social Blade']);

function sanitize(str, max = 200) {
  return (typeof str === 'string' ? str : '')
    .replace(/[<>"'`\n\r\\/]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
}

function readBody(req, maxBytes = 50 * 1024) {
  return new Promise((resolve, reject) => {
    let data = '', size = 0;
    req.on('data', c => {
      if ((size += c.length) > maxBytes) { req.destroy(); reject(new Error('Body too large')); return; }
      data += c;
    });
    req.on('end', () => { try { resolve(JSON.parse(data)); } catch { reject(new Error('Invalid JSON')); } });
    req.on('error', reject);
  });
}

function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'X-Content-Type-Options': 'nosniff' });
  res.end(JSON.stringify(data));
}
function sendHTML(res, status, html) {
  res.writeHead(status, { 'Content-Type': 'text/html; charset=utf-8', 'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff' });
  res.end(html);
}
function requireAuth(req, res) {
  const tok  = (req.headers.authorization || '').replace('Bearer ', '').trim();
  const csrf = req.headers['x-csrf-token'] || '';
  const s    = validateSession(tok, csrf);
  if (!s) { sendJSON(res, 401, { error: 'Unauthorized' }); return null; }
  return s;
}

// ════════════════════════════════════════════════════════════════
// AI SCRIPT GENERATION
// Priority: Cerebras (1M tokens/day) → Groq → OpenRouter → Cache
// ════════════════════════════════════════════════════════════════

function callProvider(provider, prompt) {
  return new Promise((resolve, reject) => {
    const p    = AI[provider];
    const model = p.models[0];
    const body  = JSON.stringify({
      model,
      messages: [
        { role: 'system', content: 'You are a fitness YouTube content expert. Return valid JSON only. No markdown.' },
        { role: 'user',   content: prompt },
      ],
      temperature: 0.7,
      max_tokens : 600,
      response_format: { type: 'json_object' },
    });

    const headers = {
      'Content-Type'  : 'application/json',
      'Authorization' : `Bearer ${p.key}`,
      'Content-Length': Buffer.byteLength(body),
    };
    if (provider === 'openrouter') {
      headers['HTTP-Referer'] = 'https://github.com/fitbot-ai';
      headers['X-Title']      = 'FitBot AI';
    }

    const req = https.request({
      hostname: p.host,
      path    : p.path,
      method  : 'POST',
      headers,
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          if (res.statusCode === 429) { reject(new Error('RATE_LIMIT')); return; }
          if (res.statusCode === 401 || res.statusCode === 403) { reject(new Error('INVALID_KEY')); return; }
          if (res.statusCode !== 200) { reject(new Error(`HTTP_${res.statusCode}`)); return; }
          const json = JSON.parse(data);
          const text = json.choices?.[0]?.message?.content;
          if (!text) { reject(new Error('Empty response')); return; }
          resolve(JSON.parse(text.replace(/```json|```/g, '').trim()));
        } catch(e) { reject(e); }
      });
    });
    req.setTimeout(20000, () => { req.destroy(); reject(new Error('TIMEOUT')); });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// Script cache — 7 pre-written scripts rotated by day of week
const SCRIPT_CACHE = [
  { hook: 'Stop wasting time on exercises that barely work.',           body: 'These 7 moves activate more muscle fibres in less time. Add them today and feel the difference in one week. No expensive equipment needed.', cta: 'Start today.', caption: 'Transform your workout in one week 💪', hashtags: ['#fitness', '#workout', '#gym', '#gains', '#fitnessmotivation', '#training', '#bodybuilding', '#muscles'] },
  { hook: 'You are training hard but the fat is not moving.',           body: 'The problem is not your workout — it is your recovery and sleep. Fix these first and watch everything change completely.', cta: 'Change your routine now.', caption: 'The secret to fat loss nobody talks about 🔥', hashtags: ['#weightloss', '#fatburning', '#diet', '#fitnessjourney', '#transformation', '#healthylifestyle', '#fitnessgains', '#beforeandafter'] },
  { hook: 'No time to train? Seven minutes is all you need.',           body: 'This circuit hits every major muscle group fast. No equipment, no gym, no excuses. Just 7 minutes and real results start showing.', cta: 'Try the 7-minute challenge.', caption: 'Maximum results in minimum time ⏱️', hashtags: ['#quickworkout', '#fitnesshacks', '#homeworkout', '#nomEquipment', '#busylifestyle', '#fitnessmotivation', '#gains', '#timemanagement'] },
  { hook: 'Sore muscles are slowing your progress every single day.',   body: 'These 5 recovery moves reduce soreness significantly. Do them after every session and train harder the very next day without pain.', cta: 'Recover like a pro.', caption: 'Stop being sore and train harder 💪🔥', hashtags: ['#recovery', '#stretching', '#musclesoreness', '#fitnesshealth', '#flexibility', '#yoga', '#trainingrecovery', '#fitnesscommunity'] },
  { hook: 'Steady state cardio is the slowest way to burn fat.',        body: 'Switch to this interval method and burn three times more calories in half the time. Your body composition will change faster than ever.', cta: 'Burn fat efficiently.', caption: 'Forget long cardio sessions — do THIS instead 🔥', hashtags: ['#cardio', '#HIIT', '#fatburning', '#cardioworkout', '#fitness', '#abs', '#fitnesshacks', '#fastresults'] },
  { hook: 'Most people train legs wrong and never know it.',            body: 'They focus only on squats and miss three key muscle groups completely. Fix this technique today and your legs will grow bigger and stronger fast.', cta: 'Build powerful legs.', caption: 'The leg training secret that changes everything 🦵', hashtags: ['#legday', '#legworkout', '#quads', '#squats', '#legmuscles', '#fitnesstraining', '#bodybuilding', '#gains'] },
  { hook: 'Bad posture makes you look weaker and feel worse every day.',body: 'These three exercises correct years of desk damage in just 10 minutes a day. Start tonight and feel taller and stronger immediately.', cta: 'Fix your posture.', caption: 'Stand taller and feel stronger 💪', hashtags: ['#posture', '#backpain', '#flexibility', '#stretching', '#health', '#fitnesshacks', '#wellness', '#musclerecovery'] },
];

function getCachedScript(topic) {
  const s = SCRIPT_CACHE[new Date().getDay()];
  return {
    hook    : s.hook,
    body    : topic ? `About "${topic}" — ` + s.body : s.body,
    cta     : s.cta,
    caption : (topic ? topic + ' 💪🔥 ' : '') + s.caption,
    hashtags: s.hashtags,
  };
}

async function generateScript(topic, source) {
  const safeTopic  = sanitize(topic, 80);
  const safeSource = ALLOWED_SOURCES.has(source) ? source : 'fitness platform';

  const prompt = (
    `Fitness YouTube content for "Mhed Fitness & Sports".\n` +
    `Topic from ${safeSource}: "${safeTopic}"\n` +
    `Return JSON: {"hook":"opening line max 100 chars","body":"3-4 sentences max 220 chars","cta":"call to action max 80 chars","caption":"caption with emojis max 400 chars","hashtags":["#tag1","#tag2"...]}`
  );

  // Try providers in priority order
  const providers = [
    { name: 'Cerebras',   key: 'cerebras',   id: 'cerebras'   },
    { name: 'Groq',       key: 'groq',       id: 'groq'       },
    { name: 'OpenRouter', key: 'openrouter', id: 'openrouter' },
  ];

  for (const p of providers) {
    if (!AI[p.id].key) {
      log(`${p.name}: no key set — skipping`);
      continue;
    }
    try {
      log(`Trying ${p.name} for topic: ${safeTopic}`);
      const data = await callProvider(p.id, prompt);
      if (data?.hook) {
        log(`${p.name} succeeded`);
        return data;
      }
    } catch(e) {
      if (e.message === 'INVALID_KEY') {
        log(`${p.name}: invalid API key`, 'ERROR');
        continue;
      }
      if (e.message === 'RATE_LIMIT') {
        log(`${p.name}: rate limited — trying next`, 'WARN');
        continue;
      }
      log(`${p.name}: ${e.message}`, 'WARN');
    }
  }

  // Gemini fallback (different SDK format)
  if (process.env.GEMINI_API_KEY) {
    try {
      log('Trying Gemini fallback...');
      const data = await callGemini(prompt);
      if (data?.hook) return data;
    } catch(e) {
      log(`Gemini: ${e.message}`, 'WARN');
    }
  }

  log('All AI providers failed — using script cache', 'WARN');
  return getCachedScript(safeTopic);
}

function callGemini(prompt) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { responseMimeType: 'application/json', maxOutputTokens: 600, temperature: 0.7 },
    });
    const req = https.request({
      hostname: 'generativelanguage.googleapis.com',
      path    : `/v1beta/models/gemini-2.0-flash:generateContent?key=${process.env.GEMINI_API_KEY}`,
      method  : 'POST',
      headers : { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.error) { reject(new Error(json.error.message)); return; }
          const text = json.candidates?.[0]?.content?.parts?.[0]?.text;
          resolve(JSON.parse(text.replace(/```json|```/g, '').trim()));
        } catch(e) { reject(e); }
      });
    });
    req.setTimeout(20000, () => { req.destroy(); reject(new Error('Gemini timeout')); });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ════════════════════════════════════════════════════════════════
// HTTP SERVER
// ════════════════════════════════════════════════════════════════
const server = http.createServer(async (req, res) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Referrer-Policy', 'no-referrer');

  const ip  = req.socket.remoteAddress || 'unknown';
  const url = req.url.split('?')[0];

  // Serve frontend
  if (req.method === 'GET' && (url === '/' || url === '/index.html')) {
    try {
      const indexPath = path.join(__dirname, '..', 'index.html');
      log(`[DEBUG] Serving index.html from: ${indexPath}`);
      const html = fs.readFileSync(indexPath, 'utf8');
      sendHTML(res, 200, html);
    } catch(e) { 
      log(`[ERROR] Failed to serve app: ${e.message}`, 'ERROR');
      sendJSON(res, 500, { error: `Could not serve app: ${e.message}` }); 
    }
    return;
  }

  // Config
  if (req.method === 'GET' && url === '/api/config') {
    sendJSON(res, 200, {
      hasCerebras  : !!AI.cerebras.key,
      hasGroq      : !!AI.groq.key,
      hasOpenRouter: !!AI.openrouter.key,
      hasGemini    : !!process.env.GEMINI_API_KEY,
      hasPexels    : !!process.env.PEXELS_API_KEY,
      hasCloudinary: !!process.env.CLOUDINARY_URL,
      hasBuffer    : !!process.env.BUFFER_API_KEY,
      videoMethod  : 'Pexels stock clips + ffmpeg assembly (free, unlimited)',
    });
    return;
  }

  // Login
  if (req.method === 'POST' && url === '/auth/login') {
    const { blocked, secs } = checkRateLimit(ip);
    if (blocked) { sendJSON(res, 429, { message: `Too many attempts. Wait ${secs}s.` }); return; }
    try {
      const { email, password } = await readBody(req);
      if (typeof email !== 'string' || typeof password !== 'string') throw new Error('Invalid');
      const hash = crypto.createHash('sha256').update(password).digest('hex');
      if (hash !== PWD_HASH) {
        recordFail(ip);
        sendJSON(res, 401, { message: 'Invalid credentials' });
        log(`Failed login: ${sanitize(email, 100)}`, 'WARN');
        return;
      }
      resetFails(ip);
      const { token, csrfToken } = createSession(sanitize(email, 200));
      sendJSON(res, 200, { token, csrfToken });
      log(`Login OK: ${sanitize(email, 100)}`);
    } catch { sendJSON(res, 400, { error: 'Bad request' }); }
    return;
  }

  // User data
  if (req.method === 'GET' && url === '/api/user-data') {
    const s = requireAuth(req, res);
    if (!s) return;
    sendJSON(res, 200, { trends: s.trends, scripts: [], queue: s.queue, posted: 0 });
    return;
  }

  // Add trend
  if (req.method === 'POST' && url === '/api/trends') {
    const s = requireAuth(req, res);
    if (!s) return;
    try {
      const { topic, source, notes } = await readBody(req);
      if (!topic?.trim()) throw new Error('Topic required');
      if (!ALLOWED_SOURCES.has(source)) throw new Error('Invalid source');
      const trend = {
        id    : crypto.randomUUID(),
        topic : sanitize(topic, 80),
        source,
        notes : sanitize(notes || '', 200),
        date  : new Date().toISOString(),
      };
      s.trends.push(trend);
      sendJSON(res, 200, trend);
      log(`Trend added: ${trend.topic}`);
    } catch(e) { sendJSON(res, 400, { error: e.message }); }
    return;
  }

  // Generate script
  if (req.method === 'POST' && url === '/api/generate-script') {
    const s = requireAuth(req, res);
    if (!s) return;
    try {
      const { trendId, source } = await readBody(req);
      const trend = s.trends.find(t => t.id === trendId);
      if (!trend) throw new Error('Trend not found');
      const script = await generateScript(trend.topic, source || trend.source);
      sendJSON(res, 200, {
        hook    : sanitize(script.hook    || '', 200),
        body    : sanitize(script.body    || '', 600),
        cta     : sanitize(script.cta     || '', 200),
        caption : sanitize(script.caption || '', 2200),
        hashtags: Array.isArray(script.hashtags)
          ? script.hashtags.filter(h => typeof h === 'string').slice(0, 10)
          : [],
      });
    } catch(e) {
      log(`Script error: ${e.message}`, 'ERROR');
      sendJSON(res, 500, { error: 'Script generation failed' });
    }
    return;
  }

  // Queue script
  if (req.method === 'POST' && url === '/api/queue') {
    const s = requireAuth(req, res);
    if (!s) return;
    try {
      const { script } = await readBody(req);
      if (!script?.hook) throw new Error('Invalid script');
      const item = {
        id      : crypto.randomUUID(),
        title   : sanitize(script.hook, 100),
        platform: 'All Platforms',
        status  : 'queued',
        date    : new Date().toISOString(),
      };
      s.queue.push(item);
      sendJSON(res, 200, item);
    } catch(e) { sendJSON(res, 400, { error: e.message }); }
    return;
  }

  // Delete queue item
  if (req.method === 'DELETE' && url.startsWith('/api/queue/')) {
    const s = requireAuth(req, res);
    if (!s) return;
    const rawId = url.split('/').pop();
    const idx   = s.queue.findIndex(q => q.id === rawId);
    if (idx === -1) { sendJSON(res, 404, { error: 'Not found' }); return; }
    s.queue.splice(idx, 1);
    sendJSON(res, 200, { success: true });
    return;
  }

  sendJSON(res, 404, { error: 'Not found' });
});

server.listen(PORT, () => {
  log(`FitBot Dashboard → http://localhost:${PORT}`);
  log(`Video method    : Pexels stock clips + ffmpeg assembly (free, unlimited)`);
  log(`AI primary      : ${AI.cerebras.key ? 'Cerebras 1M tokens/day ✓' : 'Not configured — add CEREBRAS_API_KEY'}`);
  log(`AI fallback 1   : ${AI.groq.key ? 'Groq 14,400 req/day ✓' : 'Not configured'}`);
  log(`AI fallback 2   : ${AI.openrouter.key ? 'OpenRouter 200 req/day ✓' : 'Not configured'}`);
  log(`AI fallback 3   : ${process.env.GEMINI_API_KEY ? 'Gemini 1,500 req/day ✓' : 'Not configured'}`);
});
