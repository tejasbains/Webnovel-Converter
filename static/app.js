/**
 * Frontend JavaScript for webnovel scraper webapp
 * 
 * Handles client-side validation, job submission, polling, progress display,
 * cancellation, and download.
 * 
 * Validates Requirements: 1.4, 1.5, 1.6, 4.1, 5.1, 5.6, 6.1, 6.2, 6.3, 6.4, 
 * 6.5, 6.6, 8.1, 8.3, 8.5, 9.1, 9.4
 */

// State
let currentJobId = null;
let pollInterval = null;

// DOM elements
const form = document.getElementById('scrapeForm');
const startBtn = document.getElementById('startBtn');
const cancelBtn = document.getElementById('cancelBtn');
const downloadBtn = document.getElementById('downloadBtn');
const progressSection = document.getElementById('progressSection');
const progressTitle = document.getElementById('progressTitle');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const messagesList = document.getElementById('messagesList');

// Form inputs
const sourceUrlInput = document.getElementById('sourceUrl');
const titleInput = document.getElementById('title');
const authorInput = document.getElementById('author');
const fileNameInput = document.getElementById('fileName');
const chapterCountInput = document.getElementById('chapterCount');
const translateInput = document.getElementById('translate');

// Error message elements
const errorElements = {
    sourceUrl: document.getElementById('error-sourceUrl'),
    title: document.getElementById('error-title'),
    chapterCount: document.getElementById('error-chapterCount')
};


/**
 * Client-side validation mirroring server rules
 * Validates: Requirements 1.4, 1.5, 1.6, 8.1
 */
function validateForm() {
    let isValid = true;
    const errors = {};
    
    // Clear previous errors
    Object.values(errorElements).forEach(el => {
        el.classList.remove('show');
        el.textContent = '';
    });
    
    // Validate source URL (Req 1.4)
    const sourceUrl = sourceUrlInput.value.trim();
    if (!sourceUrl) {
        errors.sourceUrl = 'Source URL is required';
        isValid = false;
    } else {
        try {
            const url = new URL(sourceUrl);
            if (url.protocol !== 'http:' && url.protocol !== 'https:') {
                errors.sourceUrl = 'Source URL must be a valid HTTP or HTTPS URL';
                isValid = false;
            }
        } catch (e) {
            errors.sourceUrl = 'Source URL must be a valid HTTP or HTTPS URL';
            isValid = false;
        }
    }
    
    // Validate title (Req 1.6)
    const title = titleInput.value.trim();
    if (!title) {
        errors.title = 'Title is required';
        isValid = false;
    }
    
    // Validate chapter count (Req 1.5)
    const chapterCount = chapterCountInput.value.trim();
    if (!chapterCount) {
        errors.chapterCount = 'Chapter count is required';
        isValid = false;
    } else {
        const count = parseInt(chapterCount, 10);
        if (isNaN(count)) {
            errors.chapterCount = 'Chapter count must be a valid integer';
            isValid = false;
        } else if (count < 1 || count > 5000) {
            errors.chapterCount = 'Chapter count must be between 1 and 5000';
            isValid = false;
        }
    }
    
    // Display errors
    Object.keys(errors).forEach(field => {
        if (errorElements[field]) {
            errorElements[field].textContent = errors[field];
            errorElements[field].classList.add('show');
        }
    });
    
    return isValid;
}


/**
 * Submit form and start scrape job
 * Validates: Requirement 1.3 (job submission)
 */
async function startScrape(event) {
    event.preventDefault();
    
    // Client-side validation
    if (!validateForm()) {
        return;
    }
    
    // Gather form data
    const formData = {
        source_url: sourceUrlInput.value.trim(),
        title: titleInput.value.trim(),
        author: authorInput.value.trim(),
        file_name: fileNameInput.value.trim(),
        chapter_count: parseInt(chapterCountInput.value.trim(), 10),
        translate: translateInput.checked
    };
    
    try {
        // Disable start button (Req 6.4)
        startBtn.disabled = true;
        startBtn.textContent = 'Starting...';
        
        // Submit to API
        const response = await fetch('/api/jobs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });
        
        const data = await response.json();
        
        if (response.status === 400) {
            // Server validation errors (Req 8.1)
            displayServerErrors(data.errors);
            startBtn.disabled = false;
            startBtn.textContent = 'Start Scrape';
            return;
        }
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to start job');
        }
        
        // Job started successfully
        currentJobId = data.jobId;
        
        // Show progress section and cancel button (Req 6.1, 9.1)
        progressSection.classList.add('show');
        cancelBtn.classList.remove('hidden');
        downloadBtn.classList.add('hidden');
        
        // Start polling
        startPolling();
        
    } catch (error) {
        alert('Error starting scrape: ' + error.message);
        startBtn.disabled = false;
        startBtn.textContent = 'Start Scrape';
    }
}


/**
 * Display server-side validation errors
 * Validates: Requirement 8.1 (retain entered values, show per-field errors)
 */
function displayServerErrors(errors) {
    Object.keys(errors).forEach(field => {
        // Map API field names to error element IDs
        const fieldMap = {
            'source_url': 'sourceUrl',
            'chapter_count': 'chapterCount'
        };
        const errorField = fieldMap[field] || field;
        
        if (errorElements[errorField]) {
            errorElements[errorField].textContent = errors[field];
            errorElements[errorField].classList.add('show');
        }
    });
}


/**
 * Start polling job status
 * Validates: Requirements 6.1, 6.2 (progress feedback)
 */
function startPolling() {
    // Poll every 1 second
    pollInterval = setInterval(pollJobStatus, 1000);
    // Initial poll
    pollJobStatus();
}


/**
 * Stop polling
 */
function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}


/**
 * Poll job status and update UI
 * Validates: Requirements 6.1, 6.2, 6.3, 6.6 (progress display)
 */
async function pollJobStatus() {
    if (!currentJobId) {
        stopPolling();
        return;
    }
    
    try {
        const response = await fetch(`/api/jobs/${currentJobId}`);
        
        if (!response.ok) {
            throw new Error('Failed to fetch job status');
        }
        
        const job = await response.json();
        
        // Update progress UI
        updateProgressUI(job);
        
        // Check if job is terminal
        if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
            stopPolling();
            handleJobComplete(job);
        }
        
    } catch (error) {
        console.error('Error polling job status:', error);
    }
}


/**
 * Update progress UI with job data
 * Validates: Requirements 6.2 (chapter count display)
 */
function updateProgressUI(job) {
    // Update title based on status
    if (job.status === 'running') {
        progressTitle.textContent = 'Scraping in progress...';
        progressTitle.className = 'progress-title status-running';
    } else if (job.status === 'completed') {
        progressTitle.textContent = 'Scrape completed!';
        progressTitle.className = 'progress-title status-completed';
    } else if (job.status === 'failed') {
        progressTitle.textContent = 'Scrape failed';
        progressTitle.className = 'progress-title status-failed';
    } else if (job.status === 'cancelled') {
        progressTitle.textContent = 'Scrape cancelled';
        progressTitle.className = 'progress-title status-cancelled';
    }
    
    // Update progress bar (Req 6.2)
    const percentage = job.total > 0 ? (job.fetched / job.total) * 100 : 0;
    progressBar.style.width = percentage + '%';
    
    // Update progress text (Req 6.2 - "X of Y chapters")
    progressText.textContent = `${job.fetched} of ${job.total} chapters • ${job.stage}`;
    
    // Update messages list
    if (job.messages && job.messages.length > 0) {
        messagesList.innerHTML = job.messages
            .map(msg => `<div>${escapeHtml(msg)}</div>`)
            .join('');
    }
    
    // Show error if failed (Req 6.6)
    if (job.status === 'failed' && job.error) {
        const errorMsg = `<div style="color: #c85a3e; font-weight: 600;">Error: ${escapeHtml(job.error)}</div>`;
        messagesList.innerHTML = errorMsg + messagesList.innerHTML;
    }
}


/**
 * Handle job completion (success, failure, or cancellation)
 * Validates: Requirements 5.1, 6.5, 9.4 (download control, re-enable start)
 */
function handleJobComplete(job) {
    // Re-enable start button (Req 6.5)
    startBtn.disabled = false;
    startBtn.textContent = 'Start Scrape';
    
    // Hide cancel button
    cancelBtn.classList.add('hidden');
    
    // Show download button only if completed successfully (Req 5.1)
    if (job.status === 'completed') {
        downloadBtn.classList.remove('hidden');
    }
}


/**
 * Request job cancellation
 * Validates: Requirements 9.1, 9.2, 9.4 (cancel control)
 */
async function cancelJob() {
    if (!currentJobId) {
        return;
    }
    
    try {
        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Cancelling...';
        
        const response = await fetch(`/api/jobs/${currentJobId}/cancel`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error('Failed to cancel job');
        }
        
        // Poll will pick up the cancelled status
        
    } catch (error) {
        alert('Error cancelling job: ' + error.message);
        cancelBtn.disabled = false;
        cancelBtn.textContent = 'Cancel';
    }
}


/**
 * Download completed EPUB
 * Validates: Requirements 5.2, 5.6 (download delivery, handle 410)
 */
async function downloadEpub() {
    if (!currentJobId) {
        return;
    }
    
    try {
        downloadBtn.disabled = true;
        downloadBtn.textContent = 'Downloading...';
        
        const response = await fetch(`/api/jobs/${currentJobId}/download`);
        
        if (response.status === 410) {
            // File no longer available (Req 5.6)
            alert('File is no longer available. It may have expired.');
            downloadBtn.classList.add('hidden');
            return;
        }
        
        if (!response.ok) {
            throw new Error('Failed to download EPUB');
        }
        
        // Get filename from Content-Disposition header
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'download.epub';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }
        
        // Download file
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        downloadBtn.disabled = false;
        downloadBtn.textContent = 'Download EPUB';
        
    } catch (error) {
        alert('Error downloading EPUB: ' + error.message);
        downloadBtn.disabled = false;
        downloadBtn.textContent = 'Download EPUB';
    }
}


/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


/**
 * Reset form and UI for a new job
 * Validates: Requirement 8.5 (clear errors on new job)
 */
function resetUI() {
    // Clear errors (Req 8.5)
    Object.values(errorElements).forEach(el => {
        el.classList.remove('show');
        el.textContent = '';
    });
    
    // Reset progress section
    progressSection.classList.remove('show');
    progressBar.style.width = '0%';
    progressText.textContent = '';
    messagesList.innerHTML = '';
    
    // Reset buttons
    startBtn.disabled = false;
    startBtn.textContent = 'Start Scrape';
    cancelBtn.classList.add('hidden');
    downloadBtn.classList.add('hidden');
    
    // Clear job ID
    currentJobId = null;
    stopPolling();
}


// Event listeners
form.addEventListener('submit', startScrape);
cancelBtn.addEventListener('click', cancelJob);
downloadBtn.addEventListener('click', downloadEpub);

// Reset UI when user starts typing in the form (clears previous errors - Req 8.5)
[sourceUrlInput, titleInput, chapterCountInput].forEach(input => {
    input.addEventListener('input', () => {
        if (currentJobId === null) {
            // Only clear errors if not currently running a job
            Object.values(errorElements).forEach(el => {
                el.classList.remove('show');
            });
        }
    });
});
