# Installation Guide

## Quick Start

```bash
# 1. Create virtual environment (recommended)
python -m venv venv

# 2. Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Upgrade pip (recommended)
python -m pip install --upgrade pip

# 4. Install dependencies
pip install -r requirements.txt

# 5. Run the app
python app.py

# 6. Open browser
# Navigate to http://localhost:5000
```

### Other Common Issues

**Missing C++ Build Tools (Windows)**
If you see errors about "Microsoft Visual C++ 14.0 is required":
1. Download and install "Microsoft C++ Build Tools":
   https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. Select "Desktop development with C++" during installation
3. Retry `pip install -r requirements.txt`

**Permission Errors**
Run command prompt/terminal as Administrator and retry.

**Python Version**
Ensure you're using Python 3.8 or higher:
```bash
python --version
```

### Verifying Installation

Test that all imports work:
```bash
python -c "import flask, requests, bs4, ebooklib, deep_translator; print('All dependencies OK')"
```

Test Pillow specifically:
```bash
python -c "from PIL import Image; print('Pillow OK')"
```

## Dependencies Explained

- **flask**: Web framework for the API and serving the frontend
- **requests**: HTTP library for fetching web pages
- **beautifulsoup4**: HTML parsing for extracting chapter content
- **ebooklib**: EPUB generation
- **deep-translator**: Google Translate integration for optional translation
- **pillow**: Image validation for cover images (validates size and format)
- **gunicorn**: Production WSGI server (not needed for local development)

## Development vs Production

**Development (local testing):**
```bash
python app.py
```
- Runs Flask development server
- Debug mode enabled
- Auto-reloads on code changes

**Production (local or deployed):**
```bash
gunicorn wsgi:app --bind 0.0.0.0:5000
```
- Runs production WSGI server
- Better performance
- No auto-reload

## Next Steps

Once installation is complete:
1. Run `python app.py`
2. Open http://localhost:5000 in your browser
3. Try a small test scrape (5-10 chapters) first
4. See `DEPLOYMENT.md` for deployment options
