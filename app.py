"""
Flask API application for webnovel scraper webapp.

Single full-stack app serving SPA at / and API under /api/*.
No CORS needed (same origin).

Validates Requirements: 1.3, 2.2, 5.2, 5.3, 5.4, 5.6, 8.1, 8.2, 8.4, 9.1, 9.2, 9.5
"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from validation import validate_params
from job_manager import get_manager
import io

app = Flask(__name__, static_folder='static')


@app.route("/")
def index():
    """
    Serve the single-page UI.
    
    Validates: Requirement 1.1 (visual interface)
    """
    return send_from_directory(app.static_folder, 'index.html')


@app.route("/api/jobs", methods=["POST"])
def create_job():
    """
    Validate input, create a scrape job, start worker, return job ID.
    
    Returns:
        202 with {jobId, status} on success
        400 with field-error map on validation failure
        
    Validates: Requirements 1.3, 1.4, 1.5, 1.6, 8.1 (input validation)
    """
    raw_data = request.get_json() or {}
    
    # Authoritative server-side validation (Req 8.1)
    errors, normalized_params = validate_params(raw_data)
    
    if errors:
        # Return 400 with per-field error map (Req 8.1)
        return jsonify({"errors": errors}), 400
    
    # Create job and start worker
    manager = get_manager()
    job_id = manager.create_job(normalized_params)
    
    # Return 202 with job ID (Req 1.3)
    snapshot = manager.get_snapshot(job_id)
    return jsonify({
        "jobId": job_id,
        "status": snapshot.status if snapshot else "running"
    }), 202


@app.route("/api/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """
    Return current job status/progress snapshot.
    
    Returns:
        200 with job snapshot
        404 if job not found
        
    Validates: Requirement 6.1 (progress feedback)
    """
    manager = get_manager()
    snapshot = manager.get_snapshot(job_id)
    
    if snapshot is None:
        return jsonify({"error": "Job not found"}), 404
    
    # Return snapshot as JSON
    return jsonify({
        "jobId": snapshot.job_id,
        "status": snapshot.status,
        "fetched": snapshot.fetched,
        "total": snapshot.total,
        "messages": snapshot.messages,
        "stage": snapshot.stage,
        "error": snapshot.error,
        "fileName": snapshot.file_name,
        "createdAt": snapshot.created_at,
        "completedAt": snapshot.completed_at,
        "expiresAt": snapshot.expires_at
    }), 200


@app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    """
    Request cancellation of a running job (idempotent, non-blocking).
    
    Safe to call on terminal jobs (no-op, Req 9.5).
    
    Returns:
        202 with current snapshot
        404 if job not found
        
    Validates: Requirements 9.1, 9.2, 9.5 (cancellation behavior)
    """
    manager = get_manager()
    snapshot = manager.request_cancel(job_id)
    
    if snapshot is None:
        return jsonify({"error": "Job not found"}), 404
    
    # Return current snapshot (Req 9.5 - unchanged if already terminal)
    return jsonify({
        "jobId": snapshot.job_id,
        "status": snapshot.status,
        "fetched": snapshot.fetched,
        "total": snapshot.total,
        "messages": snapshot.messages,
        "stage": snapshot.stage,
        "error": snapshot.error,
        "fileName": snapshot.file_name
    }), 202


@app.route("/api/jobs/<job_id>/download", methods=["GET"])
def download_epub(job_id):
    """
    Stream the finished EPUB as an attachment.
    
    Returns:
        200 with EPUB bytes and proper headers (Req 5.2, 5.3, 5.4)
        410 Gone if incomplete, cancelled, expired, or missing (Req 5.6)
        
    Validates: Requirements 5.2, 5.3, 5.4, 5.6 (EPUB delivery)
    """
    manager = get_manager()
    
    # Get job snapshot to check status and get filename
    snapshot = manager.get_snapshot(job_id)
    if snapshot is None:
        return jsonify({"error": "Job not found"}), 410
    
    # Only completed jobs have EPUBs
    if snapshot.status != "completed":
        return jsonify({"error": "EPUB not available"}), 410
    
    # Get EPUB bytes (checks expiry)
    epub_bytes = manager.get_epub_path(job_id)
    if epub_bytes is None:
        # Expired or missing (Req 5.6)
        return jsonify({"error": "File is no longer available"}), 410
    
    # Stream with proper headers (Req 5.3, 5.4)
    return send_file(
        io.BytesIO(epub_bytes),
        mimetype="application/epub+zip",
        as_attachment=True,
        download_name=snapshot.file_name
    )


if __name__ == "__main__":
    print("Starting Flask app...")
    print("Access the app at http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)