# Test Support Harness

This directory contains test support utilities for the webnovel scraper project.

## Overview

The test harness provides infrastructure for testing the JobManager's admission control and slot lifecycle without network or filesystem dependencies.

## Components

### `fake_scrape.py`

Provides the complete test harness infrastructure for testing admission control.

#### FakeEpubStore

An in-memory EPUB store that mimics the interface of the real `EpubStore` class.

**Features:**
- Stores EPUB bytes in a Python dict instead of filesystem
- Thread-safe operations
- Full API compatibility with real EpubStore (put, get, delete, exists, cleanup_all)

**Usage:**
```python
from tests.support.fake_scrape import FakeEpubStore

store = FakeEpubStore()
store.put("job-123", b"fake epub content")
epub_bytes = store.get("job-123")
store.delete("job-123")
```

#### FakeScrapeHarness

Controls scrape job execution for deterministic testing.

**Features:**
- Per-job `threading.Event` gates to control when jobs complete
- Per-job exit modes: SUCCESS, RAISE, CANCEL_OBSERVED
- Release counter to verify exactly-once slot release semantics
- Thread-safe operations

**Exit Modes:**
- `ExitMode.SUCCESS`: Job completes successfully and returns fake EPUB bytes
- `ExitMode.RAISE`: Job raises a "Simulated scrape failure" exception
- `ExitMode.CANCEL_OBSERVED`: Job raises a "Job was cancelled" exception

**Usage:**
```python
from tests.support.fake_scrape import FakeScrapeHarness, ExitMode

harness = FakeScrapeHarness()

# Configure a job to succeed after manual release
harness.set_exit_mode("job-123", ExitMode.SUCCESS)

# Get a fake scrape function
scrape_fn = harness.make_scrape_callable()

# In your test, start the job (it will block on the gate)
# ... job runs in background thread ...

# Release the job to complete
harness.release("job-123")

# Or release all jobs at once
harness.release_all()

# Verify exactly-once slot release
assert harness.get_release_count("job-123") == 1
```

#### make_test_manager()

Factory function that creates a JobManager configured for testing.

**Features:**
- Small default limits for easy saturation: max_concurrency=2, max_queue_depth=3
- Uses FakeEpubStore automatically (no filesystem access)
- Supports custom limits for different test scenarios
- Forward-compatible with future admission control parameters

**Usage:**
```python
from tests.support.fake_scrape import make_test_manager

# Create with default small limits (2 concurrent, 3 queued)
manager = make_test_manager()

# Create with custom limits
manager = make_test_manager(
    max_concurrency=5,
    max_queue_depth=10,
    session_active_limit=2
)

# Use custom stores and harness
custom_store = FakeEpubStore()
custom_harness = FakeScrapeHarness()
manager = make_test_manager(
    epub_store=custom_store,
    harness=custom_harness
)
```

## Integration with Tests

### Property-Based Tests (Hypothesis)

Use the harness in property tests to control job execution:

```python
from hypothesis import given, strategies as st
from tests.support.fake_scrape import make_test_manager, FakeScrapeHarness, ExitMode

@given(st.lists(st.text(), min_size=1, max_size=10))
def test_admission_property(job_ids):
    harness = FakeScrapeHarness()
    manager = make_test_manager(
        max_concurrency=2,
        max_queue_depth=3,
        harness=harness
    )
    
    # Configure all jobs to succeed
    for job_id in job_ids:
        harness.set_exit_mode(job_id, ExitMode.SUCCESS)
    
    # Submit jobs and verify capacity invariants
    # ...
```

### Unit Tests

Use the harness for deterministic unit testing:

```python
from tests.support.fake_scrape import make_test_manager, FakeScrapeHarness, ExitMode

def test_exactly_once_release():
    harness = FakeScrapeHarness()
    manager = make_test_manager(harness=harness)
    
    harness.set_exit_mode("job-1", ExitMode.SUCCESS)
    
    # Submit job (will block on gate)
    job_id = manager.create_job({...})
    
    # Release to complete
    harness.release(job_id)
    
    # Wait for completion
    wait_for_completion(manager, job_id)
    
    # Verify exactly one release
    assert harness.get_release_count(job_id) == 1
```

### Integration Tests

Use FakeEpubStore to avoid filesystem access:

```python
from tests.support.fake_scrape import FakeEpubStore
from job_manager import reset_manager

def test_job_completion_and_download():
    store = FakeEpubStore()
    manager = reset_manager(epub_store=store)
    
    # Run job to completion
    job_id = manager.create_job({...})
    wait_for_completion(manager, job_id)
    
    # Verify EPUB was stored
    assert store.exists(job_id)
    epub_bytes = store.get(job_id)
    assert epub_bytes is not None
```

## Testing the Harness Itself

The harness includes its own test suite:

```bash
pytest tests/support/test_fake_scrape_harness.py -v
```

Tests verify:
- FakeEpubStore operations (put, get, delete, cleanup)
- Gate blocking and release mechanisms
- Exit mode behaviors (success, raise, cancel)
- Release counter tracking
- Manager factory with various configurations

## Requirements Validated

- **Requirement 1.7**: JobManager SHALL expose Max_Concurrency and Max_Queue_Depth as constructor parameters
- **Requirement 8.5**: JobManager SHALL release the concurrency slot exactly once per job

## Design Alignment

This harness implements the "Test harness" section from the design document:

> A `tests/support/fake_scrape.py` helper provides a controllable worker body:
> - A `threading.Event` per job that the stub blocks on
> - A per-job exit mode: `success`, `raise`, or `cancel-observed`
> - A release counter keyed by job id, incremented inside `_release_slot`

The harness enables deterministic testing of admission control logic without:
- Real network requests (no scraper_service.run_scrape calls)
- Filesystem access (FakeEpubStore stores in memory)
- Long-running jobs (gates can be released immediately)
- Race conditions (manual control over when jobs complete)
