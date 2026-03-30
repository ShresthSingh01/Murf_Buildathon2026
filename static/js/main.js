document.addEventListener('DOMContentLoaded', () => {
    // Selectors
    const fileInput = document.getElementById('file-input');
    const uploadBtn = document.getElementById('upload-btn');
    const dropZone = document.getElementById('drop-zone');
    const selectedFileName = document.getElementById('selected-file-name');
    const processBtnContainer = document.getElementById('process-btn-container');
    const processBtn = document.getElementById('process-btn');
    const flowItemSelect = document.getElementById('flow-item-select');
    const flowItemVerify = document.getElementById('flow-item-verify');
    const flowItemExplain = document.getElementById('flow-item-explain');
    const themeToggle = document.getElementById('theme-toggle');
    const heroCta = document.getElementById('hero-cta');

    let selectedLang = 'en';

    // --- Theme Toggle (persisted via localStorage) ---
    function applyTheme() {
        const theme = localStorage.getItem('medilo-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', theme);
        document.body.setAttribute('data-theme', theme);
        if (themeToggle) {
            themeToggle.querySelector('.material-symbols-rounded').textContent =
                theme === 'dark' ? 'light_mode' : 'dark_mode';
        }
    }
    applyTheme();

    themeToggle?.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        localStorage.setItem('medilo-theme', next);
        applyTheme();
    });

    // --- Animations: Intersection Observer ---
    const revealObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) entry.target.classList.add('in-view');
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.reveal-up').forEach(el => revealObserver.observe(el));

    // --- Hero CTA ---
    heroCta?.addEventListener('click', () => {
        document.getElementById('upload-section').scrollIntoView({ behavior: 'smooth', block: 'center' });
    });

    // --- Language Selection ---
    document.querySelectorAll('.lang-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedLang = btn.dataset.lang;
        });
    });

    // --- Upload Logic ---
    uploadBtn?.addEventListener('click', () => fileInput.click());

    fileInput?.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFileSelect(file);
    });

    dropZone?.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragging');
    });

    dropZone?.addEventListener('dragleave', () => dropZone.classList.remove('dragging'));

    dropZone?.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragging');
        const file = e.dataTransfer.files[0];
        if (file && file.type === 'application/pdf') {
            fileInput.files = e.dataTransfer.files;
            handleFileSelect(file);
        }
    });

    function handleFileSelect(file) {
        selectedFileName.textContent = `READY: ${file.name.toUpperCase()}`;
        processBtnContainer.classList.remove('hidden');
        setUploadStep('verify');
    }

    function setUploadStep(stage) {
        [flowItemSelect, flowItemVerify, flowItemExplain].forEach(item => item.classList.remove('active', 'done'));
        if (stage === 'select') flowItemSelect.classList.add('active');
        if (stage === 'verify') {
            flowItemSelect.classList.add('done');
            flowItemVerify.classList.add('active');
        }
    }

    // --- Process Report (Submit & Redirect) ---
    processBtn?.addEventListener('click', async () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('language', selectedLang);

        processBtn.disabled = true;
        processBtn.textContent = 'Uploading...';

        try {
            const response = await fetch('/upload', { method: 'POST', body: formData });
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            if (data.redirect) window.location.href = data.redirect;
        } catch (error) {
            console.error(error);
            alert('Upload failed. Please try again.');
            processBtn.disabled = false;
            processBtn.innerHTML = '<span class="material-symbols-rounded">smart_toy</span> Begin Health Analysis';
        }
    });
});
