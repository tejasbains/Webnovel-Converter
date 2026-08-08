"""
EPUB Store Module

Stores each job's EPUB bytes keyed by job ID using temporary files.
Provides put, get, and delete operations with cleanup support driven by job expiry.

Validates Requirements 5.2, 5.5
"""

import os
import tempfile
from pathlib import Path
from typing import Optional
import threading


class EpubStore:
    """
    Thread-safe storage for EPUB files keyed by job ID.
    
    Stores EPUB bytes as temporary files under tempfile.gettempdir()/webnovel_jobs/
    to support the ≥30 min retention window required by Requirement 5.5.
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize the EPUB store.
        
        Args:
            base_dir: Base directory for storing EPUB files. 
                     Defaults to tempfile.gettempdir()/webnovel_jobs/
        """
        if base_dir is None:
            base_dir = Path(tempfile.gettempdir()) / "webnovel_jobs"
        
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
    
    def _get_path(self, job_id: str) -> Path:
        """
        Get the file path for a job's EPUB.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Path object for the EPUB file
        """
        return self.base_dir / f"{job_id}.epub"
    
    def put(self, job_id: str, epub_bytes: bytes) -> None:
        """
        Store EPUB bytes for a job.
        
        Args:
            job_id: The job identifier
            epub_bytes: The EPUB file content as bytes
            
        Validates: Requirement 5.2 (store for delivery)
        """
        with self._lock:
            path = self._get_path(job_id)
            path.write_bytes(epub_bytes)
    
    def get(self, job_id: str) -> Optional[bytes]:
        """
        Retrieve EPUB bytes for a job.
        
        Args:
            job_id: The job identifier
            
        Returns:
            The EPUB file content as bytes, or None if not found
            
        Validates: Requirement 5.2 (deliver exact stored bytes)
        """
        with self._lock:
            path = self._get_path(job_id)
            if path.exists():
                try:
                    return path.read_bytes()
                except (OSError, IOError):
                    # File may have been deleted between exists check and read
                    return None
            return None
    
    def delete(self, job_id: str) -> bool:
        """
        Delete the EPUB file for a job.
        
        Args:
            job_id: The job identifier
            
        Returns:
            True if the file was deleted, False if it didn't exist
            
        Supports cleanup driven by job manager's expiry (Requirement 5.5)
        """
        with self._lock:
            path = self._get_path(job_id)
            if path.exists():
                try:
                    path.unlink()
                    return True
                except (OSError, IOError):
                    # File may have been deleted by another process
                    return False
            return False
    
    def exists(self, job_id: str) -> bool:
        """
        Check if an EPUB file exists for a job.
        
        Args:
            job_id: The job identifier
            
        Returns:
            True if the file exists, False otherwise
        """
        with self._lock:
            path = self._get_path(job_id)
            return path.exists()
    
    def cleanup_all(self) -> int:
        """
        Remove all EPUB files from the store.
        
        This is primarily used for testing or maintenance.
        For normal operation, use delete() on individual jobs as they expire.
        
        Returns:
            Number of files deleted
        """
        with self._lock:
            count = 0
            if self.base_dir.exists():
                for epub_file in self.base_dir.glob("*.epub"):
                    try:
                        epub_file.unlink()
                        count += 1
                    except (OSError, IOError):
                        # Skip files that can't be deleted
                        pass
            return count


# Singleton instance for the application
_store_instance: Optional[EpubStore] = None
_instance_lock = threading.Lock()


def get_store() -> EpubStore:
    """
    Get the singleton EPUB store instance.
    
    Returns:
        The global EpubStore instance
    """
    global _store_instance
    if _store_instance is None:
        with _instance_lock:
            if _store_instance is None:
                _store_instance = EpubStore()
    return _store_instance


def reset_store(base_dir: Optional[Path] = None) -> EpubStore:
    """
    Reset the singleton store instance (primarily for testing).
    
    Args:
        base_dir: Optional base directory for the new store
        
    Returns:
        The new EpubStore instance
    """
    global _store_instance
    with _instance_lock:
        _store_instance = EpubStore(base_dir=base_dir)
        return _store_instance
