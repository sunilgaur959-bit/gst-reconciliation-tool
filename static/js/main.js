const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const uploadForm = document.getElementById('upload-form');
const processBtn = document.getElementById('process-btn');
const processingOverlay = document.getElementById('processing-overlay');

// --- 3D TILT EFFECT ---
const card = document.querySelector('.glass-card');
const maxTilt = 5; // degrees

document.addEventListener('mousemove', (e) => {
    if (!card) return;

    // Calculate center of screen
    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;

    // Calculate raw mouse offset from center (0 to 1)
    const offsetX = (e.clientX - centerX) / centerX;
    const offsetY = (e.clientY - centerY) / centerY;

    // Calculate rotation
    const rotateY = offsetX * maxTilt;
    const rotateX = offsetY * maxTilt * -1; // Invert X for natural tilt

    card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg)`;
});

// --- PARTICLES ---
function createParticles() {
    const blobs = document.querySelector('.background-blobs');
    if (!blobs) return;

    for (let i = 0; i < 20; i++) {
        const particle = document.createElement('div');
        particle.classList.add('particle');

        // Random size
        const size = Math.random() * 5 + 2;
        particle.style.width = `${size}px`;
        particle.style.height = `${size}px`;

        // Random position
        particle.style.left = `${Math.random() * 100}%`;
        particle.style.top = `${Math.random() * 100}%`;

        // Random drift duration
        particle.style.animationDuration = `${Math.random() * 10 + 10}s`;

        // Random opacity delay
        particle.style.animationDelay = `${Math.random() * 5}s`;

        blobs.appendChild(particle);
    }
}
createParticles();


// Drag and drop events
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, highlight, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, unhighlight, false);
});

function highlight(e) {
    dropZone.classList.add('active');
}

function unhighlight(e) {
    dropZone.classList.remove('active');
}

// Handle dropped files
dropZone.addEventListener('drop', handleDrop, false);

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;

    if (files.length > 0) {
        handleFiles(files);
    }
}

// Handle browsed files
dropZone.addEventListener('click', () => {
    fileInput.click();
});

fileInput.addEventListener('change', function () {
    handleFiles(this.files);
});

function handleFiles(files) {
    if (files.length > 0) {
        const file = files[0];
        const fileType = file.name.split('.').pop().toLowerCase();

        if (['xls', 'xlsx'].includes(fileType)) {
            // Update input element if files came from drop
            if (fileInput.files !== files) {
                try {
                    fileInput.files = files;
                } catch (e) {
                    console.error("Could not set input files", e);
                }
            }

            fileInfo.innerHTML = `Selected: <strong>${file.name}</strong>`;
            processBtn.disabled = false;
        } else {
            fileInfo.innerHTML = `<span style="color: #ef4444;">Invalid file type. Please upload .xlsx or .xls</span>`;
            processBtn.disabled = true;
        }
    }
}

// Form Submission
uploadForm.addEventListener('submit', async function (e) {
    e.preventDefault(); // Stop natural submission

    // Show processing overlay
    const btnText = processBtn.querySelector('span');
    btnText.textContent = 'Processing...';
    processingOverlay.classList.add('active');

    const formData = new FormData(uploadForm);

    try {
        const response = await fetch('/', {
            method: 'POST',
            body: formData
        });

        // If the backend had an error, it redirects to the homepage and returns HTML
        const contentType = response.headers.get('Content-Type');
        if (contentType && contentType.includes('text/html')) {
            fileInfo.innerHTML = `<span style="color: #ef4444;">Error processing file or invalid format. Refresh and try again.</span>`;
            return;
        }

        if (response.ok) {
            const blob = await response.blob();
            
            // Get filename from header if possible
            let filename = "Reconciled_GST.xlsx";
            const disposition = response.headers.get('Content-Disposition');
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                const matches = filenameRegex.exec(disposition);
                if (matches != null && matches[1]) { 
                  filename = matches[1].replace(/['"]/g, '');
                }
            }

            const url = window.URL.createObjectURL(blob);

            // Create a visible download button
            fileInfo.innerHTML = `
                <div style="margin-top: 15px; text-align: center;">
                    <p style="color: #4ade80; margin-bottom: 15px; font-weight: 600;">File successfully processed!</p>
                    <a href="${url}" download="${filename}" class="btn-primary" style="display: inline-flex; text-decoration: none; width: auto; padding: 12px 24px;">
                        <span>Download Result</span>
                        <i class="fa-solid fa-download"></i>
                    </a>
                </div>
            `;
            
            // We can optionally trigger the download automatically as well
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            // Keep the URL alive so the visible Download button works
            setTimeout(() => window.URL.revokeObjectURL(url), 600000); // Revoke after 10 mins
        } else {
            fileInfo.innerHTML = `<span style="color: #ef4444;">Server error occurred.</span>`;
        }
    } catch (error) {
        fileInfo.innerHTML = `<span style="color: #ef4444;">Network error: ${error.message}</span>`;
    } finally {
        btnText.textContent = 'Start Reconciliation';
        processingOverlay.classList.remove('active');
    }
});
