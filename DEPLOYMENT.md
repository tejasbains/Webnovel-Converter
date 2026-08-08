# Deployment Guide

This document covers deployment options and considerations for the WebNovel Scraper webapp.

## Architecture Overview

This is a **single full-stack Flask application** that serves both the frontend (SPA) and the API under a single URL:
- `GET /` → serves the HTML/JS frontend
- `POST /api/jobs` → API endpoints
- No CORS configuration needed (same origin)

## Deployment Options

### Option A: Local Development / Personal Use (Recommended)

**Why Local?**
- No hosting costs
- No free-tier timeouts or cold starts
- Scrapes from your own IP (avoids shared datacenter IP bans)
- Content stays on your machine (lower legal risk)
- EPUB downloads go directly to your browser's download folder

**To Run Locally:**

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py

# Access at http://localhost:5000
```

**Production-like Local Run:**
```bash
gunicorn wsgi:app --bind 0.0.0.0:5000
```

### Option B: Free Cloud Host (Render, Railway, Fly.io)

**Pros:**
- Shareable via public URL
- No local Python installation needed

**Cons:**
- Free tiers have cold starts (30-60s first request after idle)
- Request timeout limits (~30-60s) - mitigated by background job + polling architecture
- Ephemeral filesystem - EPUBs expire after 30 minutes (by design)
- Shared datacenter IP risks rate-limiting/bans from NovelFire
- Legal considerations for publicly hosting scraped content

**Deployment Steps (Render Example):**

1. Push code to GitHub
2. Create new Web Service on Render
3. Connect your GitHub repo
4. Render auto-detects:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn wsgi:app` (from Procfile)
5. Deploy

**Environment:**
- Python 3.11+
- Port: Set by `$PORT` env var (handled automatically by gunicorn)

## Storage & Retention

**EPUB Storage:**
- Stored in `tempfile.gettempdir()/webnovel_jobs/` as temporary files
- **Retention: 30 minutes after job completion** (per requirements)
- Automatic cleanup runs every 60 seconds

**Ephemeral Filesystem Note:**
- Free hosts reset storage on restart/redeploy
- EPUBs are short-lived by design (30 min window for download)
- This is intentional - not a bug!

## Background Jobs & Polling

**Architecture:**
- Jobs run in background worker threads
- Frontend polls `GET /api/jobs/<id>` every ~1 second
- This design survives free-tier request timeout limits

**Why not WebSockets/SSE?**
- Polling is simpler and more compatible with free hosts
- 1-second interval is responsive enough for user feedback
- Can be upgraded to SSE if needed

## Performance Considerations

**Cold Starts:**
- Free hosts sleep after inactivity
- First request after sleep: 30-60s wake time
- Subsequent requests: normal speed
- Local deployment avoids this entirely

**Scrape Duration:**
- ~10-30 seconds per chapter (fetch + optional translation)
- 100 chapters: ~15-30 minutes
- 5000 chapters (max): several hours

**Cancellation:**
- Users can cancel at any time via cancel button
- Worker checks cancel flag at each loop boundary
- Typical response time: < 5 seconds

## Legal & ToS Considerations

**⚠️ Important:**
- This tool scrapes NovelFire.net - check their Terms of Service
- **For personal use only** - do not redistribute scraped content
- Public hosting may violate copyright or ToS
- Local deployment keeps content on your machine (lower risk)

**IP Bans:**
- Public hosts use shared datacenter IPs
- Scraping from shared IPs risks rate-limiting/bans for all users
- Local deployment uses your personal IP

## Security

**Input Validation:**
- All input validated server-side (never trust client)
- URL validation prevents SSRF attacks
- File path sanitization prevents directory traversal

**No Authentication:**
- This is a single-user tool
- Add authentication if deploying publicly

## Monitoring & Logs

**Local:**
- Flask debug mode shows all requests/errors in console
- Job progress logged to stdout

**Cloud:**
- Check platform logs (Render Logs, Railway Logs, etc.)
- Monitor for rate-limiting responses from NovelFire

## Troubleshooting

**"Job failed" / No chapters fetched:**
- Check URL format (must be NovelFire.net main page URL)
- Verify chapter count isn't higher than available chapters
- Check if NovelFire is accessible

**"File is no longer available":**
- EPUB expired (30 min window)
- Download immediately after completion

**Translation timeouts:**
- Translation bounded to 60s per field
- Falls back to original text on timeout
- Job continues regardless

**Cold start delays:**
- Normal for free hosts after idle period
- Use local deployment to avoid

## Next Steps

**For Local Use:**
1. Install dependencies: `pip install -r requirements.txt`
2. Run: `python app.py`
3. Open: `http://localhost:5000`

**For Cloud Deployment:**
1. Review legal/ToS considerations
2. Push to GitHub
3. Deploy to Render/Railway/Fly.io
4. Monitor for rate-limiting

**For Testing:**
- Run `pytest` (if test files exist)
- Try small scrapes first (5-10 chapters)
