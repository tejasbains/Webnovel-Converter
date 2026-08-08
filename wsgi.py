"""
WSGI entrypoint for production deployment.

This module exposes the Flask app for WSGI servers like gunicorn.
"""

from app import app

if __name__ == "__main__":
    app.run()
