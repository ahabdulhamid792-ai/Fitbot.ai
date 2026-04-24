'use strict';
// ════════════════════════════════════════════════════════════════
// FITBOT BACKEND
// Script generation : Google Gemini 2.0 Flash  (FREE — aistudio.google.com)
// Video generation  : WaveSpeed AI LTX-2.3     ($1 free credit — wavespeed.ai)
//                     Text → Video + Audio in one API call
// ════════════════════════════════════════════════════════════════

require('dotenv').config();

const http   = require('http');
const https  = require('https');
const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');

// ── ENV VALIDATION ────────────────────────────────────────────
(function validateEnv() {
  const required = ['GEMINI_API_KEY', 'DASHBOARD_PASSWORD_HASH', 'SESSION_SECRET'];
  const missing  = required.filter(k => !process.env[k]);
  if (missing.length) {
    missing.forEach(k => console.error(`[FATAL] Missing .env: ${k}`));
    process.exit(1);
  }
  if (process.env.SESSION_SECRET.length < 32) {
    console.error('[FATAL] SESSION_SECRET must be at least 32 characters'); process.exit(1);
  }
  // WaveSpeed key is optional — video tab is disabled if not set
  if (!process.env.WAVESPEED_API_KEY) {
    console.warn('[WARN] WAVESPEED_API_KEY not set — video generation will be unavailable');
  }
})();

const PORT      = parseInt(process.env.PORT) || 3000;
const GEM_KEY   = process.env.GEMINI_API_KEY;
const PWD_HASH  = process.env.DASHBOARD_PASSWORD_HASH;
const WAVE_KEY  = process.env.WAVESPEED_API_KEY || null;

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
  sessions.set(token, { email, csrfToken, createdAt: Date.now(), trends: [], queue: [], videos: [] });
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

// ── LOGIN RATE LIMITING ───────────────────────────────────────
const loginAttempts = new Map();
function checkRateLimit(ip) {
  const e = loginAttempts.get(ip) || { count: 0, lockedUntil: 0 };
  if (Date.now() < e.lockedUntil)
    return { blocked: true, secs: Math.ceil((e.lockedUntil - Date.now()) / 1000) };
  return { blocked: false };
}
function recordFail(ip) {
  const e = loginAttempts.get(ip) || { count: 0, lockedUntil: 0 };
  if (++e.count >= 5) { e.lockedUntil = Date.now() + 60000; e.count = 0; }
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
    req.on('data', c => { if ((size += c.length) > maxBytes) { req.destroy(); reject(new Error('Body too large')); return; } data += c; });
    req.on('end', () => { try { resolve(JSON.parse(data)); } catch { reject(new Error('Invalid JSON')); } });
    req.on('error', reject);
  });
}

function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
}
function sendHTML(res, status, html) {
  res.writeHead(status, { 'Content-Type': 'text/html; charset=utf-8' });
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
// GEMINI — Script generation (FREE)
// aistudio.google.com → Get API Key → paste into .env
// ════════════════════════════════════════════════════════════════
async function callGemini(prompt) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { responseMimeType: 'application/json', maxOutputTokens: 1024, temperature: 0.7 },
      systemInstruction: { parts: [{ text: 'You are a fitness content strategist. Return valid JSON only — no markdown.' }] }
    });

    const req = https.request({
      hostname: 'generativelanguage.googleapis.com',
      path    : `/v1beta/models/gemini-2.0-flash:generateContent?key=${GEM_KEY}`,
      method  : 'POST',
      headers : { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) }
    }, res => {
      let data = '', size = 0;
      res.on('data', c => { if ((size += c.length) > 500 * 1024) { req.destroy(); reject(new Error('Gemini response too large')); return; } data += c; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.error) { reject(new Error(String(json.error.message).slice(0, 200))); return; }
          const text = json.candidates?.[0]?.content?.parts?.[0]?.text;
          if (!text) { reject(new Error('Empty Gemini response')); return; }
          resolve(JSON.parse(text.replace(/```json|```/g, '').trim()));
        } catch(e) { reject(e); }
      });
    });
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('Gemini timed out')); });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ════════════════════════════════════════════════════════════════
// WAVESPEED — Video generation using LTX-2.3
// LTX-2.3 generates VIDEO + AUDIO from text in one pass
// Sign up at wavespeed.ai → Dashboard → API Keys → Create
// Free $1 credit on signup (no card needed for signup, card needed to add more)
//
// Endpoint  : POST https://api.wavespeed.ai/api/v3/wavespeed-ai/ltx-2.3/text-to-video
// Poll      : GET  https://api.wavespeed.ai/api/v3/predictions/{id}/result
// Docs      : https://wavespeed.ai/docs/docs-api/wavespeed-ai/ltx-2.3-text-to-video
// ════════════════════════════════════════════════════════════════

const WAVESPEED_HOST = 'api.wavespeed.ai';

// Step 1: Submit video generation job
async function submitWavespeedJob(prompt) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      prompt      : sanitize(prompt, 500),
      resolution  : '720p',
      aspect_ratio: '9:16',   // vertical — best for TikTok/Reels/Shorts
      duration    : 5,        // 5 seconds per clip (cheapest, good for social)
      seed        : -1        // random
    });

    const req = https.request({
      hostname: WAVESPEED_HOST,
      path    : '/api/v3/wavespeed-ai/ltx-2.3/text-to-video',
      method  : 'POST',
      headers : {
        'Content-Type'  : 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'Authorization' : `Bearer ${WAVE_KEY}`
      }
    }, res => {
      let data = '', size = 0;
      res.on('data', c => { if ((size += c.length) > 100 * 1024) { req.destroy(); reject(new Error('WaveSpeed response too large')); return; } data += c; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (!json.data?.id) reject(new Error(json.detail || json.error || 'WaveSpeed job submission failed'));
          else resolve(json.data.id);
        } catch(e) { reject(e); }
      });
    });
    req.setTimeout(15000, () => { req.destroy(); reject(new Error('WaveSpeed submission timed out')); });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// Step 2: Poll until video is ready (max 3 minutes)
async function pollWavespeedResult(jobId) {
  const maxAttempts = 36; // 36 × 5s = 3 minutes max
  const delay = ms => new Promise(r => setTimeout(r, ms));

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    await delay(5000);

    const result = await new Promise((resolve, reject) => {
      const req = https.request({
        hostname: WAVESPEED_HOST,
        path    : `/api/v3/predictions/${encodeURIComponent(jobId)}/result`,
        method  : 'GET',
        headers : { 'Authorization': `Bearer ${WAVE_KEY}` }
      }, res => {
        let data = '', size = 0;
        res.on('data', c => { if ((size += c.length) > 100 * 1024) { req.destroy(); reject(new Error('Poll response too large')); return; } data += c; });
        res.on('end', () => {
          try { resolve(JSON.parse(data)); }
          catch(e) { reject(e); }
        });
      });
      req.setTimeout(10000, () => { req.destroy(); reject(new Error('Poll timed out')); });
      req.on('error', reject);
      req.end();
    });

    const status = result.data?.status;
    log(`WaveSpeed job ${jobId} status: ${status} (attempt ${attempt + 1})`, 'INFO');

    if (status === 'completed') {
      const videoUrl = result.data?.outputs?.[0];
      if (!videoUrl) throw new Error('Video completed but no output URL found');
      return videoUrl;
    }
    if (status === 'failed') {
      throw new Error(result.data?.error || 'Video generation failed');
    }
    // status === 'processing' or 'queued' → keep polling
  }
  throw new Error('Video generation timed out after 3 minutes');
}

// ════════════════════════════════════════════════════════════════
// HTTP SERVER
// ════════════════════════════════════════════════════════════════
const server = http.createServer(async (req, res) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  res.setHeader('Referrer-Policy', 'no-referrer');

  const ip = req.socket.remoteAddress || 'unknown';

  // ── SERVE FRONTEND ────────────────────────────────────────
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    try {
      const html = fs.readFileSync(path.resolve(__dirname, '..', 'index.html'), 'utf8')
                     .replace('%%CSRF_TOKEN%%', 'pending-login');
      sendHTML(res, 200, html);
    } catch { sendJSON(res, 500, { error: 'Could not serve app' }); }
    return;
  }

  // ── CONFIG CHECK (tells frontend if video is available) ───
  if (req.method === 'GET' && req.url === '/api/config') {
    sendJSON(res, 200, { videoEnabled: !!WAVE_KEY });
    return;
  }

  // ── LOGIN ─────────────────────────────────────────────────
  if (req.method === 'POST' && req.url === '/auth/login') {
    const { blocked, secs } = checkRateLimit(ip);
    if (blocked) { sendJSON(res, 429, { message: `Too many attempts. Wait ${secs}s.` }); return; }
    try {
      const { email, password } = await readBody(req);
      if (typeof email !== 'string' || typeof password !== 'string') throw new Error('Invalid');
      const hash  = crypto.createHash('sha256').update(password).digest('hex');
      if (hash !== PWD_HASH) {
        recordFail(ip);
        sendJSON(res, 401, { message: 'Invalid credentials' });
        log(`Failed login: ${email}`, 'WARN');
        return;
      }
      resetFails(ip);
      const { token, csrfToken } = createSession(email.slice(0, 200));
      sendJSON(res, 200, { token, csrfToken });
      log(`Login OK: ${email}`, 'INFO');
    } catch { sendJSON(res, 400, { error: 'Bad request' }); }
    return;
  }

  // ── GET USER DATA ─────────────────────────────────────────
  if (req.method === 'GET' && req.url === '/api/user-data') {
    const s = requireAuth(req, res);
    if (!s) return;
    sendJSON(res, 200, { trends: s.trends, scripts: [], queue: s.queue, videos: s.videos, posted: 0 });
    return;
  }

  // ── ADD TREND ─────────────────────────────────────────────
  if (req.method === 'POST' && req.url === '/api/trends') {
    const s = requireAuth(req, res);
    if (!s) return;
    try {
      const { topic, source, notes } = await readBody(req);
      if (!topic?.trim()) throw new Error('Invalid topic');
      if (!ALLOWED_SOURCES.has(source)) throw new Error('Invalid source');
      const trend = { id: crypto.randomUUID(), topic: sanitize(topic, 80), source, notes: sanitize(notes || '', 200), date: new Date().toISOString() };
      s.trends.push(trend);
      sendJSON(res, 200, trend);
      log(`Trend added: ${trend.topic}`, 'INFO');
    } catch(e) { sendJSON(res, 400, { error: e.message }); }
    return;
  }

  // ── GENERATE SCRIPT (GEMINI) ──────────────────────────────
  if (req.method === 'POST' && req.url === '/api/generate-script') {
    const s = requireAuth(req, res);
    if (!s) return;
    try {
      const { trendId, source } = await readBody(req);
      const trend = s.trends.find(t => t.id === trendId);
      if (!trend) throw new Error('Trend not found');

      const safeTopic  = sanitize(trend.topic, 80);
      const safeSource = ALLOWED_SOURCES.has(source) ? source : 'fitness platform';

      const script = await callGemini(`Write an ORIGINAL fitness video script for Mhed Fitness & Sports.
Inspired by trending topic: "${safeTopic}" found on ${safeSource}.
100% original content — same topic idea, entirely your own words.

Return JSON:
{
  "hook"    : "Opening line, first 3 seconds — max 100 chars",
  "body"    : "Main content, 4-6 key points — max 500 chars",
  "cta"     : "Call to action — max 100 chars",
  "caption" : "Full social media caption — max 2000 chars",
  "hashtags": ["exactly 8 hashtags starting with #"],
  "videoPrompt": "A short visual description for AI video generation — describe the fitness scene, setting, movements, lighting — max 200 chars"
}`);

      if (!script?.hook) throw new Error('Invalid Gemini response');

      const safe = {
        hook       : String(script.hook    || '').slice(0, 200),
        body       : String(script.body    || '').slice(0, 600),
        cta        : String(script.cta     || '').slice(0, 200),
        caption    : String(script.caption || '').slice(0, 2200),
        hashtags   : (Array.isArray(script.hashtags) ? script.hashtags : []).filter(h => typeof h === 'string').slice(0, 8),
        videoPrompt: String(script.videoPrompt || safeTopic + ' fitness workout').slice(0, 200)
      };

      sendJSON(res, 200, safe);
      log(`Script generated for ${s.email}: ${safeTopic}`, 'INFO');
    } catch(e) {
      log(`Gemini error: ${e.message}`, 'ERROR');
      sendJSON(res, 500, { error: 'Script generation failed. Check your Gemini API key.' });
    }
    return;
  }

  // ── GENERATE VIDEO (WAVESPEED LTX-2.3) ───────────────────
  if (req.method === 'POST' && req.url === '/api/generate-video') {
    const s = requireAuth(req, res);
    if (!s) return;

    if (!WAVE_KEY) {
      sendJSON(res, 503, { error: 'Video generation not configured. Add WAVESPEED_API_KEY to .env.' });
      return;
    }

    try {
      const { videoPrompt } = await readBody(req);
      if (!videoPrompt?.trim()) throw new Error('Video prompt required');

      const safePrompt = sanitize(videoPrompt, 300);

      // Build a fitness-specific prompt
      const fullPrompt = `${safePrompt}. Fitness content for social media. Dynamic movement. Professional lighting. Vertical 9:16 format suitable for TikTok and Instagram Reels.`;

      log(`Submitting video job for ${s.email}: ${safePrompt}`, 'INFO');
      const jobId = await submitWavespeedJob(fullPrompt);
      log(`Video job submitted: ${jobId}`, 'INFO');

      // Poll for result (this blocks for up to 3 min — consider webhooks for production)
      const videoUrl = await pollWavespeedResult(jobId);

      const videoEntry = {
        id       : crypto.randomUUID(),
        jobId,
        videoUrl,
        prompt   : safePrompt,
        createdAt: new Date().toISOString()
      };
      s.videos.push(videoEntry);

      sendJSON(res, 200, videoEntry);
      log(`Video ready for ${s.email}: ${videoUrl}`, 'INFO');
    } catch(e) {
      log(`Video error: ${e.message}`, 'ERROR');
      sendJSON(res, 500, { error: e.message || 'Video generation failed' });
    }
    return;
  }

  // ── QUEUE SCRIPT ──────────────────────────────────────────
  if (req.method === 'POST' && req.url === '/api/queue') {
    const s = requireAuth(req, res);
    if (!s) return;
    try {
      const { script } = await readBody(req);
      if (!script?.hook) throw new Error('Invalid script');
      const item = { id: crypto.randomUUID(), title: String(script.hook).slice(0, 60), platform: 'TikTok', status: 'queued', date: new Date().toISOString() };
      s.queue.push(item);
      sendJSON(res, 200, item);
    } catch(e) { sendJSON(res, 400, { error: e.message }); }
    return;
  }

  // ── DELETE QUEUE ITEM ─────────────────────────────────────
  if (req.method === 'DELETE' && req.url.startsWith('/api/queue/')) {
    const s = requireAuth(req, res);
    if (!s) return;
    const rawId = req.url.split('/').pop();
    const idx   = s.queue.findIndex(q => q.id === rawId);
    if (idx === -1) { sendJSON(res, 404, { error: 'Not found' }); return; }
    s.queue.splice(idx, 1);
    sendJSON(res, 200, { success: true });
    return;
  }

  sendJSON(res, 404, { error: 'Not found' });
});

server.listen(PORT, () => {
  log(`FitBot running → http://localhost:${PORT}`, 'INFO');
  log(`Script AI : Gemini 2.0 Flash (free)`, 'INFO');
  log(`Video AI  : WaveSpeed LTX-2.3 ${WAVE_KEY ? '(configured ✓)' : '(not configured — add WAVESPEED_API_KEY)'}`, 'INFO');
});
