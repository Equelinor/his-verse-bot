# his.verse.for.the.day — Instagram Automation Bot

Daily Bible verse post generator. Fully automated. Near-zero cost.

---

## What it does

Every day at 8:00 AM (Bahrain time):
1. Picks today's Bible verse from a 65-verse rotating bank
2. Pulls a matching divine background image from Unsplash
3. Composites the verse text with cinematic overlays using Pillow
4. Writes a warm personal caption via Claude Haiku
5. Uploads image and posts to Instagram via Meta Graph API

---

## Cost breakdown

| Component      | Tool               | Cost         |
|----------------|--------------------|--------------|
| Verse bank     | Local CSV          | **$0.00**    |
| Background img | Unsplash free API  | **$0.00**    |
| Image editing  | Pillow (Python)    | **$0.00**    |
| Caption AI     | Claude Haiku       | **~$0.30/yr**|
| Scheduler      | GitHub Actions     | **$0.00**    |
| Image hosting  | Imgur free API     | **$0.00**    |
| IG posting     | Meta Graph API     | **$0.00**    |

---

## Setup (one-time, ~30 minutes)

### Step 1 — Unsplash API key (free)
1. Go to https://unsplash.com/developers
2. Create a new application
3. Copy your **Access Key**

### Step 2 — Imgur API key (free)
1. Go to https://api.imgur.com/oauth2/addclient
2. Register as "Anonymous usage without user authorization"
3. Copy your **Client ID**

### Step 3 — Claude API key (optional, ~$0.30/yr)
1. Go to https://console.anthropic.com
2. Create an API key
3. Add $5 credit (will last years at this volume)
- Skip this if you want — the bot has a built-in fallback caption

### Step 4 — Meta Graph API (Instagram posting)
This is the most involved step but Meta's documentation is clear:

1. Go to https://developers.facebook.com
2. Create a new App → select "Business"
3. Add "Instagram Graph API" product
4. Connect your Instagram account (must be a **Professional** or **Creator** account)
5. Generate a **long-lived access token** (valid 60 days, re-generate monthly or automate refresh)
6. Note your **Instagram User ID** from the API explorer

### Step 5 — GitHub repository setup
1. Create a new GitHub repository (can be private)
2. Upload all files from this folder
3. Go to **Settings → Secrets and variables → Actions**
4. Add these secrets:

```
UNSPLASH_ACCESS_KEY   = your_unsplash_key
ANTHROPIC_API_KEY     = your_claude_key
IG_USER_ID            = your_instagram_user_id
IG_ACCESS_TOKEN       = your_long_lived_token
IMGUR_CLIENT_ID       = your_imgur_client_id
```

5. The workflow file at `.github/workflows/daily_post.yml` will run automatically every day

---

## Running locally

```bash
# Install dependencies
pip install Pillow requests python-dotenv

# Create .env file
cp .env.example .env
# Fill in your keys in .env

# Preview mode (generates image, does NOT post)
python bot.py --preview

# Run full pipeline
python bot.py

# Force a specific verse (useful for testing)
python bot.py --preview --verse 7
```

---

## File structure

```
bible_bot/
├── bot.py                          # Main automation script
├── data/
│   ├── verses.csv                  # 65+ verse bank (add more anytime)
│   └── state.json                  # Tracks rotation (auto-generated)
├── output/                         # Generated post images saved here
├── fonts/                          # Auto-downloaded on first run
└── .github/
    └── workflows/
        └── daily_post.yml          # GitHub Actions scheduler
```

---

## Adding more verses

Open `data/verses.csv` and add rows following this format:

```
id,reference,text,theme,mood,image_keywords
66,John 3:16,"For God so loved the world...",love,uplifting,"soft sunrise clouds pink sky"
```

**Moods:** `calm` | `uplifting` | `reflective`
**Themes:** `peace` | `strength` | `faith` | `hope` | `rest` | `love` | `courage` | `comfort` | `grace` | `trust` | `refuge` | `joy` | `gratitude`

**Image keywords:** 2-5 words describing the ideal background. Be descriptive:
- `"misty mountain sunrise golden light"` → peaceful, divine
- `"ocean shore soft waves horizon"` → calm, reflective
- `"dramatic storm clouds clearing sunbeam"` → strength, overcoming

---

## Manual posting (Buffer / Later alternative)

If you prefer to review before posting:
1. Run `python bot.py --preview` daily
2. Check the image in `output/`
3. Copy the caption from the terminal
4. Post manually via Buffer, Later, or directly on Instagram

---

## Rotating access tokens

Instagram long-lived tokens expire every 60 days. To automate renewal:
1. Add a second GitHub Actions workflow that refreshes the token monthly
2. Or set a calendar reminder and refresh manually at https://developers.facebook.com/tools/explorer
