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
uploadForm.addEventListener('submit', function (e) {
    // Show processing overlay
    const btnText = processBtn.querySelector('span');
    btnText.textContent = 'Processing...';
    processingOverlay.classList.add('active');

    // Allow the form to submit naturally to trigger the file download
    // A timeout to reset the UI after 'download' starts (approximate)
    setTimeout(() => {
        btnText.textContent = 'Start Reconciliation';
        processingOverlay.classList.remove('active');
        fileInfo.innerHTML = "File processed! Check your downloads.";
    }, 5000);
});
