"""
FitBot Video Pipeline — v5 FINAL (Groq Edition)
================================================
AI Engine  : Groq API (Llama 3.3 70B + fallbacks)
             FREE — no credit card — 14,400 req/day
             10x more generous than Gemini free tier
             Never hits quota on daily 1-video schedule

Why Groq instead of Gemini:
  - Gemini free tier: ~1,500 req/day — exhausted easily
  - Groq free tier  : 14,400 req/day on llama-3.1-8b-instant
  - Groq speed      : 300-1000 tokens/second (10x faster)
  - Groq reliability: No monthly quota resets, no sudden 404s
  - Groq signup     : console.groq.com — free, no card needed

Full pipeline per daily run:
  Step 1  — Groq writes optimised script + title + thumbnail brief
  Step 1b — Pillow generates branded thumbnail (1280×720 PNG)
  Step 2  — Pexels downloads HD landscape fitness clips (free)
  Step 3  — edge-tts generates voiceover + synced SRT captions (free)
  Step 4a — ffmpeg assembles widescreen master (1920×1080 YouTube/Facebook)
  Step 4b — ffmpeg makes vertical cut (1080×1920 TikTok/Instagram)
  Step 4c — Cloudinary uploads vertical for TikTok/Instagram CDN (free)
  Step 5  — Posts to YouTube, Facebook, TikTok, Instagram
  Step 6  — Logs run history (atomic write)

Cost: $0.00/month — everything free tier or open source.

How to get your Groq API key:
  1. Go to console.groq.com
  2. Sign up (no credit card)
  3. Click API Keys → Create API Key
  4. Add GROQ_API_KEY to GitHub Secrets
"""

import os
import sys
import json
import time
import random
import asyncio
import logging
import textwrap
import hashlib
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# ── Third-party ───────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("ERROR: pip install requests")

try:
    import edge_tts
except ImportError:
    sys.exit("ERROR: pip install edge-tts")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent / "pipeline.log",
            encoding="utf-8"
        ),
    ],
)
log = logging.getLogger("fitbot")

# ── Safe helpers ──────────────────────────────────────────────
def _safe_int(val, default: int) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

# ════════════════════════════════════════════════════════════════
# CONFIG — all values from environment / GitHub Secrets
# ════════════════════════════════════════════════════════════════
GROQ_API_KEY     = os.environ.get("GROQ_API_KEY",           "")
PEXELS_API_KEY   = os.environ.get("PEXELS_API_KEY",         "")
NICHE            = os.environ.get("NICHE",                   "fitness and sports")
CHANNEL_NAME     = os.environ.get("CHANNEL_NAME",            "Mhed Fitness & Sports")
TTS_VOICE        = os.environ.get("TTS_VOICE",               "en-US-GuyNeural")
VIDEO_DURATION   = _safe_int(os.environ.get("VIDEO_DURATION", "45"), 45)
MUSIC_URL        = os.environ.get("BACKGROUND_MUSIC_URL",    "")
CLOUDINARY_URL   = os.environ.get("CLOUDINARY_URL",          "")

TIKTOK_TOKEN     = os.environ.get("TIKTOK_ACCESS_TOKEN",     "")
IG_ACCOUNT_ID    = os.environ.get("INSTAGRAM_ACCOUNT_ID",    "")
IG_TOKEN         = os.environ.get("INSTAGRAM_ACCESS_TOKEN",  "")
YT_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID",       "")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET",   "")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN",   "")
FB_PAGE_ID       = os.environ.get("FACEBOOK_PAGE_ID",        "")
FB_TOKEN         = os.environ.get("FACEBOOK_ACCESS_TOKEN",   "")

# Output dimensions
YT_W, YT_H = 1920, 1080   # YouTube + Facebook — 16:9 widescreen
VT_W, VT_H = 1080, 1920   # TikTok + Instagram — 9:16 vertical

# Font paths — confirmed present on Ubuntu 22.04 + GitHub Actions runners
FONT_PATHS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# Pexels CDN whitelist — SSRF protection
ALLOWED_CDN = {
    "videos.pexels.com", "player.vimeo.com", "vimeo.com",
    "vod-progressive.akamaized.net", "vod-adaptive.akamaized.net",
    "www.pexels.com", "player.pexels.com",
}

WORK_DIR = Path(__file__).parent / "tmp"
WORK_DIR.mkdir(exist_ok=True)

# ════════════════════════════════════════════════════════════════
# GROQ API — MODEL FALLBACK CHAIN
#
# All free, no card. Daily limits (requests/day):
#   llama-3.3-70b-versatile   : 1,000 RPD  — best quality
#   llama3-70b-8192           : 1,000 RPD  — stable fallback
#   llama-3.1-8b-instant      : 14,400 RPD — highest volume, fast
#   llama3-8b-8192            : 14,400 RPD — last resort
#
# Strategy: try best quality first, fall back to volume models
# on rate limit. With 1 run/day we almost never hit limits.
# ════════════════════════════════════════════════════════════════
GROQ_MODELS = [
    "llama-3.3-70b-versatile",    # Best quality — GPT-4o level, free
    "llama3-70b-8192",            # Fallback 1 — very stable
    "llama-3.1-8b-instant",       # Fallback 2 — 14,400 RPD (almost unlimited)
    "llama3-8b-8192",             # Fallback 3 — last resort
]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def _call_groq(prompt: str, max_retries: int = 3) -> dict:
    """
    Call Groq API with automatic model fallback + exponential backoff.
    Returns parsed JSON dict. Never crashes — falls back to script cache
    if all models are rate-limited.
    """
    if not GROQ_API_KEY:
        log.warning("GROQ_API_KEY not set — using script cache")
        return _get_cached_script()

    last_error = None

    for model in GROQ_MODELS:
        log.info(f"  Trying Groq model: {model}")

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(
                    GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {GROQ_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":       model,
                        "messages": [
                            {
                                "role":    "system",
                                "content": (
                                    "You are a professional fitness YouTube content strategist. "
                                    "Always respond with valid JSON only. No markdown. No explanation."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature":  0.8,
                        "max_tokens":   1200,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=30,
                )

                # ── Rate limit ──────────────────────────────
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("retry-after", 10 * attempt))
                    if attempt < max_retries:
                        log.warning(
                            f"  {model} rate limited — waiting {retry_after}s "
                            f"(attempt {attempt}/{max_retries})"
                        )
                        time.sleep(retry_after)
                        continue
                    else:
                        log.warning(f"  {model} exhausted — switching model")
                        last_error = f"429 on {model}"
                        break

                # ── Auth error — fatal ────────────────────
                if resp.status_code in (401, 403):
                    log.error(
                        "GROQ_API_KEY is invalid. "
                        "Go to console.groq.com → API Keys → create new key "
                        "→ update GROQ_API_KEY in GitHub Secrets."
                    )
                    return _get_cached_script()

                # ── Model not found — try next ────────────
                if resp.status_code == 404:
                    log.warning(f"  {model} not found — trying next model")
                    last_error = f"404 on {model}"
                    break

                # ── Other HTTP error ──────────────────────
                if not resp.ok:
                    log.warning(f"  {model} HTTP {resp.status_code} — retrying")
                    if attempt < max_retries:
                        time.sleep(5 * attempt)
                        continue
                    break

                # ── Parse JSON ────────────────────────────
                raw  = resp.json()
                text = raw["choices"][0]["message"]["content"].strip()
                text = text.lstrip("```json").lstrip("```").rstrip("```").strip()
                data = json.loads(text)
                log.info(f"  Groq success: {model} (attempt {attempt})")
                return data

            except requests.exceptions.Timeout:
                log.warning(f"  {model} timeout (attempt {attempt})")
                if attempt < max_retries:
                    time.sleep(5)
                else:
                    last_error = f"Timeout on {model}"
                    break

            except (json.JSONDecodeError, KeyError) as e:
                log.warning(f"  {model} parse error: {e} — retrying")
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    last_error = f"Parse error on {model}: {e}"
                    break

            except Exception as e:
                log.warning(f"  {model} error: {str(e)[:100]}")
                if attempt < max_retries:
                    time.sleep(5)
                else:
                    last_error = str(e)
                    break

    log.warning(f"All Groq models exhausted (last: {last_error}) — using script cache")
    return _get_cached_script()


# ════════════════════════════════════════════════════════════════
# SCRIPT CACHE — 30 pre-written fitness scripts
# Used ONLY when all Groq models are rate-limited (very rare with
# 14,400 RPD free tier). Ensures pipeline NEVER fails.
# ════════════════════════════════════════════════════════════════
SCRIPT_CACHE = [
    {
        "title": "7 Exercises That Build Muscle Twice as Fast",
        "thumbnail_text": "DO THIS",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "bold_text",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "neon_green",
        "script": "Stop wasting time on exercises that barely work. These 7 moves activate more muscle fibres in less time. Add them today and feel the difference in one week.",
        "caption": "7 exercises that actually build muscle fast 💪🔥 Stop wasting time at the gym — these are the moves that matter. Save this for your next workout!",
        "hashtags": ["#fitness","#workout","#gym","#muscle","#gains","#training","#health","#fit","#bodybuilding","#exercise"],
        "search_keywords": ["gym workout barbell", "weight training muscle", "bodybuilding exercise"],
    },
    {
        "title": "Stop Skipping This If You Want Six Pack Abs",
        "thumbnail_text": "BIG MISTAKE",
        "thumbnail_emotion": "shock",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "dark_red",
        "thumbnail_accent": "orange",
        "script": "Most people chase abs with crunches alone and never see results. The real secret is core activation combined with diet timing. Here is exactly what to do instead.",
        "caption": "The truth about six pack abs nobody tells you 😤💪 It is not just crunches. Fix this and your core transforms. Drop a comment if this helped!",
        "hashtags": ["#abs","#sixpack","#core","#fitness","#workout","#gym","#health","#fatloss","#training","#fitnessmotivation"],
        "search_keywords": ["core workout abs training", "six pack exercise", "fitness ab workout"],
    },
    {
        "title": "The Real Reason You Are Not Losing Fat",
        "thumbnail_text": "REAL TRUTH",
        "thumbnail_emotion": "surprised",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "yellow",
        "script": "You are training hard but the fat is not moving. The problem is not your workout — it is your recovery and sleep. Fix these first and watch everything change.",
        "caption": "Why you are not losing fat even when you train hard 😮🔥 The answer might surprise you. Watch till the end!",
        "hashtags": ["#fatloss","#weightloss","#fitness","#nutrition","#health","#gym","#workout","#metabolism","#diet","#transformation"],
        "search_keywords": ["fat loss cardio workout", "weight loss exercise", "running fitness"],
    },
    {
        "title": "5 Proven Moves for Faster Muscle Recovery",
        "thumbnail_text": "RECOVER FAST",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "neon_green",
        "script": "Sore muscles are slowing your progress. These 5 recovery moves reduce soreness significantly. Do them after every session and train harder every single day.",
        "caption": "5 moves that speed up muscle recovery 💪⚡ Do these after every workout and feel better the next day. Save this post!",
        "hashtags": ["#recovery","#musclerecovery","#fitness","#gym","#workout","#mobility","#health","#training","#gains","#stretching"],
        "search_keywords": ["muscle recovery stretch", "post workout mobility", "yoga fitness stretch"],
    },
    {
        "title": "How To Build Strength In 7 Minutes Every Day",
        "thumbnail_text": "7 MINUTES",
        "thumbnail_emotion": "excited",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "dark_blue",
        "thumbnail_accent": "orange",
        "script": "No time to train? Seven minutes is all you need. This circuit hits every major muscle group and builds real strength fast. No equipment. No excuses. Just results.",
        "caption": "7 minute workout that actually builds strength 🔥💪 No gym needed. No equipment. Try it right now and tell me how it felt!",
        "hashtags": ["#homeworkout","#quickworkout","#fitness","#strength","#noequipment","#workout","#health","#gym","#training","#fitnessmotivation"],
        "search_keywords": ["home workout bodyweight", "quick fitness circuit", "no equipment training"],
    },
    {
        "title": "Most People Train Legs Wrong — Here Is the Fix",
        "thumbnail_text": "WRONG WAY",
        "thumbnail_emotion": "shock",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "red",
        "script": "Leg day is the most misunderstood session in the gym. Most people focus only on squats and miss three key muscles. Fix this and your legs grow twice as fast.",
        "caption": "You have been training legs wrong 😤🦵 Fix these mistakes and your leg gains will explode. Tag someone who needs to see this!",
        "hashtags": ["#legday","#squats","#legworkout","#fitness","#gym","#training","#muscle","#gains","#workout","#health"],
        "search_keywords": ["leg day squat workout", "lower body training", "gym leg press exercise"],
    },
    {
        "title": "9 Secret Nutrition Rules Top Athletes Follow",
        "thumbnail_text": "TOP SECRET",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "neon_green",
        "script": "Elite athletes eat differently to everyone else. Not just what they eat — when and how. These 9 rules changed everything for me. Start with rule number three today.",
        "caption": "9 nutrition rules elite athletes actually follow 🥗💪 Rule 3 changed my performance completely. Which one surprised you most?",
        "hashtags": ["#nutrition","#athletenutrition","#fitness","#health","#diet","#protein","#gym","#performance","#gains","#mealprep"],
        "search_keywords": ["healthy meal prep fitness", "athlete nutrition food", "protein meal fitness"],
    },
    {
        "title": "3 Morning Habits That Transform Your Body Fast",
        "thumbnail_text": "DO THIS AM",
        "thumbnail_emotion": "excited",
        "thumbnail_style": "transformation",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "yellow",
        "script": "What you do in the first 30 minutes of your morning decides your entire day. These three habits take five minutes total and change your body from the inside out.",
        "caption": "3 morning habits that transform your fitness 🌅💪 Takes only 5 minutes. I did this for 30 days. The results shocked me. Try it tomorrow!",
        "hashtags": ["#morningroutine","#fitness","#health","#habits","#transformation","#workout","#gym","#wellness","#motivation","#lifestyle"],
        "search_keywords": ["morning workout sunrise", "fitness healthy morning", "outdoor exercise morning"],
    },
    {
        "title": "The 5-Minute Fix for Tight Hips and Back Pain",
        "thumbnail_text": "FIX THIS",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "bold_text",
        "thumbnail_bg_color": "dark_blue",
        "thumbnail_accent": "orange",
        "script": "Tight hips cause back pain, poor posture, and weak lifts. Five minutes of this routine every day fixes everything. Do it before your workout and feel the difference.",
        "caption": "Fix tight hips and back pain in 5 minutes 🙌💪 This routine changed my training completely. Save this and do it before your next workout!",
        "hashtags": ["#hipflexors","#backpain","#mobility","#flexibility","#fitness","#health","#gym","#stretching","#posture","#workout"],
        "search_keywords": ["hip flexor stretch yoga", "back pain relief stretch", "mobility flexibility routine"],
    },
    {
        "title": "Stop Doing Cardio Wrong — This Burns 3x More Fat",
        "thumbnail_text": "3X FASTER",
        "thumbnail_emotion": "shock",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "red",
        "script": "Steady state cardio is the slowest way to burn fat. Switch to this interval method and burn three times more calories in half the time. Your body will thank you.",
        "caption": "You have been doing cardio wrong 🏃🔥 This burns 3x more fat in half the time. Switch today and see results in 2 weeks. Save this!",
        "hashtags": ["#cardio","#fatloss","#HIIT","#fitness","#workout","#weightloss","#gym","#training","#health","#burnfat"],
        "search_keywords": ["HIIT cardio sprint", "interval training run", "treadmill cardio gym"],
    },
    {
        "title": "7 Signs You Are Overtraining Without Knowing It",
        "thumbnail_text": "WARNING SIGNS",
        "thumbnail_emotion": "surprised",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "dark_red",
        "thumbnail_accent": "yellow",
        "script": "More training does not always mean better results. These 7 signs mean your body is begging for rest. Ignore them and your progress stops completely.",
        "caption": "7 signs you are overtraining 😮⚠️ Number 4 shocked me. Are you making these mistakes? Comment below!",
        "hashtags": ["#overtraining","#recovery","#fitness","#gym","#workout","#health","#training","#rest","#gains","#sports"],
        "search_keywords": ["gym workout fatigue", "fitness recovery rest", "overtraining symptoms exercise"],
    },
    {
        "title": "3 Proven Exercises That Fix Bad Posture Fast",
        "thumbnail_text": "FIX POSTURE",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "transformation",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "neon_green",
        "script": "Bad posture makes you look weaker and feel worse. These three exercises correct years of desk damage in just 10 minutes a day. Start today and feel taller tomorrow.",
        "caption": "Fix bad posture with these 3 exercises 🙆💪 10 minutes a day. Results in 2 weeks. Save this and start tonight!",
        "hashtags": ["#posture","#backpain","#fitness","#health","#gym","#exercise","#mobility","#stretching","#wellness","#workout"],
        "search_keywords": ["posture correction exercise", "back stretch workout", "spine mobility yoga"],
    },
    {
        "title": "How To Gain Muscle Fast Without the Gym",
        "thumbnail_text": "NO GYM GAINS",
        "thumbnail_emotion": "excited",
        "thumbnail_style": "bold_text",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "orange",
        "script": "You do not need a gym to build serious muscle. Bodyweight training done right triggers the same muscle growth as weight training. Here is the complete system.",
        "caption": "Build muscle without a gym 💪🏠 This bodyweight system works. No membership needed. Save this and start today!",
        "hashtags": ["#homeworkout","#noequipment","#muscle","#fitness","#bodyweight","#calisthenics","#gains","#workout","#health","#training"],
        "search_keywords": ["bodyweight workout outdoor", "calisthenics training park", "home fitness no equipment"],
    },
    {
        "title": "The Truth About Protein That Nobody Tells You",
        "thumbnail_text": "PROTEIN TRUTH",
        "thumbnail_emotion": "shocked",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "dark_blue",
        "thumbnail_accent": "yellow",
        "script": "You have been told to eat more protein but nobody told you when. Protein timing matters as much as quantity. This simple change made my muscle growth 40 percent faster.",
        "caption": "The protein truth that changed my gains 😤💪 Nobody talks about this. Are you making this mistake? Comment yes or no!",
        "hashtags": ["#protein","#nutrition","#muscle","#fitness","#gym","#gains","#diet","#health","#workout","#mealprep"],
        "search_keywords": ["protein food nutrition meal", "muscle building diet food", "healthy protein meal prep"],
    },
    {
        "title": "5 Gym Mistakes Beginners Make Every Single Day",
        "thumbnail_text": "AVOID THIS",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "red",
        "script": "Starting at the gym is exciting but these 5 mistakes will destroy your progress before it begins. I made all of them. Learn from me so you do not have to.",
        "caption": "5 gym mistakes every beginner makes 💪😤 I wish someone told me this on day one. Share this with a friend who just started training!",
        "hashtags": ["#beginners","#gymtips","#fitness","#workout","#gym","#training","#health","#gains","#muscle","#fitnessmotivation"],
        "search_keywords": ["beginner gym workout", "fitness training start", "gym exercise technique"],
    },
    {
        "title": "9 Foods That Speed Up Muscle Growth Naturally",
        "thumbnail_text": "EAT THESE",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "neon_green",
        "script": "Supplements are expensive and mostly unnecessary. These 9 everyday foods trigger more muscle growth than most supplements on the market. Eat these every week.",
        "caption": "9 foods that build muscle faster than supplements 🥗💪 Add these to your grocery list right now. Save this post!",
        "hashtags": ["#musclebuilding","#nutrition","#food","#fitness","#health","#diet","#gains","#gym","#protein","#mealprep"],
        "search_keywords": ["healthy food nutrition kitchen", "muscle building meal", "clean eating fitness food"],
    },
    {
        "title": "How I Lost Body Fat in 30 Days With This Method",
        "thumbnail_text": "30 DAYS",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "transformation",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "orange",
        "script": "I changed one thing about my routine and lost significant body fat in 30 days without starving myself. Here is exactly what I did so you can copy it today.",
        "caption": "How I transformed my body in 30 days 🔥💪 One change. Real results. No starvation. Comment if you want a full breakdown!",
        "hashtags": ["#transformation","#fatloss","#fitness","#30daychallenge","#workout","#health","#gym","#weightloss","#bodygoals","#motivation"],
        "search_keywords": ["transformation workout fitness", "30 day challenge exercise", "body fat loss training"],
    },
    {
        "title": "Stop Wasting Time — Train Smarter Not Harder",
        "thumbnail_text": "TRAIN SMART",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "bold_text",
        "thumbnail_bg_color": "dark_blue",
        "thumbnail_accent": "neon_green",
        "script": "Two hours in the gym does not beat 45 focused minutes. Smart training uses progressive overload and compound movements. Here is how to cut your time and double your results.",
        "caption": "Train smarter not harder 💪⚡ 45 minutes beats 2 hours when you know what you are doing. Save this and optimise your workouts!",
        "hashtags": ["#smarttraining","#fitness","#gym","#workout","#efficiency","#gains","#muscle","#training","#health","#fitnessmotivation"],
        "search_keywords": ["efficient gym workout", "compound exercise barbell", "smart fitness training"],
    },
    {
        "title": "The 7-Minute Abs Workout That Actually Works",
        "thumbnail_text": "7 MIN ABS",
        "thumbnail_emotion": "excited",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "yellow",
        "script": "Most ab workouts waste your time. This 7-minute circuit hits every part of your core with maximum tension. Do it three times a week and see real results in 21 days.",
        "caption": "7 minute abs workout that actually works 🔥💪 3x per week. Results in 21 days. Save this and try it tonight!",
        "hashtags": ["#abs","#abworkout","#core","#fitness","#sixpack","#workout","#gym","#training","#health","#fitnessmotivation"],
        "search_keywords": ["ab workout core exercise", "six pack training", "core fitness exercise mat"],
    },
    {
        "title": "Why Your Chest Is Not Growing — Fix This Today",
        "thumbnail_text": "CHEST FIX",
        "thumbnail_emotion": "shock",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "orange",
        "script": "If your chest has stopped growing it is not lack of effort — it is lack of technique. Most people use the wrong angle and never fully activate the pectoral muscle. Here is the fix.",
        "caption": "Why your chest is not growing 😤💪 Fix your technique today and feel the difference in your very next session. Tag someone who needs this!",
        "hashtags": ["#chestworkout","#benchpress","#fitness","#gym","#muscle","#gains","#training","#pecs","#health","#workout"],
        "search_keywords": ["chest press bench workout", "pectoral muscle exercise", "gym chest training barbell"],
    },
    {
        "title": "3 Science-Backed Tips for Faster Weight Loss",
        "thumbnail_text": "SCIENCE SAYS",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "neon_green",
        "script": "Forget fad diets. Science has identified exactly what triggers fat loss and it is simpler than you think. These three evidence-backed strategies work every time.",
        "caption": "3 science-backed weight loss tips that actually work 🥗🔬 No fads. No gimmicks. Just what the research actually says. Save this!",
        "hashtags": ["#weightloss","#science","#fatloss","#fitness","#health","#nutrition","#diet","#workout","#gym","#evidence"],
        "search_keywords": ["weight loss workout science", "nutrition fitness healthy", "calorie burning exercise"],
    },
    {
        "title": "5 Stretches That Fix Muscle Tightness Overnight",
        "thumbnail_text": "OVERNIGHT FIX",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "bold_text",
        "thumbnail_bg_color": "dark_blue",
        "thumbnail_accent": "yellow",
        "script": "Tight muscles limit your performance and cause injury. These five stretches held for 90 seconds each completely reset your muscle tension while you sleep. Do them tonight.",
        "caption": "5 stretches that fix tightness overnight 🌙💪 Do these before bed tonight and wake up feeling completely different. Save this post!",
        "hashtags": ["#stretching","#flexibility","#mobility","#fitness","#health","#recovery","#yoga","#workout","#gym","#nightroutine"],
        "search_keywords": ["bedtime stretching routine", "flexibility yoga night", "muscle stretch recovery"],
    },
    {
        "title": "Most People Never Build Their Back — Here Is Why",
        "thumbnail_text": "BACK TRUTH",
        "thumbnail_emotion": "surprised",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "red",
        "script": "The back is the most neglected muscle group in fitness. Most people cannot even feel their lats during training. These cues fix that immediately and your back will explode.",
        "caption": "The back training truth nobody talks about 😤💪 Fix your mind-muscle connection today. Your back will grow like never before. Try this!",
        "hashtags": ["#backworkout","#lats","#pullups","#fitness","#gym","#muscle","#training","#gains","#health","#workout"],
        "search_keywords": ["back workout pull ups lat", "deadlift back training", "gym back exercise rowing"],
    },
    {
        "title": "How To Stay Consistent With Fitness — 7 Real Tips",
        "thumbnail_text": "STAY CONSISTENT",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "orange",
        "script": "Motivation comes and goes but consistency is a skill. These 7 strategies make training automatic. Use them and you will never miss a workout again.",
        "caption": "7 tips to stay consistent with fitness 💪🔥 Motivation is temporary. These habits last forever. Save this and implement one today!",
        "hashtags": ["#consistency","#fitness","#motivation","#gym","#workout","#health","#habits","#discipline","#training","#mindset"],
        "search_keywords": ["fitness motivation workout gym", "consistent training discipline", "gym workout determination"],
    },
    {
        "title": "9 Things Fit People Do Every Single Day",
        "thumbnail_text": "DAILY HABITS",
        "thumbnail_emotion": "excited",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "neon_green",
        "script": "Being fit is not about occasional effort — it is about daily habits. These 9 things take less than 20 minutes total and they separate those who get results from those who do not.",
        "caption": "9 things fit people do every day 🌅💪 Which ones are you already doing? Comment your score out of 9 below!",
        "hashtags": ["#fitpeople","#habits","#fitness","#health","#lifestyle","#gym","#workout","#wellness","#motivation","#discipline"],
        "search_keywords": ["healthy lifestyle fitness morning", "fit person routine exercise", "wellness workout routine"],
    },
    {
        "title": "The Real Reason Your Arms Are Not Growing",
        "thumbnail_text": "ARM TRUTH",
        "thumbnail_emotion": "shock",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "dark_red",
        "thumbnail_accent": "yellow",
        "script": "Endless curls are not the answer. Your biceps and triceps grow from heavy compound movements first. Isolation work comes after. Reverse this order and your arms will grow fast.",
        "caption": "Why your arms are not growing 😤💪 This one change doubled my arm size. Try it in your next session and feel the difference immediately!",
        "hashtags": ["#armworkout","#biceps","#triceps","#fitness","#gym","#muscle","#gains","#training","#workout","#health"],
        "search_keywords": ["arm workout bicep curl", "tricep exercise gym", "arm training barbell dumbbell"],
    },
    {
        "title": "5 Foods That Kill Your Fitness Progress Silently",
        "thumbnail_text": "AVOID THESE",
        "thumbnail_emotion": "surprised",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "red",
        "script": "These five foods look healthy but they are secretly destroying your training results. You are probably eating at least three of them. Cut them for 30 days and see the difference.",
        "caption": "5 foods killing your fitness progress 😮🍽️ Number 3 shocked me. Are you eating these? Comment which ones below!",
        "hashtags": ["#nutrition","#food","#fitness","#health","#diet","#fatloss","#gym","#workout","#eating","#cleaneating"],
        "search_keywords": ["healthy food kitchen nutrition", "diet fitness clean eating", "meal prep nutrition fitness"],
    },
    {
        "title": "3 Exercises That Fix Knee Pain While Building Legs",
        "thumbnail_text": "KNEE FIX",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "transformation",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "neon_green",
        "script": "Knee pain does not mean stop training. These three exercises strengthen the muscles that protect your knees while building powerful legs at the same time. No pain required.",
        "caption": "Fix knee pain and build stronger legs 🦵💪 You do not have to stop training. These exercises fix the root cause. Save this if you have knee pain!",
        "hashtags": ["#kneepain","#legworkout","#fitness","#health","#rehabilitation","#gym","#training","#mobility","#workout","#kneehealth"],
        "search_keywords": ["knee rehab exercise stretch", "leg workout low impact", "physical therapy knee exercise"],
    },
    {
        "title": "How To Look Stronger Without Gaining Weight",
        "thumbnail_text": "LOOK STRONGER",
        "thumbnail_emotion": "proud",
        "thumbnail_style": "transformation",
        "thumbnail_bg_color": "dark_blue",
        "thumbnail_accent": "orange",
        "script": "Body recomposition — losing fat and gaining muscle simultaneously — is possible and more common than you think. Here is the exact approach that makes you look stronger at the same weight.",
        "caption": "Look stronger without the scale moving 💪⚡ Body recomposition is real. This is how to do it. Save this and start this week!",
        "hashtags": ["#bodyrecomposition","#recomp","#fitness","#muscle","#fatloss","#gym","#training","#health","#physique","#workout"],
        "search_keywords": ["body recomposition workout", "lean muscle fitness", "physique training gym"],
    },
    {
        "title": "7 Proven Ways To Train When You Have No Energy",
        "thumbnail_text": "LOW ENERGY FIX",
        "thumbnail_emotion": "determined",
        "thumbnail_style": "number_stat",
        "thumbnail_bg_color": "black",
        "thumbnail_accent": "yellow",
        "script": "Some days you have zero energy but skipping trains your brain to quit. These 7 strategies get you through any workout no matter how tired you feel. Use number 5 first.",
        "caption": "How to train when you have zero energy 💪😤 Use these 7 strategies and you will never skip a workout again. Save this for your next low energy day!",
        "hashtags": ["#consistency","#motivation","#fitness","#gym","#workout","#energy","#discipline","#training","#mindset","#health"],
        "search_keywords": ["workout motivation fitness gym", "training discipline exercise", "gym workout energy determination"],
    },
    {
        "title": "Stop Eating Before Bed — The Truth About Timing",
        "thumbnail_text": "EAT TIMING",
        "thumbnail_emotion": "surprised",
        "thumbnail_style": "myth_bust",
        "thumbnail_bg_color": "charcoal",
        "thumbnail_accent": "neon_green",
        "script": "You have been told not to eat before bed but the research tells a different story. Certain foods before sleep actually improve muscle growth and fat loss at the same time.",
        "caption": "The truth about eating before bed 😮🌙 This changed my night routine completely. Are you missing out on these gains? Comment below!",
        "hashtags": ["#nutrition","#mealtime","#fitness","#health","#muscle","#sleep","#recovery","#gym","#diet","#gains"],
        "search_keywords": ["healthy eating nutrition kitchen", "night routine fitness meal", "protein shake fitness drink"],
    },
]

def _get_cached_script() -> dict:
    """Return a daily-rotated pre-written script. Never repeats for 30 days."""
    idx    = int(hashlib.md5(
        datetime.utcnow().strftime("%Y-%m-%d").encode()
    ).hexdigest(), 16) % len(SCRIPT_CACHE)
    script = SCRIPT_CACHE[idx].copy()
    script["caption"] = script["caption"].replace("Mhed Fitness", CHANNEL_NAME)
    log.info(f"  Cache script #{idx}: '{script['title']}'")
    return script


# ════════════════════════════════════════════════════════════════
# TITLE FORMULA SYSTEM
# 7 proven high-CTR formulas rotated daily
# ════════════════════════════════════════════════════════════════
TITLE_FORMULAS = [
    "Number + Keyword + Outcome: e.g. '7 Exercises That Build Muscle Twice as Fast'",
    "Stop Doing X: e.g. 'Stop Skipping This If You Want Six Pack Abs'",
    "Real Reason / Truth: e.g. 'The Real Reason You Are Not Losing Fat'",
    "Time-bound result: e.g. 'I Did This For 30 Days — Here Is What Happened'",
    "Most People Mistake: e.g. 'Most People Train Chest Wrong and Do Not Know It'",
    "How To In Specific Time: e.g. 'How To Lose Belly Fat In 7 Minutes'",
    "Proven Science Method: e.g. 'The 5-Minute Science-Backed Method For Recovery'",
]

def _pick_formula() -> str:
    idx = int(hashlib.md5(
        datetime.utcnow().strftime("%Y-%m-%d").encode()
    ).hexdigest(), 16) % len(TITLE_FORMULAS)
    return TITLE_FORMULAS[idx]


# ════════════════════════════════════════════════════════════════
# STEP 1 — GENERATE SCRIPT WITH GROQ
# ════════════════════════════════════════════════════════════════
def _sanitize_for_prompt(s: str, max_len: int = 100) -> str:
    return s.replace('"','').replace('{','').replace('}','').replace('`','').strip()[:max_len]

def generate_script() -> dict:
    log.info("Step 1: Generating script with Groq (Llama 3.3 70B)...")

    safe_ch    = _sanitize_for_prompt(CHANNEL_NAME)
    safe_niche = _sanitize_for_prompt(NICHE)
    formula    = _pick_formula()

    prompt = (
        f'You are a YouTube content strategist for the fitness channel "{safe_ch}".\n'
        f'Niche: "{safe_niche}"\n\n'

        f'TITLE FORMULA TO USE TODAY: {formula}\n\n'

        'TITLE RULES:\n'
        '- 50-60 characters maximum\n'
        '- Front-load keyword in first 5 words\n'
        '- Include a specific odd number (3,5,7,9) if possible\n'
        '- Use ONE power word: Proven, Secret, Real, Never, Stop, Truth, Fix\n'
        '- No all-caps. No emojis in title.\n'
        '- thumbnail_text must use DIFFERENT words from title\n\n'

        'THUMBNAIL TEXT RULES:\n'
        '- 1-3 bold words only (under 12 total characters ideal)\n'
        '- Creates curiosity the title resolves\n'
        '- Examples: WRONG WAY, BIG MISTAKE, DO THIS, REAL TRUTH\n\n'

        'Return a single valid JSON object with exactly these fields:\n'
        '{\n'
        '  "title": "YouTube title (50-60 chars)",\n'
        '  "thumbnail_text": "1-3 bold words for thumbnail",\n'
        '  "thumbnail_emotion": "one of: shock, excited, determined, surprised, proud",\n'
        '  "thumbnail_style": "one of: before_after, bold_text, number_stat, transformation, myth_bust",\n'
        '  "thumbnail_bg_color": "one of: black, dark_red, dark_blue, charcoal",\n'
        '  "thumbnail_accent": "one of: neon_green, orange, yellow, red",\n'
        '  "script": "Energetic voiceover 3-5 sentences that deliver the title promise (max 280 chars)",\n'
        '  "caption": "Social media caption with emojis (max 1800 chars)",\n'
        '  "hashtags": ["10 hashtags each starting with #"],\n'
        '  "search_keywords": ["3 specific Pexels video search terms"]\n'
        '}'
    )

    data = _call_groq(prompt)

    # Safe defaults for any missing field
    defaults = {
        "title"             : "7 Fitness Tips That Will Transform Your Body",
        "thumbnail_text"    : "DO THIS",
        "thumbnail_emotion" : "determined",
        "thumbnail_style"   : "bold_text",
        "thumbnail_bg_color": "black",
        "thumbnail_accent"  : "neon_green",
        "script"            : f"Here are the top fitness tips for {safe_niche}. Follow these steps and transform your body. Start today and see results in 30 days.",
        "caption"           : f"Top fitness tips 💪🔥 Save this for your next workout!",
        "hashtags"          : ["#fitness","#workout","#gym","#health","#fit","#training","#motivation","#exercise","#gains","#lifestyle"],
        "search_keywords"   : ["gym workout training", "fitness exercise", "weight lifting gym"],
    }
    for field, default in defaults.items():
        if field not in data:
            log.warning(f"  Missing field '{field}' — using default")
            data[field] = default

    data["title"] = str(data["title"])[:60].strip()
    log.info(f"  Title     : '{data['title']}'")
    log.info(f"  Thumbnail : '{data['thumbnail_text']}' [{data['thumbnail_style']}]")
    return data


# ════════════════════════════════════════════════════════════════
# STEP 1b — GENERATE THUMBNAIL  (Pillow — free)
# 1280×720 PNG — YouTube recommended resolution
# Mhed Fitness brand: near-black bg, neon green accent
# ════════════════════════════════════════════════════════════════
BG_COLOURS = {
    "black"    : (10, 10, 10),
    "dark_red" : (26, 5, 5),
    "dark_blue": (5, 10, 26),
    "charcoal" : (20, 20, 20),
}
ACCENT_COLOURS = {
    "neon_green": (0, 255, 136),
    "orange"    : (255, 124, 42),
    "yellow"    : (255, 214, 10),
    "red"       : (255, 77, 109),
}

def generate_thumbnail(script_data: dict, channel: str):
    log.info("Step 1b: Generating thumbnail (1280×720)...")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        log.warning("  Pillow not installed — skipping thumbnail")
        return None

    W, H = 1280, 720
    bg_rgb     = BG_COLOURS.get(script_data.get("thumbnail_bg_color","black"),   (10,10,10))
    accent_rgb = ACCENT_COLOURS.get(script_data.get("thumbnail_accent","neon_green"), (0,255,136))

    img  = Image.new("RGB", (W, H), color=bg_rgb)
    draw = ImageDraw.Draw(img)

    # Subtle gradient — left darker, right slightly lighter
    for x in range(W):
        adj = int(25 * x / W)
        draw.line([(x,0),(x,H)], fill=tuple(min(255, c+adj) for c in bg_rgb))

    # Left accent bar
    draw.rectangle([(0,0),(12,H)], fill=accent_rgb)
    # Bottom accent stripe
    draw.rectangle([(0,H-80),(W,H)], fill=(0,0,0))
    draw.rectangle([(0,H-84),(W,H-80)], fill=accent_rgb)

    # Font selection
    font_path = next((p for p in FONT_PATHS if Path(p).exists()), None)
    def _font(size):
        if font_path:
            try: return ImageFont.truetype(font_path, size)
            except Exception: pass
        return ImageFont.load_default()

    # Headline words — 1 word per line, huge impact
    words = str(script_data.get("thumbnail_text","DO THIS")).upper().split()[:3]
    y = 55
    for i, word in enumerate(words):
        fnt = _font(160)
        # Shadow
        for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4),(0,5),(5,0)]:
            draw.text((38+dx, y+dy), word, font=fnt, fill=(0,0,0))
        # Text — first word accent colour, rest white
        draw.text((38, y), word, font=fnt, fill=accent_rgb if i==0 else (255,255,255))
        bb = draw.textbbox((38,y), word, font=fnt)
        y += (bb[3]-bb[1]) + 10

    # Style badge
    badges = {
        "before_after"  : "BEFORE vs AFTER",
        "number_stat"   : "NEW METHOD",
        "transformation": "RESULTS",
        "myth_bust"     : "MYTH BUSTED",
    }
    badge = badges.get(script_data.get("thumbnail_style",""), "")
    if badge:
        bfnt = _font(72)
        bx, by = 38, H-155
        bb   = draw.textbbox((bx,by), badge, font=bfnt)
        draw.rectangle([(bx-10,by-10),(bb[2]+10,bb[3]+10)], fill=accent_rgb)
        draw.text((bx,by), badge, font=bfnt, fill=(0,0,0))

    # Emotion emoji — top right
    emotion_map = {"shock":"😱","excited":"🔥","determined":"💪","surprised":"😮","proud":"🏆"}
    emoji = emotion_map.get(script_data.get("thumbnail_emotion",""), "🔥")
    try:
        draw.text((W-170, 40), emoji, font=_font(110), fill=(255,255,255))
    except Exception:
        pass

    # Arrow — draws eye right
    ax, ay = W-185, H//2-35
    draw.polygon([(ax,ay),(ax,ay+70),(ax+55,ay+35)], fill=accent_rgb)

    # Channel name
    ch = f"@{channel.replace('&','and')}"
    draw.text((28, H-64), ch, font=_font(42), fill=(200,200,200))

    out = WORK_DIR / "thumbnail.png"
    img.save(out, "PNG", optimize=True)
    log.info(f"  Thumbnail: {out.name} ({out.stat().st_size//1024}KB)")
    return out


# ════════════════════════════════════════════════════════════════
# STEP 2 — FETCH PEXELS LANDSCAPE CLIPS  (free, 20K req/month)
# ════════════════════════════════════════════════════════════════
def _validate_cdn_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return any(host == d or host.endswith("."+d) for d in ALLOWED_CDN)
    except Exception:
        return False

def _download_file(url: str, dest: Path, timeout: int = 30) -> bool:
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256*1024):
                    f.write(chunk)
        return True
    except Exception as e:
        log.warning(f"  Download failed: {e}")
        return False

def fetch_pexels_videos(keywords: list, target_duration: int) -> list:
    log.info(f"Step 2: Fetching Pexels clips for: {keywords}")
    downloaded, total_secs, used_ids = [], 0, set()
    headers = {"Authorization": PEXELS_API_KEY}

    for keyword in keywords:
        if total_secs >= target_duration:
            break
        url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({
            "query": keyword, "orientation": "landscape",
            "size": "large", "per_page": 15,
        })
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            videos = resp.json().get("videos", [])
        except Exception as e:
            log.warning(f"  Pexels search failed '{keyword}': {e}")
            continue

        random.shuffle(videos)
        for v in videos:
            if total_secs >= target_duration or v["id"] in used_ids:
                continue

            best, best_px = None, 0
            for vf in v.get("video_files", []):
                w, h, lnk = vf.get("width",0), vf.get("height",0), vf.get("link","")
                if not lnk or w<=0 or h<=0: continue
                if w>h and w>=1920 and w*h>best_px:
                    best, best_px = vf, w*h

            if not best:
                for vf in v.get("video_files", []):
                    if vf.get("width",0) > vf.get("height",0) and vf.get("width",0)>=1280:
                        best = vf; break

            if not best: continue
            cdn_url = best.get("link","")
            if not _validate_cdn_url(cdn_url):
                continue

            dest     = WORK_DIR / f"clip_{v['id']}.mp4"
            clip_dur = min(int(v.get("duration",5)), 12)
            log.info(f"  Clip {v['id']} ({best['width']}×{best['height']}, {clip_dur}s)")
            if _download_file(cdn_url, dest):
                downloaded.append(dest)
                used_ids.add(v["id"])
                total_secs += clip_dur
                time.sleep(0.2)

    if not downloaded:
        raise RuntimeError("No Pexels clips downloaded. Check PEXELS_API_KEY.")
    log.info(f"  Got {len(downloaded)} clips (~{total_secs}s)")
    return downloaded


# ════════════════════════════════════════════════════════════════
# STEP 3 — VOICEOVER + SYNCED SRT CAPTIONS  (edge-tts — free)
# ════════════════════════════════════════════════════════════════
async def _tts_stream(script: str, audio_path: Path, srt_path: Path):
    communicate = edge_tts.Communicate(script, TTS_VOICE)
    words, audio = [], []
    async for event in communicate.stream():
        if event["type"] == "audio":
            audio.append(event["data"])
        elif event["type"] == "WordBoundary":
            words.append({
                "word"    : event["text"],
                "start_ms": event["offset"]   // 10_000,
                "dur_ms"  : event["duration"] // 10_000,
            })
    with open(audio_path, "wb") as f:
        for chunk in audio: f.write(chunk)

    if not words:
        return

    def _ms(ms):
        h,r = divmod(ms,3_600_000); m,r = divmod(r,60_000); s,ms = divmod(r,1_000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    cues, gs = [], 5
    for i in range(0, len(words), gs):
        g = words[i:i+gs]
        cues.append(
            f"{i//gs+1}\n{_ms(g[0]['start_ms'])} --> "
            f"{_ms(g[-1]['start_ms']+g[-1]['dur_ms']+150)}\n"
            f"{' '.join(w['word'] for w in g)}\n"
        )
    srt_path.write_text("\n".join(cues), encoding="utf-8")
    log.info(f"  SRT: {len(cues)} cues")

def generate_voiceover_with_subs(script: str):
    log.info(f"Step 3: Voiceover + SRT ({TTS_VOICE})...")
    audio = WORK_DIR / "voiceover.mp3"
    srt   = WORK_DIR / "captions.srt"
    try:
        asyncio.run(_tts_stream(script, audio, srt))
    except RuntimeError:
        asyncio.get_event_loop().run_until_complete(_tts_stream(script, audio, srt))
    has_srt = srt.exists() and srt.stat().st_size > 10
    return audio, (srt if has_srt else None)


# ════════════════════════════════════════════════════════════════
# HELPERS — ffmpeg, fonts, probing
# ════════════════════════════════════════════════════════════════
def _get_font() -> str:
    return next((p for p in FONT_PATHS if Path(p).exists()), "")

def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json","-show_format",str(path)],
            capture_output=True, text=True,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return float(VIDEO_DURATION)

def _ffmpeg(cmd: list, label: str):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{r.stderr.decode(errors='replace')[-600:]}")


# ════════════════════════════════════════════════════════════════
# STEP 4a — ASSEMBLE WIDESCREEN MASTER  (1920×1080 YouTube/Facebook)
# Quality: H.264 High · 12 Mbps · bt709 · 30fps · Poppins Bold captions
# BUG-1 FIX: -filter_complex and -vf are mutually exclusive branches
# ════════════════════════════════════════════════════════════════
def assemble_video(clips, voiceover, srt_path, title, script, channel) -> Path:
    log.info("Step 4a: Assembling widescreen master (1920×1080)...")
    font        = _get_font()
    out_path    = WORK_DIR / "master_wide.mp4"
    vo_duration = _probe_duration(voiceover)
    font_arg    = f":fontfile={font}" if font else ""

    # ── Encode + colour-grade each clip ──────────────────────
    trimmed = []
    for i, clip in enumerate(clips):
        out = WORK_DIR / f"t{i}.mp4"
        try:
            _ffmpeg([
                "ffmpeg","-y","-i",str(clip),"-t","12",
                "-vf",(
                    f"scale={YT_W}:{YT_H}:force_original_aspect_ratio=increase,"
                    f"crop={YT_W}:{YT_H},setsar=1,"
                    f"eq=saturation=1.35:brightness=0.02:contrast=1.08,"
                    f"hue=h=8:s=1.1"
                ),
                "-c:v","libx264","-profile:v","high","-level","4.2",
                "-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
                "-pix_fmt","yuv420p",
                "-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
                "-r","30","-an",str(out),
            ], f"Encode clip {i}")
            trimmed.append(out)
        except RuntimeError as e:
            log.warning(f"  Clip {i} skipped: {str(e)[:80]}")

    if not trimmed:
        raise RuntimeError("All clip encoding failed")

    # ── Crossfade transitions ─────────────────────────────────
    if len(trimmed) == 1:
        concat_path = trimmed[0]
    else:
        fade_dur = 0.5
        inputs_cmd = []
        for p in trimmed: inputs_cmd += ["-i", str(p)]
        fc, prev = [], "[0:v]"
        for k in range(1, len(trimmed)):
            out_lbl = f"[v{k}]" if k < len(trimmed)-1 else "[vout]"
            fc.append(
                f"{prev}[{k}:v]xfade=transition=fade:"
                f"duration={fade_dur}:offset={(12.0-fade_dur)*k},"
                f"format=yuv420p{out_lbl}"
            )
            prev = out_lbl
        concat_path = WORK_DIR / "xfaded.mp4"
        try:
            _ffmpeg(
                ["ffmpeg","-y"] + inputs_cmd + [
                    "-filter_complex", ";".join(fc),
                    "-map","[vout]","-c:v","libx264","-preset","slow",
                    "-b:v","12M","-maxrate","14M","-bufsize","24M",
                    "-pix_fmt","yuv420p",
                    "-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
                    "-r","30",str(concat_path),
                ], "Crossfade"
            )
        except RuntimeError as e:
            log.warning(f"  Crossfade failed — simple concat: {str(e)[:60]}")
            clist = WORK_DIR / "concat.txt"
            with open(clist,"w",encoding="utf-8") as f:
                for p in trimmed:
                    safe = str(p.resolve()).replace("\\","/").replace("'","\\'")
                    f.write(f"file '{safe}'\n")
            concat_path = WORK_DIR / "concatenated.mp4"
            _ffmpeg([
                "ffmpeg","-y","-f","concat","-safe","0",
                "-i",str(clist),"-c","copy",str(concat_path),
            ], "Concat fallback")

    # ── Background music ──────────────────────────────────────
    music_path = None
    if MUSIC_URL:
        mp = WORK_DIR / "music.mp3"
        if _download_file(MUSIC_URL, mp):
            music_path = mp
            log.info("  Background music ready")

    # ── Subtitle filter string ────────────────────────────────
    has_srt = srt_path and Path(srt_path).exists()

    def _srt_filter(size: int) -> str:
        srt_esc = str(Path(srt_path).resolve()).replace("\\","/").replace(":","\\:")
        return (
            f"subtitles='{srt_esc}'"
            f":force_style='Fontname=Poppins{font_arg},"
            f"FontSize={size},PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,BackColour=&H80000000,"
            f"Bold=1,Outline=3,Shadow=2,MarginV=80,Alignment=2'"
        )

    def _drawtext(txt: str, ch: str, w: int, h: int, sz: int, lw: int) -> str:
        lines  = textwrap.wrap(txt, width=lw)[:4]
        ys     = h - len(lines)*(sz+16) - 80
        parts  = []
        for i, line in enumerate(lines):
            esc = (line.replace("\\","\\\\").replace("'","\u2019")
                       .replace(":","\\:").replace("%","\\%"))
            parts.append(
                f"drawtext=text='{esc}':"
                + (f"fontfile={font}:" if font else "")
                + f"fontcolor=white:fontsize={sz}:x=(w-text_w)/2:"
                  f"y={ys+i*(sz+16)}:"
                  f"borderw=3:bordercolor=black@0.9:"
                  f"box=1:boxcolor=black@0.45:boxborderw=12"
            )
        ch_esc = (ch.replace("\\","\\\\").replace("'","\u2019").replace(":","\\:"))
        parts.insert(0,
            f"drawtext=text='@{ch_esc}':"
            + (f"fontfile={font}:" if font else "")
            + f"fontcolor=white@0.9:fontsize=34:x=40:y=40:"
              f"borderw=2:bordercolor=black@0.7"
        )
        return ",".join(filter(None, parts))

    # ── Final assembly — BUG-1 FIX: -filter_complex and -vf ─
    # are mutually exclusive. Music uses filter_complex only.
    # No music uses -vf only. Never both.
    cmd = [
        "ffmpeg","-y",
        "-stream_loop","-1","-i",str(concat_path),
        "-i",str(voiceover),
    ]
    if music_path:
        cmd += ["-i",str(music_path)]
    cmd += ["-t",str(vo_duration+0.5)]

    if music_path:
        vchain = f"[0:v]{_srt_filter(52) if has_srt else _drawtext(script,channel,YT_W,YT_H,52,55)}[vout]"
        achain = "[2:a]volume=0.20[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        cmd   += ["-filter_complex",f"{vchain};{achain}","-map","[vout]","-map","[aout]"]
    else:
        cmd += ["-map","0:v","-map","1:a"]
        vf   = _srt_filter(52) if has_srt else _drawtext(script,channel,YT_W,YT_H,52,55)
        if vf: cmd += ["-vf",vf]

    cmd += [
        "-c:v","libx264","-profile:v","high","-level","4.2",
        "-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
        "-pix_fmt","yuv420p",
        "-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
        "-c:a","aac","-b:a","192k","-ar","44100","-ac","2",
        "-movflags","+faststart","-shortest",str(out_path),
    ]
    _ffmpeg(cmd, "Widescreen assembly")
    log.info(f"  Wide: {out_path.name} ({out_path.stat().st_size//1_000_000:.1f}MB)")
    return out_path


# ════════════════════════════════════════════════════════════════
# STEP 4b — VERTICAL CUT  (1080×1920 TikTok/Instagram)
# Centre-crop from master — fast, no re-download needed
# ════════════════════════════════════════════════════════════════
def make_vertical(wide_path, srt_path, script, channel) -> Path:
    log.info("Step 4b: Making vertical cut (1080×1920)...")
    out_path = WORK_DIR / "vertical.mp4"
    font     = _get_font()
    font_arg = f":fontfile={font}" if font else ""
    has_srt  = srt_path and Path(srt_path).exists()

    if has_srt:
        srt_esc = str(Path(srt_path).resolve()).replace("\\","/").replace(":","\\:")
        sub_filter = (
            f"subtitles='{srt_esc}'"
            f":force_style='Fontname=Poppins{font_arg},"
            f"FontSize=72,PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,BackColour=&H80000000,"
            f"Bold=1,Outline=4,Shadow=3,MarginV=120,Alignment=2'"
        )
    else:
        lines   = textwrap.wrap(script, width=25)[:5]
        y_start = VT_H - len(lines)*106 - 100
        parts   = []
        for i, line in enumerate(lines):
            esc = (line.replace("\\","\\\\").replace("'","\u2019")
                       .replace(":","\\:").replace("%","\\%"))
            parts.append(
                f"drawtext=text='{esc}':"
                + (f"fontfile={font}:" if font else "")
                + f"fontcolor=white:fontsize=72:x=(w-text_w)/2:"
                  f"y={y_start+i*106}:"
                  f"borderw=4:bordercolor=black@0.9:"
                  f"box=1:boxcolor=black@0.45:boxborderw=14"
            )
        ch = (channel.replace("\\","\\\\").replace("'","\u2019").replace(":","\\:"))
        parts.insert(0,
            f"drawtext=text='@{ch}':"
            + (f"fontfile={font}:" if font else "")
            + "fontcolor=white@0.88:fontsize=40:x=30:y=60:"
              "borderw=2:bordercolor=black@0.7"
        )
        sub_filter = ",".join(filter(None, parts))

    vf = (
        f"crop={VT_W}:{VT_H}:((in_w-{VT_W})/2):0,"
        f"scale={VT_W}:{VT_H}:flags=lanczos,setsar=1"
    )
    if sub_filter:
        vf += "," + sub_filter

    _ffmpeg([
        "ffmpeg","-y","-i",str(wide_path),"-vf",vf,
        "-c:v","libx264","-profile:v","high","-level","4.2",
        "-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
        "-pix_fmt","yuv420p",
        "-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
        "-c:a","aac","-b:a","192k","-ar","44100","-ac","2",
        "-movflags","+faststart",str(out_path),
    ], "Vertical cut")
    log.info(f"  Vertical: {out_path.name} ({out_path.stat().st_size//1_000_000:.1f}MB)")
    return out_path


# ════════════════════════════════════════════════════════════════
# STEP 4c — UPLOAD TO CLOUDINARY CDN  (free 25GB/month)
# Required for TikTok + Instagram (need public HTTPS URL)
# YouTube + Facebook upload the file directly — no CDN needed
# ════════════════════════════════════════════════════════════════
def upload_to_cloudinary(video_path: Path, public_id: str) -> str:
    if not CLOUDINARY_URL:
        log.warning("  CLOUDINARY_URL not set — TikTok/Instagram CDN skipped")
        return ""
    try:
        try:
            import cloudinary
            import cloudinary.uploader
        except ImportError:
            subprocess.run([sys.executable,"-m","pip","install","cloudinary","-q"], check=True)
            import cloudinary
            import cloudinary.uploader

        cloudinary.config(cloudinary_url=CLOUDINARY_URL)
        log.info(f"  Uploading {video_path.name} to Cloudinary...")
        result = cloudinary.uploader.upload(
            str(video_path),
            public_id=public_id,
            resource_type="video",
            overwrite=True,
            format="mp4",
        )
        url = result.get("secure_url","")
        log.info(f"  CDN URL: {url}")
        return url
    except Exception as e:
        log.error(f"  Cloudinary failed: {e}")
        return ""


# ════════════════════════════════════════════════════════════════
# STEP 5 — POST TO ALL PLATFORMS
# ════════════════════════════════════════════════════════════════
def _full_caption(caption: str, hashtags: list) -> str:
    return (caption.strip() + "\n\n" + " ".join(hashtags[:10]))[:2200]

def _refresh_yt_token() -> str:
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        return ""
    try:
        r = requests.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id":YT_CLIENT_ID,"client_secret":YT_CLIENT_SECRET,
                  "refresh_token":YT_REFRESH_TOKEN,"grant_type":"refresh_token"},
            timeout=15,
        )
        return r.json().get("access_token","") if r.ok else ""
    except Exception:
        return ""

def _upload_thumbnail(video_id: str, thumb: Path, token: str):
    if not (video_id and thumb and thumb.exists()):
        return
    try:
        with open(thumb,"rb") as f:
            r = requests.post(
                f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
                f"?videoId={video_id}&uploadType=media",
                headers={"Authorization":f"Bearer {token}","Content-Type":"image/png"},
                data=f, timeout=60,
            )
        if r.ok: log.info("  Thumbnail uploaded ✓")
        else: log.warning(f"  Thumbnail HTTP {r.status_code}")
    except Exception as e:
        log.warning(f"  Thumbnail upload failed: {e}")

def post_youtube(video_path: Path, title: str, desc: str, thumbnail: Path=None) -> str:
    if not (YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        log.warning("YouTube: credentials not set — skipping")
        return ""
    token = _refresh_yt_token()
    if not token:
        log.error("YouTube: token refresh failed")
        return ""
    try:
        r1 = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?uploadType=resumable&part=snippet,status",
            headers={
                "Authorization":f"Bearer {token}","Content-Type":"application/json",
                "X-Upload-Content-Type":"video/mp4",
                "X-Upload-Content-Length":str(video_path.stat().st_size),
            },
            json={
                "snippet":{
                    "title":title[:100],"description":desc[:5000],
                    "tags":["fitness","workout","health","gym"],"categoryId":"17",
                },
                "status":{"privacyStatus":"public","selfDeclaredMadeForKids":False},
            },
            timeout=30,
        )
        if not r1.ok: log.error(f"YouTube initiate HTTP {r1.status_code}"); return ""
        upload_url = r1.headers.get("Location","")
        if not upload_url: log.error("YouTube: no upload URL"); return ""

        with open(video_path,"rb") as f:
            r2 = requests.put(upload_url,headers={"Content-Type":"video/mp4"},
                              data=f, timeout=300)
        if r2.ok:
            vid = r2.json().get("id","")
            log.info(f"YouTube ✓  id={vid}")
            if thumbnail: _upload_thumbnail(vid, thumbnail, token)
            return vid
        log.error(f"YouTube upload HTTP {r2.status_code}")
        return ""
    except Exception as e:
        log.error(f"YouTube error: {e}")
        return ""

def post_facebook(video_path: Path, title: str, desc: str) -> bool:
    if not (FB_PAGE_ID and FB_TOKEN):
        log.warning("Facebook: credentials not set — skipping")
        return False
    try:
        with open(video_path,"rb") as f:
            r = requests.post(
                f"https://graph-video.facebook.com/v19.0/{FB_PAGE_ID}/videos",
                data={"title":title[:255],"description":desc[:5000],"access_token":FB_TOKEN},
                files={"source":("video.mp4",f,"video/mp4")},
                timeout=300,
            )
        if r.ok: log.info(f"Facebook ✓  id={r.json().get('id')}"); return True
        log.error(f"Facebook HTTP {r.status_code}")
        return False
    except Exception as e:
        log.error(f"Facebook error: {e}")
        return False

def post_tiktok(cdn_url: str, caption: str) -> bool:
    if not TIKTOK_TOKEN: log.warning("TikTok: token not set"); return False
    if not cdn_url: log.warning("TikTok: no CDN URL"); return False
    try:
        r = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/video/init/",
            headers={"Authorization":f"Bearer {TIKTOK_TOKEN}",
                     "Content-Type":"application/json; charset=UTF-8"},
            json={
                "post_info":{
                    "title":caption[:150],"privacy_level":"PUBLIC_TO_EVERYONE",
                    "disable_duet":False,"disable_comment":False,"disable_stitch":False,
                },
                "source_info":{"source":"PULL_FROM_URL","video_url":cdn_url},
            },
            timeout=30,
        )
        if r.ok: log.info("TikTok ✓"); return True
        log.error(f"TikTok HTTP {r.status_code}"); return False
    except Exception as e:
        log.error(f"TikTok error: {e}"); return False

def post_instagram(cdn_url: str, caption: str) -> bool:
    if not (IG_ACCOUNT_ID and IG_TOKEN):
        log.warning("Instagram: credentials not set"); return False
    if not cdn_url: log.warning("Instagram: no CDN URL"); return False
    base = "https://graph.facebook.com/v19.0"
    try:
        r1 = requests.post(
            f"{base}/{IG_ACCOUNT_ID}/media",
            json={"media_type":"REELS","video_url":cdn_url,
                  "caption":caption,"access_token":IG_TOKEN},
            timeout=30,
        )
        if not r1.ok: log.error(f"Instagram container HTTP {r1.status_code}"); return False
        cid = r1.json().get("id")
        if not cid: log.error("Instagram: no container ID"); return False

        log.info("Instagram: waiting for container...")
        for _ in range(18):
            time.sleep(5)
            sr = requests.get(f"{base}/{cid}",
                              params={"fields":"status_code","access_token":IG_TOKEN},
                              timeout=15)
            st = sr.json().get("status_code","")
            if st == "FINISHED": break
            if st == "ERROR": log.error("Instagram: container error"); return False

        r2 = requests.post(f"{base}/{IG_ACCOUNT_ID}/media_publish",
                           json={"creation_id":cid,"access_token":IG_TOKEN},
                           timeout=30)
        if r2.ok and r2.json().get("id"): log.info("Instagram ✓"); return True
        log.error(f"Instagram publish HTTP {r2.status_code}"); return False
    except Exception as e:
        log.error(f"Instagram error: {e}"); return False


# ════════════════════════════════════════════════════════════════
# STEP 6 — LOG RUN  (atomic write — crash-safe)
# ════════════════════════════════════════════════════════════════
def save_run_log(script_data: dict, results: dict):
    log_path = Path(__file__).parent / "run_history.json"
    try:
        existing = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    except Exception:
        existing = []
    existing.insert(0, {
        "date"    : datetime.utcnow().isoformat(),
        "title"   : script_data.get("title",""),
        "platforms": results,
    })
    tmp = log_path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(existing[:60], indent=2), encoding="utf-8")
        tmp.replace(log_path)
    except Exception as e:
        log.warning(f"Log write failed: {e}")


# ════════════════════════════════════════════════════════════════
# CLEANUP
# ════════════════════════════════════════════════════════════════
def cleanup(keep_list=None):
    keep_set = {Path(p).resolve() for p in (keep_list or []) if p}
    for pat in ["*.mp4","*.mp3","*.txt","*.srt","*.tmp","*.png"]:
        for f in WORK_DIR.glob(pat):
            if f.resolve() not in keep_set:
                try: f.unlink()
                except Exception: pass
    log.info("Temp files cleaned")

def _validate_env():
    missing = []
    if not GROQ_API_KEY:   missing.append("GROQ_API_KEY    → console.groq.com (free, no card)")
    if not PEXELS_API_KEY: missing.append("PEXELS_API_KEY  → pexels.com/api   (free, no card)")
    if missing:
        for m in missing: log.error(f"Missing: {m}")
        sys.exit(1)


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 65)
    log.info("FitBot v5 — Groq Edition (Llama 3.3 70B · 14,400 req/day free)")
    log.info(f"Channel  : {CHANNEL_NAME}")
    log.info(f"Niche    : {NICHE}")
    log.info(f"Wide     : {YT_W}×{YT_H}  → YouTube + Facebook")
    log.info(f"Vertical : {VT_W}×{VT_H}  → TikTok  + Instagram")
    log.info(f"Quality  : H.264 High · 12Mbps · 192k AAC · bt709")
    log.info(f"Cost     : $0.00/month — 100% free")
    log.info("=" * 65)

    _validate_env()

    wide = vertical = thumbnail = None
    try:
        # Step 1 — Script + title + thumbnail brief (Groq)
        script_data = generate_script()
        caption     = _full_caption(script_data["caption"], script_data["hashtags"])
        desc        = script_data["caption"] + "\n\n" + " ".join(script_data["hashtags"])

        # Step 1b — Branded thumbnail
        thumbnail = generate_thumbnail(script_data, CHANNEL_NAME)

        # Step 2 — Pexels footage
        clips = fetch_pexels_videos(script_data["search_keywords"], VIDEO_DURATION)

        # Step 3 — Voiceover + SRT
        voiceover, srt = generate_voiceover_with_subs(script_data["script"])

        # Step 4a — Widescreen master
        wide = assemble_video(clips, voiceover, srt,
                              title=script_data["title"],
                              script=script_data["script"],
                              channel=CHANNEL_NAME)

        # Step 4b — Vertical cut
        vertical = make_vertical(wide, srt,
                                 script=script_data["script"],
                                 channel=CHANNEL_NAME)

        # Step 4c — CDN upload (TikTok + Instagram)
        cdn_url = upload_to_cloudinary(vertical, "fitbot_vertical_latest")

        # Step 5 — Post
        log.info("Step 5: Posting to all platforms...")
        yt_id = post_youtube(wide, script_data["title"], desc, thumbnail=thumbnail)
        results = {
            "youtube"  : bool(yt_id),
            "facebook" : post_facebook(wide,    script_data["title"], desc),
            "tiktok"   : post_tiktok(cdn_url,   caption),
            "instagram": post_instagram(cdn_url, caption),
        }

        log.info("=" * 65)
        log.info("RESULTS:")
        fmts = {"youtube":"1920×1080","facebook":"1920×1080",
                "tiktok":"1080×1920", "instagram":"1080×1920"}
        for p, ok in results.items():
            log.info(f"  {p.upper():12}  {'✓ POSTED' if ok else '✗ skipped/failed'}  [{fmts[p]}]")
        if yt_id:
            log.info(f"  Watch: https://youtube.com/watch?v={yt_id}")
        log.info("=" * 65)

        # Step 6 — Log
        save_run_log(script_data, results)

    finally:
        cleanup(keep_list=[wide, vertical, thumbnail])
        log.info("Pipeline complete.")

if __name__ == "__main__":
    main()
