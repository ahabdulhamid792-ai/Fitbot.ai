# FITBOT SETUP — GOOGLE GEMINI (FREE, NO CARD)

## Step 1: Get Your Free Gemini API Key

1. Go to https://aistudio.google.com
2. Sign in with any Google account
3. Click "Get API Key" in the top menu
4. Click "Create API Key"
5. Copy the key (starts with AIzaSy...)

Free limits: 15 requests/minute, 1500/day — more than enough for daily use.

---

## Step 2: Generate Your Dashboard Password Hash

Open Terminal (Mac/Linux) or PowerShell (Windows):

### Mac / Linux
```bash
echo -n "your-chosen-password" | sha256sum
```

### Windows (PowerShell)
```powershell
$pw = "your-chosen-password"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($pw)
$hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
[System.BitConverter]::ToString($hash).Replace("-","").ToLower()
```

Copy the 64-character output.

---

## Step 3: Create Your .env File

```bash
cd fitbot-ai/backend
cp .env.example .env
```

Open `.env` and fill in:
```
GEMINI_API_KEY=AIzaSy_your_key_from_step_1
DASHBOARD_PASSWORD_HASH=your_64_char_hash_from_step_2
SESSION_SECRET=any_random_string_at_least_32_chars
PORT=3000
```

Generate a session secret:
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

---

## Step 4: Install and Run

```bash
cd fitbot-ai/backend
npm install
npm start
```

You should see:
```
[INFO] FitBot server running → http://localhost:3000
[INFO] AI: Google Gemini 2.0 Flash (free tier)
```

---

## Step 5: Open the App

Go to http://localhost:3000 in your browser.

- Email: anything (e.g. mhed@fitness.com)
- Password: the plain text password you hashed in Step 2

---

## Deploying to Render.com (Free Hosting)

1. Push the fitbot-ai folder to a GitHub repo
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Settings:
   - Root Directory: `backend`
   - Build Command: `npm install`
   - Start Command: `node server.js`
5. Go to Environment → Add Variables:
   ```
   GEMINI_API_KEY=AIzaSy...
   DASHBOARD_PASSWORD_HASH=abc123...
   SESSION_SECRET=random64chars...
   NODE_ENV=production
   ```
6. Deploy → your app is live at yourname.onrender.com

---

## Gemini Free Tier Limits

| Limit          | Amount                |
|----------------|-----------------------|
| Requests/min   | 15                    |
| Requests/day   | 1,500                 |
| Tokens/min     | 1,000,000             |
| Cost           | FREE (no card needed) |

1,500 scripts per day is more than enough for daily content creation.
