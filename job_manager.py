"""
Job Manager Module

Thread-safe in-memory job registry with background workers and cancellation support.
Manages scrape job lifecycle, progress tracking, and EPUB retention.

Validates Requirements: 5.5, 6.1, 6.2, 9.1, 9.2, 9.3, 9.5
"""

import uuid
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import time

from scraper_service import run_scrape
from epub_store import get_store


class JobStatus(Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobSnapshot:
    """
    Immutable snapshot of job state for API responses.
    
    Validates: Requirement 6.2 (progress tracking)
    """
    job_id: str
    status: str  # JobStatus value
    cancel_requested: bool
    fetched: int  # Chapters fetched so far
    total: int  # Requested chapter count
    messages: list[str]  # Progress/warning notices
    stage: str  # Current stage label
    error: Optional[str]  # Error message if failed
    file_name: str  # Derived download name
    created_at: str  # ISO timestamp
    completed_at: Optional[str]  # ISO timestamp
    expires_at: Optional[str]  # ISO timestamp


class Job:
    """
    Internal job state (mutable, protected by JobManager lock).
    """
    
    def __init__(self, job_id: str, params: Dict[str, Any]):
        self.job_id = job_id
        self.params = params
        self.status = JobStatus.QUEUED
        self.cancel_requested = False
        self.fetched = 0
        self.total = params["chapter_count"]
        self.messages: list[str] = []
        self.stage = "queued"
        self.error: Optional[str] = None
        self.file_name = params["file_name"]
        self.created_at = datetime.utcnow()
        self.completed_at: Optional[datetime] = None
        self.expires_at: Optional[datetime] = None
        self.worker_thread: Optional[threading.Thread] = None
    
    def snapshot(self) -> JobSnapshot:
        """Create an immutable snapshot for API responses."""
        return JobSnapshot(
            job_id=self.job_id,
            status=self.status.value,
            cancel_requested=self.cancel_requested,
            fetched=self.fetched,
            total=self.total,
            messages=self.messages.copy(),
            stage=self.stage,
            error=self.error,
            file_name=self.file_name,
            created_at=self.created_at.isoformat() + "Z",
            completed_at=self.completed_at.isoformat() + "Z" if self.completed_at else None,
            expires_at=self.expires_at.isoformat() + "Z" if self.expires_at else None
        )


class JobManager:
    """
    Thread-safe job manager with background workers and cancellation.
    
    Maintains in-memory registry keyed by UUID, launches worker threads,
    tracks progress, handles cancellation, and manages EPUB retention.
    
    Validates Requirements: 5.5, 6.1, 6.2, 9.1, 9.2, 9.3, 9.5
    """
    
    def __init__(self, epub_store=None):
        """
        Initialize the job manager.
        
        Args:
            epub_store: EpubStore instance (defaults to singleton)
        """
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._epub_store = epub_store or get_store()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()
    
    def create_job(self, params: Dict[str, Any]) -> str:
        """
        Create a new job and start its worker thread.
        
        Args:
            params: Validated scrape parameters
            
        Returns:
            Job ID (UUID string)
            
        Validates: Requirement 6.1 (job creation and worker launch)
        """
        job_id = str(uuid.uuid4())
        job = Job(job_id, params)
        
        with self._lock:
            self._jobs[job_id] = job
            
            # Launch worker thread
            worker = threading.Thread(
                target=self._worker,
                args=(job_id,),
                daemon=True
            )
            job.worker_thread = worker
            job.status = JobStatus.RUNNING
            worker.start()
        
        return job_id
    
    def get_snapshot(self, job_id: str) -> Optional[JobSnapshot]:
        """
        Get an immutable snapshot of job state.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobSnapshot or None if job not found
            
        Validates: Requirement 6.1 (progress snapshots)
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.snapshot()
    
    def request_cancel(self, job_id: str) -> Optional[JobSnapshot]:
        """
        Request cancellation of a job (non-blocking, idempotent).
        
        Sets the cancel flag; the worker checks it at loop boundaries.
        Safe to call on terminal jobs (no-op). Returns None for unknown IDs.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Current job snapshot or None if job not found
            
        Validates: Requirements 9.1, 9.2, 9.5 (cancellation behavior)
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            
            # Only set flag if not already terminal (Req 9.5)
            if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                job.cancel_requested = True
            
            return job.snapshot()
    
    def get_epub_path(self, job_id: str) -> Optional[bytes]:
        """
        Get EPUB bytes for a completed job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            EPUB bytes or None if unavailable/expired/not completed
            
        Validates: Requirement 5.5 (retention and delivery)
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            
            # Only completed jobs have EPUBs
            if job.status != JobStatus.COMPLETED:
                return None
            
            # Check expiry
            if job.expires_at and datetime.utcnow() >= job.expires_at:
                return None
        
        # Retrieve from store (outside lock to avoid blocking)
        return self._epub_store.get(job_id)
    
    def cleanup_expired(self):
        """
        Remove expired EPUBs and old job records.
        
        Respects the ≥30 min retention window (Requirement 5.5).
        """
        with self._lock:
            now = datetime.utcnow()
            expired_job_ids = []
            
            for job_id, job in self._jobs.items():
                # Clean up expired completed jobs
                if job.status == JobStatus.COMPLETED and job.expires_at:
                    if now >= job.expires_at:
                        expired_job_ids.append(job_id)
        
        # Delete EPUBs and prune job records (outside lock)
        for job_id in expired_job_ids:
            self._epub_store.delete(job_id)
            with self._lock:
                if job_id in self._jobs:
                    del self._jobs[job_id]
    
    def start_cleanup_worker(self, interval_seconds: int = 60):
        """
        Start a background thread that periodically cleans up expired jobs.
        
        Args:
            interval_seconds: How often to run cleanup (default: 60)
        """
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return  # Already running
        
        def cleanup_loop():
            while not self._stop_cleanup.wait(timeout=interval_seconds):
                try:
                    self.cleanup_expired()
                except Exception:
                    pass  # Ignore cleanup errors
        
        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()
    
    def stop_cleanup_worker(self):
        """Stop the cleanup worker thread."""
        self._stop_cleanup.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=2)
    
    def _worker(self, job_id: str):
        """
        Background worker that executes a scrape job.
        
        Updates shared progress snapshot after each chapter, checks cancel flag
        at loop boundaries, writes EPUB to store on success, and transitions
        status to completed/failed/cancelled.
        
        Args:
            job_id: Job identifier
            
        Validates: Requirements 6.1, 6.2, 9.2, 9.3 (worker behavior and cancellation)
        """
        def progress_callback(event: Dict[str, Any]):
            """Progress callback that updates job state."""
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                
                # Check cancel flag at every callback (loop boundary - Req 9.2)
                if job.cancel_requested:
                    # Worker will detect this and stop
                    return
                
                event_type = event.get("type")
                
                # Update stage
                if event_type == "stage":
                    job.stage = event.get("stage", job.stage)
                
                # Update fetched count (Req 6.2)
                if event_type == "chapter_complete":
                    job.fetched = event.get("fetched", job.fetched)
                
                # Record messages for translation failures, cover issues, etc.
                if event_type in ("translation_failure", "cover_unavailable", "cover_invalid"):
                    msg = self._format_message(event)
                    if msg:
                        job.messages.append(msg)
        
        try:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                params = job.params
            
            # Run the scrape (blocking call)
            # The progress_callback checks cancel flag and will raise if cancelled
            epub_bytes = run_scrape(params, progress_callback)
            
            # Check if cancelled during scrape
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                
                if job.cancel_requested:
                    # Cancelled - don't produce EPUB (Req 9.3)
                    job.status = JobStatus.CANCELLED
                    job.stage = "cancelled"
                    job.completed_at = datetime.utcnow()
                    return
            
            # Success - store EPUB and mark complete
            self._epub_store.put(job_id, epub_bytes)
            
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                
                job.status = JobStatus.COMPLETED
                job.stage = "completed"
                job.completed_at = datetime.utcnow()
                # Set expiry to 30 minutes after completion (Req 5.5)
                job.expires_at = job.completed_at + timedelta(minutes=30)
        
        except Exception as e:
            # Failed
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    return
                
                # Check if it was a cancellation-induced exception
                if job.cancel_requested:
                    job.status = JobStatus.CANCELLED
                    job.stage = "cancelled"
                else:
                    job.status = JobStatus.FAILED
                    job.stage = "failed"
                    job.error = str(e)
                
                job.completed_at = datetime.utcnow()
    
    def _format_message(self, event: Dict[str, Any]) -> Optional[str]:
        """Format a progress event into a user-facing message."""
        event_type = event.get("type")
        
        if event_type == "translation_failure":
            field = event.get("field", "text")
            index = event.get("index", "?")
            return f"Chapter {index} {field} translation failed, using original text"
        
        elif event_type == "cover_unavailable":
            reason = event.get("reason", "unknown")
            return f"Cover image unavailable: {reason}"
        
        elif event_type == "cover_invalid":
            reason = event.get("reason", "unknown")
            return f"Cover image invalid: {reason}"
        
        return None


# Singleton instance for the application
_manager_instance: Optional[JobManager] = None
_instance_lock = threading.Lock()


def get_manager() -> JobManager:
    """
    Get the singleton job manager instance.
    
    Returns:
        The global JobManager instance
    """
    global _manager_instance
    if _manager_instance is None:
        with _instance_lock:
            if _manager_instance is None:
                _manager_instance = JobManager()
                _manager_instance.start_cleanup_worker()
    return _manager_instance


def reset_manager(epub_store=None) -> JobManager:
    """
    Reset the singleton manager instance (primarily for testing).
    
    Args:
        epub_store: Optional EpubStore for the new manager
        
    Returns:
        The new JobManager instance
    """
    global _manager_instance
    with _instance_lock:
        if _manager_instance:
            _manager_instance.stop_cleanup_worker()
        _manager_instance = JobManager(epub_store=epub_store)
        _manager_instance.start_cleanup_worker()
        return _manager_instance
