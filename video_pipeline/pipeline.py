"""
FitBot Video Pipeline — v6 GOD MODE
=====================================
Researched April 2026 — Best free AI provider hierarchy:

PRIMARY   → Cerebras   (cloud.cerebras.ai)
  - 1,000,000 tokens/day FREE — no credit card — email only signup
  - 2,600 tokens/second on Llama 4 Scout (20x faster than GPUs)
  - OpenAI-compatible endpoint: https://api.cerebras.ai/v1
  - Sign up: cloud.cerebras.ai → Create Account → API Keys → Create

FALLBACK 1 → Groq      (console.groq.com)
  - 14,400 req/day free on llama-3.1-8b-instant
  - 300+ tokens/second
  - OpenAI-compatible endpoint: https://api.groq.com/openai/v1

FALLBACK 2 → OpenRouter (openrouter.ai)
  - 200 req/day free, no credit card, 33+ free models
  - Uses :free model variants (DeepSeek, Llama, Qwen)
  - OpenAI-compatible endpoint: https://openrouter.ai/api/v1

FALLBACK 3 → Gemini    (aistudio.google.com)
  - 1,500 req/day free, no credit card
  - Uses google-generativeai SDK (different format)

FALLBACK 4 → Script Cache
  - 30 pre-written fitness scripts rotated daily
  - Pipeline NEVER fails — always posts something

TOTAL COST: $0.00/month — all free tiers, no credit cards

Video output (dual format, one run daily):
  1920×1080 — YouTube + Facebook  (16:9 widescreen)
  1080×1920 — TikTok + Instagram  (9:16 vertical)

Quality: H.264 High · 12 Mbps · 192k AAC · bt709 · Poppins Bold
Thumbnail: 1280×720 PNG with Mhed Fitness brand colours
"""

import os, sys, json, time, random, asyncio
import logging, textwrap, hashlib, subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path

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
        logging.FileHandler(Path(__file__).parent / "pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("fitbot")

def _safe_int(val, default):
    try: return int(val)
    except: return default

# ════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════
CEREBRAS_API_KEY  = os.environ.get("CEREBRAS_API_KEY",  "")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY",      "")
OPENROUTER_API_KEY= os.environ.get("OPENROUTER_API_KEY","")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY",    "")
PEXELS_API_KEY    = os.environ.get("PEXELS_API_KEY",    "")
CLOUDINARY_URL    = os.environ.get("CLOUDINARY_URL",    "")
CHANNEL_NAME      = os.environ.get("CHANNEL_NAME",      "Mhed Fitness & Sports")
NICHE             = os.environ.get("NICHE",              "fitness and sports")
TTS_VOICE         = os.environ.get("TTS_VOICE",          "en-US-GuyNeural")
VIDEO_DURATION    = _safe_int(os.environ.get("VIDEO_DURATION","45"), 45)
MUSIC_URL         = os.environ.get("BACKGROUND_MUSIC_URL","")

TIKTOK_TOKEN      = os.environ.get("TIKTOK_ACCESS_TOKEN",    "")
IG_ACCOUNT_ID     = os.environ.get("INSTAGRAM_ACCOUNT_ID",   "")
IG_TOKEN          = os.environ.get("INSTAGRAM_ACCESS_TOKEN",  "")
YT_CLIENT_ID      = os.environ.get("YOUTUBE_CLIENT_ID",       "")
YT_CLIENT_SECRET  = os.environ.get("YOUTUBE_CLIENT_SECRET",   "")
YT_REFRESH_TOKEN  = os.environ.get("YOUTUBE_REFRESH_TOKEN",   "")
FB_PAGE_ID        = os.environ.get("FACEBOOK_PAGE_ID",        "")
FB_TOKEN          = os.environ.get("FACEBOOK_ACCESS_TOKEN",   "")

YT_W, YT_H = 1920, 1080
VT_W, VT_H = 1080, 1920

FONT_PATHS = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
ALLOWED_CDN = {
    "videos.pexels.com","player.vimeo.com","vimeo.com",
    "vod-progressive.akamaized.net","vod-adaptive.akamaized.net",
    "www.pexels.com","player.pexels.com",
}
WORK_DIR = Path(__file__).parent / "tmp"
WORK_DIR.mkdir(exist_ok=True)

# ════════════════════════════════════════════════════════════════
# AI PROVIDER HIERARCHY
# Each provider uses OpenAI-compatible format except Gemini
# ════════════════════════════════════════════════════════════════

# ── Provider definitions ──────────────────────────────────────
PROVIDERS = [
    {
        "name"    : "Cerebras",
        "key_env" : "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        "models"  : [
            "llama-3.3-70b",      # Best quality on Cerebras
            "llama3.1-70b",       # Stable fallback
            "llama3.1-8b",        # Lightweight — highest quota
        ],
        "signup"  : "cloud.cerebras.ai — email only, no card",
        "limit"   : "1,000,000 tokens/day",
    },
    {
        "name"    : "Groq",
        "key_env" : "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "models"  : [
            "llama-3.3-70b-versatile",
            "llama3-70b-8192",
            "llama-3.1-8b-instant",
            "llama3-8b-8192",
        ],
        "signup"  : "console.groq.com — email only, no card",
        "limit"   : "14,400 req/day",
    },
    {
        "name"    : "OpenRouter",
        "key_env" : "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "models"  : [
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-r1:free",
            "deepseek/deepseek-v3:free",
            "qwen/qwen3-235b-a22b:free",
            "meta-llama/llama-3.1-8b-instruct:free",
        ],
        "signup"  : "openrouter.ai — email only, no card",
        "limit"   : "200 req/day free",
    },
]

def _call_openai_compatible(base_url: str, api_key: str, model: str,
                             prompt: str, provider_name: str,
                             max_retries: int = 3) -> dict:
    """Call any OpenAI-compatible endpoint with retry + backoff."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type" : "application/json",
    }
    if provider_name == "OpenRouter":
        headers["HTTP-Referer"] = "https://github.com/fitbot-ai"
        headers["X-Title"]      = "FitBot AI"

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model"      : model,
                    "messages"   : [
                        {
                            "role"   : "system",
                            "content": (
                                "You are a professional fitness YouTube content strategist. "
                                "Always respond with valid JSON only. No markdown. No explanation."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature"    : 0.8,
                    "max_tokens"     : 1200,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )

            if resp.status_code == 429:
                after = int(resp.headers.get("retry-after", 10 * attempt))
                if attempt < max_retries:
                    log.warning(f"  {provider_name}/{model} rate limited — waiting {after}s")
                    time.sleep(after)
                    continue
                return None  # signal: try next model

            if resp.status_code in (401, 403):
                log.error(f"  {provider_name} API key invalid — skipping provider")
                return "SKIP_PROVIDER"

            if resp.status_code == 404:
                log.warning(f"  {provider_name}/{model} not found — try next model")
                return None

            if not resp.ok:
                log.warning(f"  {provider_name}/{model} HTTP {resp.status_code}")
                if attempt < max_retries:
                    time.sleep(5 * attempt)
                    continue
                return None

            raw  = resp.json()["choices"][0]["message"]["content"].strip()
            raw  = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(raw)

        except requests.exceptions.Timeout:
            log.warning(f"  {provider_name}/{model} timeout (attempt {attempt})")
            if attempt < max_retries: time.sleep(5)
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"  {provider_name}/{model} parse error: {e}")
            if attempt < max_retries: time.sleep(3)
        except Exception as e:
            log.warning(f"  {provider_name}/{model} error: {str(e)[:80]}")
            if attempt < max_retries: time.sleep(5)

    return None  # all retries failed

def _call_gemini(prompt: str) -> dict:
    """Call Gemini as fallback — uses google-generativeai SDK."""
    if not GEMINI_API_KEY:
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        log.warning("  google-generativeai not installed — skipping Gemini")
        return None

    GEMINI_MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-2.0-flash-lite",
    ]

    genai.configure(api_key=GEMINI_API_KEY)

    for model_name in GEMINI_MODELS:
        for attempt in range(1, 3):
            try:
                model    = genai.GenerativeModel(model_name)
                response = model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        max_output_tokens=1200,
                        temperature=0.8,
                    ),
                )
                raw = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                log.info(f"  Gemini success: {model_name}")
                return json.loads(raw)
            except Exception as e:
                err = str(e).lower()
                if "quota" in err or "429" in err or "resource_exhausted" in err:
                    log.warning(f"  Gemini/{model_name} quota — trying next model")
                    break  # next model
                elif "404" in err or "not found" in err:
                    log.warning(f"  Gemini/{model_name} not found — trying next model")
                    break
                else:
                    if attempt < 2: time.sleep(5)

    return None

def call_ai(prompt: str) -> dict:
    """
    Master AI caller — tries every provider in priority order.
    Cerebras → Groq → OpenRouter → Gemini → Script Cache
    Never crashes. Always returns a valid dict.
    """
    # ── Try Cerebras, Groq, OpenRouter ───────────────────────
    for provider in PROVIDERS:
        key = os.environ.get(provider["key_env"], "")
        if not key:
            log.info(f"  {provider['name']}: no key set — skipping")
            log.info(f"    Get free key: {provider['signup']}")
            continue

        log.info(f"  Trying {provider['name']} ({provider['limit']})...")

        for model in provider["models"]:
            result = _call_openai_compatible(
                provider["base_url"], key, model,
                prompt, provider["name"]
            )
            if result == "SKIP_PROVIDER":
                break  # bad key — skip entire provider
            if result is not None:
                return result  # success
            # None = try next model

    # ── Try Gemini ────────────────────────────────────────────
    if GEMINI_API_KEY:
        log.info("  Trying Gemini (fallback 3)...")
        result = _call_gemini(prompt)
        if result is not None:
            return result

    # ── Script cache — pipeline never fails ──────────────────
    log.warning("All AI providers exhausted — using script cache")
    log.warning("To fix: sign up at cloud.cerebras.ai (free, email only, no card)")
    return _get_cached_script()


# ════════════════════════════════════════════════════════════════
# SCRIPT CACHE — 30 pre-written scripts rotated daily
# ════════════════════════════════════════════════════════════════
SCRIPT_CACHE = [
    {"title":"7 Exercises That Build Muscle Twice as Fast","thumbnail_text":"DO THIS","thumbnail_emotion":"determined","thumbnail_style":"bold_text","thumbnail_bg_color":"black","thumbnail_accent":"neon_green","script":"Stop wasting time on exercises that barely work. These 7 moves activate more muscle fibres in less time. Add them today and feel the difference in one week.","caption":"7 exercises that actually build muscle fast 💪🔥 Stop wasting time — these are the moves that matter. Save this for your next workout!","hashtags":["#fitness","#workout","#gym","#muscle","#gains","#training","#health","#fit","#bodybuilding","#exercise"],"search_keywords":["gym workout barbell","weight training muscle","bodybuilding exercise"]},
    {"title":"Stop Skipping This If You Want Six Pack Abs","thumbnail_text":"BIG MISTAKE","thumbnail_emotion":"shock","thumbnail_style":"myth_bust","thumbnail_bg_color":"dark_red","thumbnail_accent":"orange","script":"Most people chase abs with crunches alone and never see results. The real secret is core activation combined with diet timing. Here is exactly what to do instead.","caption":"The truth about six pack abs nobody tells you 😤💪 It is not just crunches. Fix this and your core transforms!","hashtags":["#abs","#sixpack","#core","#fitness","#workout","#gym","#health","#fatloss","#training","#fitnessmotivation"],"search_keywords":["core workout abs training","six pack exercise","fitness ab workout"]},
    {"title":"The Real Reason You Are Not Losing Fat","thumbnail_text":"REAL TRUTH","thumbnail_emotion":"surprised","thumbnail_style":"myth_bust","thumbnail_bg_color":"charcoal","thumbnail_accent":"yellow","script":"You are training hard but the fat is not moving. The problem is not your workout — it is your recovery. Fix your sleep first and watch everything change.","caption":"Why you are not losing fat even when you train hard 😮🔥 The answer might surprise you. Watch till the end!","hashtags":["#fatloss","#weightloss","#fitness","#nutrition","#health","#gym","#workout","#metabolism","#diet","#transformation"],"search_keywords":["fat loss cardio workout","weight loss exercise","running fitness"]},
    {"title":"5 Proven Moves for Faster Muscle Recovery","thumbnail_text":"RECOVER FAST","thumbnail_emotion":"proud","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"neon_green","script":"Sore muscles are slowing your progress. These 5 recovery moves reduce soreness significantly. Do them after every session and train harder every day.","caption":"5 moves that speed up muscle recovery 💪⚡ Do these after every workout. Save this post!","hashtags":["#recovery","#musclerecovery","#fitness","#gym","#workout","#mobility","#health","#training","#gains","#stretching"],"search_keywords":["muscle recovery stretch","post workout mobility","yoga fitness stretch"]},
    {"title":"How To Build Strength In 7 Minutes Every Day","thumbnail_text":"7 MINUTES","thumbnail_emotion":"excited","thumbnail_style":"number_stat","thumbnail_bg_color":"dark_blue","thumbnail_accent":"orange","script":"No time to train? Seven minutes is all you need. This circuit hits every major muscle group fast. No equipment. No excuses. Just results.","caption":"7 minute workout that actually builds strength 🔥💪 No gym needed. Try it right now!","hashtags":["#homeworkout","#quickworkout","#fitness","#strength","#noequipment","#workout","#health","#gym","#training","#fitnessmotivation"],"search_keywords":["home workout bodyweight","quick fitness circuit","no equipment training"]},
    {"title":"Most People Train Legs Wrong — Here Is the Fix","thumbnail_text":"WRONG WAY","thumbnail_emotion":"shock","thumbnail_style":"myth_bust","thumbnail_bg_color":"black","thumbnail_accent":"red","script":"Leg day is the most misunderstood session in the gym. Most people focus only on squats and miss key muscles. Fix this and your legs grow twice as fast.","caption":"You have been training legs wrong 😤🦵 Fix these mistakes and your leg gains will explode!","hashtags":["#legday","#squats","#legworkout","#fitness","#gym","#training","#muscle","#gains","#workout","#health"],"search_keywords":["leg day squat workout","lower body training","gym leg press exercise"]},
    {"title":"9 Secret Nutrition Rules Top Athletes Follow","thumbnail_text":"TOP SECRET","thumbnail_emotion":"determined","thumbnail_style":"number_stat","thumbnail_bg_color":"charcoal","thumbnail_accent":"neon_green","script":"Elite athletes eat differently to everyone else. Not just what they eat — when and how. These 9 rules changed everything for me.","caption":"9 nutrition rules elite athletes actually follow 🥗💪 Which one surprised you most?","hashtags":["#nutrition","#athletenutrition","#fitness","#health","#diet","#protein","#gym","#performance","#gains","#mealprep"],"search_keywords":["healthy meal prep fitness","athlete nutrition food","protein meal fitness"]},
    {"title":"3 Morning Habits That Transform Your Body Fast","thumbnail_text":"DO THIS AM","thumbnail_emotion":"excited","thumbnail_style":"transformation","thumbnail_bg_color":"black","thumbnail_accent":"yellow","script":"What you do in the first 30 minutes of your morning decides your entire day. These three habits take five minutes and change your body from the inside out.","caption":"3 morning habits that transform your fitness 🌅💪 I did this for 30 days. The results shocked me!","hashtags":["#morningroutine","#fitness","#health","#habits","#transformation","#workout","#gym","#wellness","#motivation","#lifestyle"],"search_keywords":["morning workout sunrise","fitness healthy morning","outdoor exercise morning"]},
    {"title":"The 5-Minute Fix for Tight Hips and Back Pain","thumbnail_text":"FIX THIS","thumbnail_emotion":"proud","thumbnail_style":"bold_text","thumbnail_bg_color":"dark_blue","thumbnail_accent":"orange","script":"Tight hips cause back pain, poor posture, and weak lifts. Five minutes of this routine every day fixes everything. Do it before your workout.","caption":"Fix tight hips and back pain in 5 minutes 🙌💪 Save this and do it before your next workout!","hashtags":["#hipflexors","#backpain","#mobility","#flexibility","#fitness","#health","#gym","#stretching","#posture","#workout"],"search_keywords":["hip flexor stretch yoga","back pain relief stretch","mobility flexibility routine"]},
    {"title":"Stop Doing Cardio Wrong — This Burns 3x More Fat","thumbnail_text":"3X FASTER","thumbnail_emotion":"shock","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"red","script":"Steady state cardio is the slowest way to burn fat. Switch to this interval method and burn three times more calories in half the time.","caption":"You have been doing cardio wrong 🏃🔥 This burns 3x more fat in half the time. Save this!","hashtags":["#cardio","#fatloss","#HIIT","#fitness","#workout","#weightloss","#gym","#training","#health","#burnfat"],"search_keywords":["HIIT cardio sprint","interval training run","treadmill cardio gym"]},
    {"title":"7 Signs You Are Overtraining Without Knowing It","thumbnail_text":"WARNING","thumbnail_emotion":"surprised","thumbnail_style":"myth_bust","thumbnail_bg_color":"dark_red","thumbnail_accent":"yellow","script":"More training does not always mean better results. These 7 signs mean your body is begging for rest. Ignore them and your progress stops completely.","caption":"7 signs you are overtraining 😮⚠️ Number 4 shocked me. Are you making these mistakes?","hashtags":["#overtraining","#recovery","#fitness","#gym","#workout","#health","#training","#rest","#gains","#sports"],"search_keywords":["gym workout fatigue","fitness recovery rest","training recovery exercise"]},
    {"title":"3 Proven Exercises That Fix Bad Posture Fast","thumbnail_text":"FIX POSTURE","thumbnail_emotion":"determined","thumbnail_style":"transformation","thumbnail_bg_color":"charcoal","thumbnail_accent":"neon_green","script":"Bad posture makes you look weaker and feel worse. These three exercises correct years of desk damage in just 10 minutes a day.","caption":"Fix bad posture with these 3 exercises 🙆💪 10 minutes a day. Save this and start tonight!","hashtags":["#posture","#backpain","#fitness","#health","#gym","#exercise","#mobility","#stretching","#wellness","#workout"],"search_keywords":["posture correction exercise","back stretch workout","spine mobility yoga"]},
    {"title":"How To Gain Muscle Fast Without the Gym","thumbnail_text":"NO GYM GAINS","thumbnail_emotion":"excited","thumbnail_style":"bold_text","thumbnail_bg_color":"black","thumbnail_accent":"orange","script":"You do not need a gym to build serious muscle. Bodyweight training done right triggers the same muscle growth as weight training.","caption":"Build muscle without a gym 💪🏠 No membership needed. Save this and start today!","hashtags":["#homeworkout","#noequipment","#muscle","#fitness","#bodyweight","#calisthenics","#gains","#workout","#health","#training"],"search_keywords":["bodyweight workout outdoor","calisthenics training park","home fitness no equipment"]},
    {"title":"The Truth About Protein That Nobody Tells You","thumbnail_text":"PROTEIN TRUTH","thumbnail_emotion":"shock","thumbnail_style":"myth_bust","thumbnail_bg_color":"dark_blue","thumbnail_accent":"yellow","script":"You have been told to eat more protein but nobody told you when. Protein timing matters as much as quantity. This change made my gains 40 percent faster.","caption":"The protein truth that changed my gains 😤💪 Nobody talks about this. Comment yes or no!","hashtags":["#protein","#nutrition","#muscle","#fitness","#gym","#gains","#diet","#health","#workout","#mealprep"],"search_keywords":["protein food nutrition meal","muscle building diet food","healthy protein meal prep"]},
    {"title":"5 Gym Mistakes Beginners Make Every Single Day","thumbnail_text":"AVOID THIS","thumbnail_emotion":"determined","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"red","script":"Starting at the gym is exciting but these 5 mistakes will destroy your progress before it begins. I made all of them. Learn from me.","caption":"5 gym mistakes every beginner makes 💪😤 Share this with a friend who just started training!","hashtags":["#beginners","#gymtips","#fitness","#workout","#gym","#training","#health","#gains","#muscle","#fitnessmotivation"],"search_keywords":["beginner gym workout","fitness training start","gym exercise technique"]},
    {"title":"9 Foods That Speed Up Muscle Growth Naturally","thumbnail_text":"EAT THESE","thumbnail_emotion":"proud","thumbnail_style":"number_stat","thumbnail_bg_color":"charcoal","thumbnail_accent":"neon_green","script":"Supplements are expensive and mostly unnecessary. These 9 everyday foods trigger more muscle growth than most supplements on the market.","caption":"9 foods that build muscle faster than supplements 🥗💪 Add these to your grocery list now!","hashtags":["#musclebuilding","#nutrition","#food","#fitness","#health","#diet","#gains","#gym","#protein","#mealprep"],"search_keywords":["healthy food nutrition kitchen","muscle building meal","clean eating fitness food"]},
    {"title":"How I Lost Body Fat in 30 Days With This Method","thumbnail_text":"30 DAYS","thumbnail_emotion":"proud","thumbnail_style":"transformation","thumbnail_bg_color":"black","thumbnail_accent":"orange","script":"I changed one thing about my routine and lost significant body fat in 30 days without starving myself. Here is exactly what I did.","caption":"How I transformed my body in 30 days 🔥💪 One change. Real results. Comment if you want a full breakdown!","hashtags":["#transformation","#fatloss","#fitness","#30daychallenge","#workout","#health","#gym","#weightloss","#bodygoals","#motivation"],"search_keywords":["transformation workout fitness","30 day challenge exercise","body fat loss training"]},
    {"title":"Stop Wasting Time — Train Smarter Not Harder","thumbnail_text":"TRAIN SMART","thumbnail_emotion":"determined","thumbnail_style":"bold_text","thumbnail_bg_color":"dark_blue","thumbnail_accent":"neon_green","script":"Two hours in the gym does not beat 45 focused minutes. Smart training uses progressive overload and compound movements. Cut your time and double your results.","caption":"Train smarter not harder 💪⚡ 45 minutes beats 2 hours. Save this and optimise your workouts!","hashtags":["#smarttraining","#fitness","#gym","#workout","#efficiency","#gains","#muscle","#training","#health","#fitnessmotivation"],"search_keywords":["efficient gym workout","compound exercise barbell","smart fitness training"]},
    {"title":"The 7-Minute Abs Workout That Actually Works","thumbnail_text":"7 MIN ABS","thumbnail_emotion":"excited","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"yellow","script":"Most ab workouts waste your time. This 7-minute circuit hits every part of your core with maximum tension. Do it three times a week for real results.","caption":"7 minute abs workout that actually works 🔥💪 3x per week. Save this and try it tonight!","hashtags":["#abs","#abworkout","#core","#fitness","#sixpack","#workout","#gym","#training","#health","#fitnessmotivation"],"search_keywords":["ab workout core exercise","six pack training","core fitness exercise mat"]},
    {"title":"Why Your Chest Is Not Growing — Fix This Today","thumbnail_text":"CHEST FIX","thumbnail_emotion":"shock","thumbnail_style":"myth_bust","thumbnail_bg_color":"charcoal","thumbnail_accent":"orange","script":"If your chest has stopped growing it is not lack of effort — it is technique. Most people never fully activate the pectoral muscle. Here is the fix.","caption":"Why your chest is not growing 😤💪 Fix your technique today. Tag someone who needs this!","hashtags":["#chestworkout","#benchpress","#fitness","#gym","#muscle","#gains","#training","#pecs","#health","#workout"],"search_keywords":["chest press bench workout","pectoral muscle exercise","gym chest training barbell"]},
    {"title":"3 Science-Backed Tips for Faster Weight Loss","thumbnail_text":"SCIENCE SAYS","thumbnail_emotion":"determined","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"neon_green","script":"Forget fad diets. Science has identified exactly what triggers fat loss and it is simpler than you think. These three strategies work every time.","caption":"3 science-backed weight loss tips that actually work 🥗🔬 No fads. No gimmicks. Save this!","hashtags":["#weightloss","#science","#fatloss","#fitness","#health","#nutrition","#diet","#workout","#gym","#evidence"],"search_keywords":["weight loss workout science","nutrition fitness healthy","calorie burning exercise"]},
    {"title":"5 Stretches That Fix Muscle Tightness Overnight","thumbnail_text":"OVERNIGHT FIX","thumbnail_emotion":"proud","thumbnail_style":"bold_text","thumbnail_bg_color":"dark_blue","thumbnail_accent":"yellow","script":"Tight muscles limit your performance and cause injury. These five stretches held for 90 seconds each reset your muscle tension while you sleep.","caption":"5 stretches that fix tightness overnight 🌙💪 Do these before bed and wake up feeling different!","hashtags":["#stretching","#flexibility","#mobility","#fitness","#health","#recovery","#yoga","#workout","#gym","#nightroutine"],"search_keywords":["bedtime stretching routine","flexibility yoga night","muscle stretch recovery"]},
    {"title":"Most People Never Build Their Back — Here Is Why","thumbnail_text":"BACK TRUTH","thumbnail_emotion":"surprised","thumbnail_style":"myth_bust","thumbnail_bg_color":"black","thumbnail_accent":"red","script":"The back is the most neglected muscle group. Most people cannot even feel their lats during training. These cues fix that immediately.","caption":"The back training truth nobody talks about 😤💪 Fix your mind-muscle connection today!","hashtags":["#backworkout","#lats","#pullups","#fitness","#gym","#muscle","#training","#gains","#health","#workout"],"search_keywords":["back workout pull ups lat","deadlift back training","gym back exercise rowing"]},
    {"title":"How To Stay Consistent With Fitness — 7 Real Tips","thumbnail_text":"STAY CONSISTENT","thumbnail_emotion":"determined","thumbnail_style":"number_stat","thumbnail_bg_color":"charcoal","thumbnail_accent":"orange","script":"Motivation comes and goes but consistency is a skill. These 7 strategies make training automatic. Use them and you will never miss a workout again.","caption":"7 tips to stay consistent with fitness 💪🔥 Motivation is temporary. These habits last forever!","hashtags":["#consistency","#fitness","#motivation","#gym","#workout","#health","#habits","#discipline","#training","#mindset"],"search_keywords":["fitness motivation workout gym","consistent training discipline","gym workout determination"]},
    {"title":"9 Things Fit People Do Every Single Day","thumbnail_text":"DAILY HABITS","thumbnail_emotion":"excited","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"neon_green","script":"Being fit is not about occasional effort — it is about daily habits. These 9 things take less than 20 minutes total and separate those who get results.","caption":"9 things fit people do every day 🌅💪 Which ones are you already doing? Comment your score!","hashtags":["#fitpeople","#habits","#fitness","#health","#lifestyle","#gym","#workout","#wellness","#motivation","#discipline"],"search_keywords":["healthy lifestyle fitness morning","fit person routine exercise","wellness workout routine"]},
    {"title":"The Real Reason Your Arms Are Not Growing","thumbnail_text":"ARM TRUTH","thumbnail_emotion":"shock","thumbnail_style":"myth_bust","thumbnail_bg_color":"dark_red","thumbnail_accent":"yellow","script":"Endless curls are not the answer. Your biceps and triceps grow from heavy compound movements first. Reverse this order and your arms will grow fast.","caption":"Why your arms are not growing 😤💪 This one change doubled my arm size!","hashtags":["#armworkout","#biceps","#triceps","#fitness","#gym","#muscle","#gains","#training","#workout","#health"],"search_keywords":["arm workout bicep curl","tricep exercise gym","arm training barbell dumbbell"]},
    {"title":"5 Foods That Kill Your Fitness Progress Silently","thumbnail_text":"AVOID THESE","thumbnail_emotion":"surprised","thumbnail_style":"myth_bust","thumbnail_bg_color":"black","thumbnail_accent":"red","script":"These five foods look healthy but they are secretly destroying your training results. You are probably eating three of them. Cut them for 30 days.","caption":"5 foods killing your fitness progress 😮🍽️ Number 3 shocked me. Comment which ones you eat!","hashtags":["#nutrition","#food","#fitness","#health","#diet","#fatloss","#gym","#workout","#eating","#cleaneating"],"search_keywords":["healthy food kitchen nutrition","diet fitness clean eating","meal prep nutrition fitness"]},
    {"title":"3 Exercises That Fix Knee Pain While Building Legs","thumbnail_text":"KNEE FIX","thumbnail_emotion":"proud","thumbnail_style":"transformation","thumbnail_bg_color":"charcoal","thumbnail_accent":"neon_green","script":"Knee pain does not mean stop training. These three exercises strengthen the muscles that protect your knees while building powerful legs at the same time.","caption":"Fix knee pain and build stronger legs 🦵💪 Save this if you have knee pain!","hashtags":["#kneepain","#legworkout","#fitness","#health","#rehabilitation","#gym","#training","#mobility","#workout","#kneehealth"],"search_keywords":["knee rehab exercise stretch","leg workout low impact","physical therapy knee exercise"]},
    {"title":"How To Look Stronger Without Gaining Weight","thumbnail_text":"LOOK STRONGER","thumbnail_emotion":"proud","thumbnail_style":"transformation","thumbnail_bg_color":"dark_blue","thumbnail_accent":"orange","script":"Body recomposition — losing fat and gaining muscle simultaneously — is possible and more common than you think. Here is the exact approach.","caption":"Look stronger without the scale moving 💪⚡ Body recomposition is real. Start this week!","hashtags":["#bodyrecomposition","#recomp","#fitness","#muscle","#fatloss","#gym","#training","#health","#physique","#workout"],"search_keywords":["body recomposition workout","lean muscle fitness","physique training gym"]},
    {"title":"7 Proven Ways To Train When You Have No Energy","thumbnail_text":"LOW ENERGY FIX","thumbnail_emotion":"determined","thumbnail_style":"number_stat","thumbnail_bg_color":"black","thumbnail_accent":"yellow","script":"Some days you have zero energy but skipping trains your brain to quit. These 7 strategies get you through any workout no matter how tired you feel.","caption":"How to train when you have zero energy 💪😤 Never skip a workout again. Save this!","hashtags":["#consistency","#motivation","#fitness","#gym","#workout","#energy","#discipline","#training","#mindset","#health"],"search_keywords":["workout motivation fitness gym","training discipline exercise","gym workout energy determination"]},
    {"title":"Stop Eating Before Bed — The Truth About Timing","thumbnail_text":"EAT TIMING","thumbnail_emotion":"surprised","thumbnail_style":"myth_bust","thumbnail_bg_color":"charcoal","thumbnail_accent":"neon_green","script":"You have been told not to eat before bed but the research tells a different story. Certain foods before sleep actually improve muscle growth and fat loss.","caption":"The truth about eating before bed 😮🌙 This changed my night routine completely!","hashtags":["#nutrition","#mealtime","#fitness","#health","#muscle","#sleep","#recovery","#gym","#diet","#gains"],"search_keywords":["healthy eating nutrition kitchen","night routine fitness meal","protein shake fitness drink"]},
]

def _get_cached_script() -> dict:
    idx    = int(hashlib.md5(datetime.utcnow().strftime("%Y-%m-%d").encode()).hexdigest(), 16) % len(SCRIPT_CACHE)
    script = SCRIPT_CACHE[idx].copy()
    script["caption"] = script["caption"].replace("Mhed Fitness", CHANNEL_NAME)
    log.info(f"  Cache #{idx}: '{script['title']}'")
    return script


# ════════════════════════════════════════════════════════════════
# TITLE FORMULA ROTATION (7 proven high-CTR formulas)
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
    idx = int(hashlib.md5(datetime.utcnow().strftime("%Y-%m-%d").encode()).hexdigest(), 16) % 7
    return TITLE_FORMULAS[idx]

def _sanitize(s: str, max_len: int = 100) -> str:
    return s.replace('"','').replace('{','').replace('}','').replace('`','').strip()[:max_len]


# ════════════════════════════════════════════════════════════════
# STEP 1 — GENERATE SCRIPT
# ════════════════════════════════════════════════════════════════
def generate_script() -> dict:
    log.info("Step 1: Generating script (Cerebras → Groq → OpenRouter → Gemini → Cache)...")

    prompt = (
        f'You are a YouTube content strategist for "{_sanitize(CHANNEL_NAME)}".\n'
        f'Niche: "{_sanitize(NICHE)}"\n\n'
        f'TITLE FORMULA TODAY: {_pick_formula()}\n\n'
        'TITLE RULES: 50-60 chars max · front-load keyword · include odd number (3,5,7,9) · one power word (Proven/Secret/Real/Never/Stop/Truth/Fix) · no all-caps · no emojis\n'
        'THUMBNAIL TEXT: 1-3 bold words · under 12 total chars · different words from title · creates curiosity\n\n'
        'Return ONE valid JSON object with EXACTLY these fields:\n'
        '{"title":"50-60 char YouTube title",'
        '"thumbnail_text":"1-3 bold words",'
        '"thumbnail_emotion":"shock|excited|determined|surprised|proud",'
        '"thumbnail_style":"before_after|bold_text|number_stat|transformation|myth_bust",'
        '"thumbnail_bg_color":"black|dark_red|dark_blue|charcoal",'
        '"thumbnail_accent":"neon_green|orange|yellow|red",'
        '"script":"3-5 energetic voiceover sentences max 280 chars",'
        '"caption":"social media caption with emojis max 1800 chars",'
        '"hashtags":["10 hashtags each starting with #"],'
        '"search_keywords":["3 specific Pexels video search terms"]}'
    )

    data = call_ai(prompt)

    # Safe defaults for any missing field
    defaults = {
        "title":"7 Fitness Tips That Will Transform Your Body",
        "thumbnail_text":"DO THIS",
        "thumbnail_emotion":"determined",
        "thumbnail_style":"bold_text",
        "thumbnail_bg_color":"black",
        "thumbnail_accent":"neon_green",
        "script":f"Here are the top fitness tips for {_sanitize(NICHE)}. Follow these and transform your body. Start today and see results in 30 days.",
        "caption":f"Top fitness tips 💪🔥 Save this for your next workout!",
        "hashtags":["#fitness","#workout","#gym","#health","#fit","#training","#motivation","#exercise","#gains","#lifestyle"],
        "search_keywords":["gym workout training","fitness exercise","weight lifting gym"],
    }
    for k, v in defaults.items():
        if k not in data or not data[k]:
            data[k] = v

    data["title"] = str(data["title"])[:60].strip()
    log.info(f"  Title     : '{data['title']}'")
    log.info(f"  Thumbnail : '{data['thumbnail_text']}' [{data['thumbnail_style']}]")
    return data


# ════════════════════════════════════════════════════════════════
# STEP 1b — GENERATE THUMBNAIL  (Pillow — free, 1280×720)
# ════════════════════════════════════════════════════════════════
BG_COLOURS     = {"black":(10,10,10),"dark_red":(26,5,5),"dark_blue":(5,10,26),"charcoal":(20,20,20)}
ACCENT_COLOURS = {"neon_green":(0,255,136),"orange":(255,124,42),"yellow":(255,214,10),"red":(255,77,109)}

def generate_thumbnail(script_data: dict, channel: str):
    log.info("Step 1b: Generating thumbnail (1280×720)...")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        log.warning("  Pillow not installed — skipping thumbnail")
        return None

    W, H    = 1280, 720
    bg_rgb  = BG_COLOURS.get(script_data.get("thumbnail_bg_color","black"), (10,10,10))
    acc_rgb = ACCENT_COLOURS.get(script_data.get("thumbnail_accent","neon_green"), (0,255,136))
    img     = Image.new("RGB",(W,H),color=bg_rgb)
    draw    = ImageDraw.Draw(img)

    for x in range(W):
        adj = int(25*x/W)
        draw.line([(x,0),(x,H)], fill=tuple(min(255,c+adj) for c in bg_rgb))
    draw.rectangle([(0,0),(12,H)], fill=acc_rgb)
    draw.rectangle([(0,H-80),(W,H)], fill=(0,0,0))
    draw.rectangle([(0,H-84),(W,H-80)], fill=acc_rgb)

    font_path = next((p for p in FONT_PATHS if Path(p).exists()), None)
    def _font(sz):
        if font_path:
            try: return ImageFont.truetype(font_path, sz)
            except: pass
        return ImageFont.load_default()

    words = str(script_data.get("thumbnail_text","DO THIS")).upper().split()[:3]
    y = 55
    for i, word in enumerate(words):
        fnt = _font(155)
        for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4),(0,5)]:
            draw.text((38+dx,y+dy), word, font=fnt, fill=(0,0,0))
        draw.text((38,y), word, font=fnt, fill=acc_rgb if i==0 else (255,255,255))
        bb = draw.textbbox((38,y), word, font=fnt)
        y += (bb[3]-bb[1])+10

    badges = {"before_after":"BEFORE vs AFTER","number_stat":"NEW METHOD","transformation":"RESULTS","myth_bust":"MYTH BUSTED"}
    badge  = badges.get(script_data.get("thumbnail_style",""),"")
    if badge:
        bfnt = _font(68)
        bx,by = 38,H-150
        bb    = draw.textbbox((bx,by), badge, font=bfnt)
        draw.rectangle([(bx-10,by-10),(bb[2]+10,bb[3]+10)], fill=acc_rgb)
        draw.text((bx,by), badge, font=bfnt, fill=(0,0,0))

    emojis = {"shock":"😱","excited":"🔥","determined":"💪","surprised":"😮","proud":"🏆"}
    try:
        draw.text((W-165,40), emojis.get(script_data.get("thumbnail_emotion",""),"🔥"), font=_font(105), fill=(255,255,255))
    except: pass

    ax,ay = W-175,H//2-30
    draw.polygon([(ax,ay),(ax,ay+65),(ax+50,ay+32)], fill=acc_rgb)
    draw.text((28,H-60), f"@{channel.replace('&','and')}", font=_font(40), fill=(200,200,200))

    out = WORK_DIR / "thumbnail.png"
    img.save(out, "PNG", optimize=True)
    log.info(f"  Thumbnail: {out.name} ({out.stat().st_size//1024}KB)")
    return out


# ════════════════════════════════════════════════════════════════
# STEP 2 — FETCH PEXELS CLIPS  (free, 20K req/month)
# ════════════════════════════════════════════════════════════════
def _validate_cdn(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        return any(host==d or host.endswith("."+d) for d in ALLOWED_CDN)
    except: return False

def _download(url: str, dest: Path, timeout: int=30) -> bool:
    try:
        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(dest,"wb") as f:
                for chunk in r.iter_content(chunk_size=256*1024): f.write(chunk)
        return True
    except Exception as e:
        log.warning(f"  Download failed: {e}")
        return False

def fetch_pexels_videos(keywords: list, target: int) -> list:
    log.info(f"Step 2: Fetching Pexels clips for: {keywords}")
    downloaded, total, used = [], 0, set()
    headers = {"Authorization": PEXELS_API_KEY}

    for kw in keywords:
        if total >= target: break
        url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
            {"query":kw,"orientation":"landscape","size":"large","per_page":15})
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            videos = r.json().get("videos",[])
        except Exception as e:
            log.warning(f"  Pexels '{kw}': {e}"); continue

        random.shuffle(videos)
        for v in videos:
            if total>=target or v["id"] in used: continue
            best,bpx = None,0
            for vf in v.get("video_files",[]):
                w,h,lnk = vf.get("width",0),vf.get("height",0),vf.get("link","")
                if not lnk or w<=0 or h<=0: continue
                if w>h and w>=1920 and w*h>bpx: best,bpx=vf,w*h
            if not best:
                for vf in v.get("video_files",[]):
                    if vf.get("width",0)>vf.get("height",0) and vf.get("width",0)>=1280:
                        best=vf; break
            if not best: continue
            cdn = best.get("link","")
            if not _validate_cdn(cdn): continue
            dest     = WORK_DIR/f"clip_{v['id']}.mp4"
            clip_dur = min(int(v.get("duration",5)),12)
            log.info(f"  Clip {v['id']} ({best['width']}×{best['height']}, {clip_dur}s)")
            if _download(cdn, dest):
                downloaded.append(dest)
                used.add(v["id"])
                total += clip_dur
                time.sleep(0.2)

    if not downloaded:
        raise RuntimeError("No Pexels clips downloaded. Check PEXELS_API_KEY.")
    log.info(f"  Got {len(downloaded)} clips (~{total}s)")
    return downloaded


# ════════════════════════════════════════════════════════════════
# STEP 3 — VOICEOVER + SYNCED SRT  (edge-tts — free, unlimited)
# ════════════════════════════════════════════════════════════════
async def _tts_stream(script: str, audio: Path, srt: Path):
    comm  = edge_tts.Communicate(script, TTS_VOICE)
    words,aud = [],[]
    async for ev in comm.stream():
        if ev["type"]=="audio": aud.append(ev["data"])
        elif ev["type"]=="WordBoundary":
            words.append({"word":ev["text"],"start_ms":ev["offset"]//10_000,"dur_ms":ev["duration"]//10_000})
    with open(audio,"wb") as f:
        for c in aud: f.write(c)
    if not words: return
    def ms(v): h,r=divmod(v,3_600_000); m,r=divmod(r,60_000); s,v=divmod(r,1_000); return f"{h:02d}:{m:02d}:{s:02d},{v:03d}"
    cues = []
    for i in range(0,len(words),5):
        g=words[i:i+5]
        cues.append(f"{i//5+1}\n{ms(g[0]['start_ms'])} --> {ms(g[-1]['start_ms']+g[-1]['dur_ms']+150)}\n{' '.join(w['word'] for w in g)}\n")
    srt.write_text("\n".join(cues), encoding="utf-8")
    log.info(f"  SRT: {len(cues)} cues")

def generate_voiceover_with_subs(script: str):
    log.info(f"Step 3: Voiceover + SRT ({TTS_VOICE})...")
    audio = WORK_DIR/"voiceover.mp3"
    srt   = WORK_DIR/"captions.srt"
    try:    asyncio.run(_tts_stream(script, audio, srt))
    except RuntimeError: asyncio.get_event_loop().run_until_complete(_tts_stream(script, audio, srt))
    has_srt = srt.exists() and srt.stat().st_size>10
    return audio, (srt if has_srt else None)


# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════
def _font() -> str:
    return next((p for p in FONT_PATHS if Path(p).exists()), "")

def _duration(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_format",str(path)], capture_output=True, text=True)
        return float(json.loads(r.stdout)["format"]["duration"])
    except: return float(VIDEO_DURATION)

def _ffmpeg(cmd: list, label: str):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{r.stderr.decode(errors='replace')[-500:]}")


# ════════════════════════════════════════════════════════════════
# STEP 4a — WIDESCREEN MASTER  (1920×1080 — YouTube/Facebook)
# H.264 High · 12Mbps · bt709 · crossfade · captions
# BUG-PROOF: -filter_complex and -vf are NEVER in the same command
# ════════════════════════════════════════════════════════════════
def assemble_video(clips, voiceover, srt_path, title, script, channel) -> Path:
    log.info("Step 4a: Assembling widescreen master (1920×1080)...")
    font    = _font()
    out     = WORK_DIR/"master_wide.mp4"
    vo_dur  = _duration(voiceover)
    fa      = f":fontfile={font}" if font else ""

    # Encode + grade clips
    trimmed = []
    for i,clip in enumerate(clips):
        o = WORK_DIR/f"t{i}.mp4"
        try:
            _ffmpeg(["ffmpeg","-y","-i",str(clip),"-t","12",
                     "-vf",(f"scale={YT_W}:{YT_H}:force_original_aspect_ratio=increase,"
                            f"crop={YT_W}:{YT_H},setsar=1,"
                            f"eq=saturation=1.35:brightness=0.02:contrast=1.08,hue=h=8:s=1.1"),
                     "-c:v","libx264","-profile:v","high","-level","4.2",
                     "-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
                     "-pix_fmt","yuv420p","-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
                     "-r","30","-an",str(o)], f"Clip {i}")
            trimmed.append(o)
        except RuntimeError as e:
            log.warning(f"  Clip {i} skipped: {str(e)[:60]}")

    if not trimmed: raise RuntimeError("All clip encoding failed")

    # Crossfade transitions
    if len(trimmed)==1:
        concat = trimmed[0]
    else:
        ic,fc,prev = [],[],"[0:v]"
        for p in trimmed: ic+=["-i",str(p)]
        for k in range(1,len(trimmed)):
            lbl = f"[v{k}]" if k<len(trimmed)-1 else "[vout]"
            fc.append(f"{prev}[{k}:v]xfade=transition=fade:duration=0.5:offset={(12.0-0.5)*k},format=yuv420p{lbl}")
            prev=lbl
        concat = WORK_DIR/"xfaded.mp4"
        try:
            _ffmpeg(["ffmpeg","-y"]+ic+["-filter_complex",";".join(fc),"-map","[vout]",
                     "-c:v","libx264","-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
                     "-pix_fmt","yuv420p","-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
                     "-r","30",str(concat)], "Crossfade")
        except RuntimeError:
            clist=WORK_DIR/"concat.txt"
            with open(clist,"w",encoding="utf-8") as f:
                for p in trimmed: f.write(f"file '{str(p.resolve()).replace(chr(39), chr(8217))}'\n")
            concat=WORK_DIR/"concatenated.mp4"
            _ffmpeg(["ffmpeg","-y","-f","concat","-safe","0","-i",str(clist),"-c","copy",str(concat)],"Concat")

    # Music
    music = None
    if MUSIC_URL:
        mp = WORK_DIR/"music.mp3"
        if _download(MUSIC_URL, mp): music=mp

    has_srt = srt_path and Path(srt_path).exists()

    def srt_f(sz):
        e=str(Path(srt_path).resolve()).replace("\\","/").replace(":","\\:")
        return (f"subtitles='{e}':force_style='Fontname=Poppins{fa},FontSize={sz},"
                f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,"
                f"Bold=1,Outline=3,Shadow=2,MarginV=80,Alignment=2'")

    def dt_f(txt,ch,w,h,sz,lw):
        lines=textwrap.wrap(txt,width=lw)[:4]; ys=h-len(lines)*(sz+16)-80; parts=[]
        for i,line in enumerate(lines):
            esc=line.replace("\\","\\\\").replace("'","\u2019").replace(":","\\:").replace("%","\\%")
            parts.append(f"drawtext=text='{esc}':"+(f"fontfile={font}:" if font else "")+
                         f"fontcolor=white:fontsize={sz}:x=(w-text_w)/2:y={ys+i*(sz+16)}:"
                         f"borderw=3:bordercolor=black@0.9:box=1:boxcolor=black@0.45:boxborderw=12")
        ce=ch.replace("\\","\\\\").replace("'","\u2019").replace(":","\\:")
        parts.insert(0,f"drawtext=text='@{ce}':"+(f"fontfile={font}:" if font else "")+
                     f"fontcolor=white@0.9:fontsize=34:x=40:y=40:borderw=2:bordercolor=black@0.7")
        return ",".join(filter(None,parts))

    # BUG-PROOF: music → filter_complex only; no music → -vf only
    cmd = ["ffmpeg","-y","-stream_loop","-1","-i",str(concat),"-i",str(voiceover)]
    if music: cmd+=["-i",str(music)]
    cmd+=["-t",str(vo_dur+0.5)]

    if music:
        vc = f"[0:v]{srt_f(52) if has_srt else dt_f(script,channel,YT_W,YT_H,52,55)}[vout]"
        ac = "[2:a]volume=0.20[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        cmd+=["-filter_complex",f"{vc};{ac}","-map","[vout]","-map","[aout]"]
    else:
        cmd+=["-map","0:v","-map","1:a"]
        vf = srt_f(52) if has_srt else dt_f(script,channel,YT_W,YT_H,52,55)
        if vf: cmd+=["-vf",vf]

    cmd+=(["-c:v","libx264","-profile:v","high","-level","4.2",
           "-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
           "-pix_fmt","yuv420p","-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
           "-c:a","aac","-b:a","192k","-ar","44100","-ac","2",
           "-movflags","+faststart","-shortest",str(out)])
    _ffmpeg(cmd, "Widescreen assembly")
    log.info(f"  Wide: {out.name} ({out.stat().st_size//1_000_000:.1f}MB)")
    return out


# ════════════════════════════════════════════════════════════════
# STEP 4b — VERTICAL CUT  (1080×1920 — TikTok/Instagram)
# ════════════════════════════════════════════════════════════════
def make_vertical(wide, srt_path, script, channel) -> Path:
    log.info("Step 4b: Making vertical cut (1080×1920)...")
    out  = WORK_DIR/"vertical.mp4"
    font = _font()
    fa   = f":fontfile={font}" if font else ""
    has  = srt_path and Path(srt_path).exists()

    # Get source video dimensions to ensure valid crop
    try:
        r = subprocess.run(["ffprobe","-v","quiet","-print_format","json",
                           "-show_streams",str(wide)], capture_output=True, text=True)
        vid_info = json.loads(r.stdout)["streams"][0]
        src_w, src_h = vid_info.get("width", YT_W), vid_info.get("height", YT_H)
    except:
        src_w, src_h = YT_W, YT_H
    
    # Ensure crop box is valid (don't exceed source dimensions)
    crop_x = max(0, (src_w - VT_W) // 2)
    
    if has:
        se=str(Path(srt_path).resolve()).replace("\\","/").replace(":","\\:")
        sub=(f"subtitles='{se}':force_style='Fontname=Poppins{fa},FontSize=72,"
             f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,"
             f"Bold=1,Outline=4,Shadow=3,MarginV=120,Alignment=2'")
    else:
        lines=textwrap.wrap(script,width=25)[:5]; ys=VT_H-len(lines)*106-100; parts=[]
        for i,line in enumerate(lines):
            esc=line.replace("\\","\\\\").replace("'","\u2019").replace(":","\\:").replace("%","\\%")
            parts.append(f"drawtext=text='{esc}':"+(f"fontfile={font}:" if font else "")+
                         f"fontcolor=white:fontsize=72:x=(w-text_w)/2:y={ys+i*106}:"
                         f"borderw=4:bordercolor=black@0.9:box=1:boxcolor=black@0.45:boxborderw=14")
        ce=channel.replace("\\","\\\\").replace("'","\u2019").replace(":","\\:")
        parts.insert(0,f"drawtext=text='@{ce}':"+(f"fontfile={font}:" if font else "")+
                     "fontcolor=white@0.88:fontsize=40:x=30:y=60:borderw=2:bordercolor=black@0.7")
        sub=",".join(filter(None,parts))

    # Fixed: use calculated crop_x instead of formula, add scale before crop
    vf=f"scale={VT_W}:{VT_H}:force_original_aspect_ratio=increase,crop={VT_W}:{VT_H}:{crop_x}:0,setsar=1"
    if sub: vf+=","+sub

    _ffmpeg(["ffmpeg","-y","-i",str(wide),"-vf",vf,
             "-c:v","libx264","-profile:v","high","-level","4.2",
             "-preset","slow","-b:v","12M","-maxrate","14M","-bufsize","24M",
             "-pix_fmt","yuv420p","-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709",
             "-c:a","aac","-b:a","192k","-ar","44100","-ac","2",
             "-movflags","+faststart",str(out)], "Vertical cut")
    log.info(f"  Vertical: {out.name} ({out.stat().st_size//1_000_000:.1f}MB)")
    return out


# ════════════════════════════════════════════════════════════════
# STEP 4c — CLOUDINARY CDN  (free 25GB/month)
# ════════════════════════════════════════════════════════════════
def upload_to_cloudinary(video_path: Path, public_id: str) -> str:
    if not CLOUDINARY_URL:
        log.warning("  CLOUDINARY_URL not set — TikTok/Instagram CDN skipped")
        return ""
    try:
        try:
            import cloudinary, cloudinary.uploader
        except ImportError:
            subprocess.run([sys.executable,"-m","pip","install","cloudinary","-q"],check=True)
            import cloudinary, cloudinary.uploader
        cloudinary.config(cloudinary_url=CLOUDINARY_URL)
        log.info(f"  Uploading to Cloudinary...")
        result = cloudinary.uploader.upload(str(video_path),public_id=public_id,
                                             resource_type="video",overwrite=True,format="mp4")
        url = result.get("secure_url","")
        log.info(f"  CDN URL: {url}")
        return url
    except Exception as e:
        log.error(f"  Cloudinary failed: {e}")
        return ""


# ════════════════════════════════════════════════════════════════
# STEP 5 — POST TO ALL PLATFORMS
# ════════════════════════════════════════════════════════════════
def _caption(caption,hashtags): return (caption.strip()+"\n\n"+" ".join(hashtags[:10]))[:2200]

def _yt_token():
    if not(YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN): return ""
    try:
        r=requests.post("https://oauth2.googleapis.com/token",
                        data={"client_id":YT_CLIENT_ID,"client_secret":YT_CLIENT_SECRET,
                              "refresh_token":YT_REFRESH_TOKEN,"grant_type":"refresh_token"},timeout=15)
        return r.json().get("access_token","") if r.ok else ""
    except: return ""

def _upload_thumb(vid,thumb,token):
    if not(vid and thumb and Path(thumb).exists()): return
    try:
        with open(thumb,"rb") as f:
            r=requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
                            f"?videoId={vid}&uploadType=media",
                            headers={"Authorization":f"Bearer {token}","Content-Type":"image/png"},
                            data=f, timeout=60)
        log.info("  Thumbnail ✓" if r.ok else f"  Thumbnail HTTP {r.status_code}")
    except Exception as e: log.warning(f"  Thumbnail: {e}")

def post_youtube(video_path,title,desc,thumbnail=None) -> str:
    if not(YT_CLIENT_ID and YT_CLIENT_SECRET and YT_REFRESH_TOKEN):
        log.warning("YouTube: credentials not set"); return ""
    token=_yt_token()
    if not token: log.error("YouTube: token failed"); return ""
    try:
        r1=requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                         headers={"Authorization":f"Bearer {token}","Content-Type":"application/json",
                                  "X-Upload-Content-Type":"video/mp4","X-Upload-Content-Length":str(video_path.stat().st_size)},
                         json={"snippet":{"title":title[:100],"description":desc[:5000],
                                          "tags":["fitness","workout","health","gym"],"categoryId":"17"},
                               "status":{"privacyStatus":"public","selfDeclaredMadeForKids":False}},timeout=30)
        if not r1.ok: log.error(f"YouTube initiate HTTP {r1.status_code}"); return ""
        ul=r1.headers.get("Location","")
        if not ul: log.error("YouTube: no upload URL"); return ""
        with open(video_path,"rb") as f:
            r2=requests.put(ul,headers={"Content-Type":"video/mp4"},data=f,timeout=300)
        if r2.ok:
            vid=r2.json().get("id","")
            log.info(f"YouTube ✓  id={vid}")
            if thumbnail: _upload_thumb(vid,thumbnail,token)
            return vid
        log.error(f"YouTube upload HTTP {r2.status_code}"); return ""
    except Exception as e: log.error(f"YouTube: {e}"); return ""

def post_facebook(video_path,title,desc) -> bool:
    if not(FB_PAGE_ID and FB_TOKEN): log.warning("Facebook: not set"); return False
    try:
        with open(video_path,"rb") as f:
            r=requests.post(f"https://graph-video.facebook.com/v19.0/{FB_PAGE_ID}/videos",
                            data={"title":title[:255],"description":desc[:5000],"access_token":FB_TOKEN},
                            files={"source":("video.mp4",f,"video/mp4")},timeout=300)
        if r.ok: log.info(f"Facebook ✓  id={r.json().get('id')}"); return True
        log.error(f"Facebook HTTP {r.status_code}"); return False
    except Exception as e: log.error(f"Facebook: {e}"); return False

def post_tiktok(cdn_url,caption) -> bool:
    if not TIKTOK_TOKEN: log.warning("TikTok: token not set"); return False
    if not cdn_url: log.warning("TikTok: no CDN URL"); return False
    try:
        r=requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/",
                        headers={"Authorization":f"Bearer {TIKTOK_TOKEN}","Content-Type":"application/json; charset=UTF-8"},
                        json={"post_info":{"title":caption[:150],"privacy_level":"PUBLIC_TO_EVERYONE",
                                           "disable_duet":False,"disable_comment":False,"disable_stitch":False},
                              "source_info":{"source":"PULL_FROM_URL","video_url":cdn_url}},timeout=30)
        if r.ok: log.info("TikTok ✓"); return True
        log.error(f"TikTok HTTP {r.status_code}"); return False
    except Exception as e: log.error(f"TikTok: {e}"); return False

def post_instagram(cdn_url,caption) -> bool:
    if not(IG_ACCOUNT_ID and IG_TOKEN): log.warning("Instagram: not set"); return False
    if not cdn_url: log.warning("Instagram: no CDN URL"); return False
    base="https://graph.facebook.com/v19.0"
    try:
        r1=requests.post(f"{base}/{IG_ACCOUNT_ID}/media",
                         json={"media_type":"REELS","video_url":cdn_url,"caption":caption,"access_token":IG_TOKEN},timeout=30)
        if not r1.ok: log.error(f"Instagram container HTTP {r1.status_code}"); return False
        cid=r1.json().get("id")
        if not cid: log.error("Instagram: no container ID"); return False
        log.info("Instagram: waiting for container...")
        for _ in range(18):
            time.sleep(5)
            sr=requests.get(f"{base}/{cid}",params={"fields":"status_code","access_token":IG_TOKEN},timeout=15)
            st=sr.json().get("status_code","")
            if st=="FINISHED": break
            if st=="ERROR": log.error("Instagram: container error"); return False
        r2=requests.post(f"{base}/{IG_ACCOUNT_ID}/media_publish",
                         json={"creation_id":cid,"access_token":IG_TOKEN},timeout=30)
        if r2.ok and r2.json().get("id"): log.info("Instagram ✓"); return True
        log.error(f"Instagram publish HTTP {r2.status_code}"); return False
    except Exception as e: log.error(f"Instagram: {e}"); return False


# ════════════════════════════════════════════════════════════════
# STEP 6 — ATOMIC LOG (crash-safe)
# ════════════════════════════════════════════════════════════════
def save_run_log(script_data,results):
    lp=Path(__file__).parent/"run_history.json"
    try: existing=json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else []
    except: existing=[]
    existing.insert(0,{"date":datetime.utcnow().isoformat(),"title":script_data.get("title",""),"platforms":results})
    tmp=lp.with_suffix(".tmp")
    try: tmp.write_text(json.dumps(existing[:60],indent=2),encoding="utf-8"); tmp.replace(lp)
    except Exception as e: log.warning(f"Log write: {e}")

def cleanup(keep_list=None):
    keep={Path(p).resolve() for p in (keep_list or []) if p}
    for pat in ["*.mp4","*.mp3","*.txt","*.srt","*.tmp","*.png"]:
        for f in WORK_DIR.glob(pat):
            if f.resolve() not in keep:
                try: f.unlink()
                except: pass
    log.info("Temp files cleaned")

def _validate_env():
    if not PEXELS_API_KEY:
        log.error("PEXELS_API_KEY missing — get free at pexels.com/api")
        sys.exit(1)
    has_ai = any([CEREBRAS_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY])
    if not has_ai:
        log.warning("No AI key set — pipeline will use script cache for content")
        log.warning("Recommended: add CEREBRAS_API_KEY (cloud.cerebras.ai — free, email only)")


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 68)
    log.info("FitBot v6 GOD MODE — Multi-Provider AI · Zero Cost · Zero Crashes")
    log.info(f"Channel  : {CHANNEL_NAME}")
    log.info(f"Niche    : {NICHE}")
    log.info(f"AI Chain : Cerebras → Groq → OpenRouter → Gemini → Script Cache")
    log.info(f"Wide     : {YT_W}×{YT_H} → YouTube + Facebook")
    log.info(f"Vertical : {VT_W}×{VT_H} → TikTok  + Instagram")
    log.info(f"Quality  : H.264 High · 12Mbps · 192k AAC · bt709 · Poppins Bold")
    log.info(f"Cost     : $0.00/month")
    log.info("=" * 68)

    _validate_env()

    wide=vertical=thumbnail=None
    try:
        # Step 1 — Script
        script_data = generate_script()
        cap  = _caption(script_data["caption"], script_data["hashtags"])
        desc = script_data["caption"] + "\n\n" + " ".join(script_data["hashtags"])

        # Step 1b — Thumbnail
        thumbnail = generate_thumbnail(script_data, CHANNEL_NAME)

        # Step 2 — Pexels
        clips = fetch_pexels_videos(script_data["search_keywords"], VIDEO_DURATION)

        # Step 3 — Voiceover + SRT
        voiceover, srt = generate_voiceover_with_subs(script_data["script"])

        # Step 4a — Widescreen
        wide = assemble_video(clips, voiceover, srt,
                              title=script_data["title"],
                              script=script_data["script"],
                              channel=CHANNEL_NAME)

        # Step 4b — Vertical
        vertical = make_vertical(wide, srt,
                                 script=script_data["script"],
                                 channel=CHANNEL_NAME)

        # Step 4c — CDN
        cdn_url = upload_to_cloudinary(vertical, "fitbot_vertical_latest")

        # Step 5 — Post
        log.info("Step 5: Posting to all platforms...")
        yt_id = post_youtube(wide, script_data["title"], desc, thumbnail=thumbnail)
        results = {
            "youtube"  : bool(yt_id),
            "facebook" : post_facebook(wide, script_data["title"], desc),
            "tiktok"   : post_tiktok(cdn_url, cap),
            "instagram": post_instagram(cdn_url, cap),
        }

        log.info("=" * 68)
        log.info("RESULTS:")
        fmts={"youtube":"1920×1080","facebook":"1920×1080","tiktok":"1080×1920","instagram":"1080×1920"}
        for p,ok in results.items():
            log.info(f"  {p.upper():12}  {'✓ POSTED' if ok else '✗ skipped/failed'}  [{fmts[p]}]")
        if yt_id: log.info(f"  Watch: https://youtube.com/watch?v={yt_id}")
        log.info("=" * 68)

        # Step 6 — Log
        save_run_log(script_data, results)

    finally:
        cleanup(keep_list=[wide, vertical, thumbnail])
        log.info("Pipeline complete.")

if __name__ == "__main__":
    main()
