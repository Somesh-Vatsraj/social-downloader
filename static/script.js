const urlInput = document.getElementById('urlInput');
const downloadBtn = document.getElementById('downloadBtn');
const loading = document.getElementById('loading');
const errorBox = document.getElementById('errorBox');
const errorMessage = document.getElementById('errorMessage');
const resultBox = document.getElementById('resultBox');
const profileInfo = document.getElementById('profileInfo');
const caption = document.getElementById('caption');
const mediaList = document.getElementById('mediaList');

downloadBtn.addEventListener('click', handleDownload);
urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleDownload();
});

async function handleDownload() {
    const url = urlInput.value.trim();
    if (!url) return;

    // Reset UI
    loading.classList.remove('hidden');
    errorBox.classList.add('hidden');
    resultBox.classList.add('hidden');
    downloadBtn.disabled = true;

    try {
        const res = await fetch(`/api/download?url=${encodeURIComponent(url)}`);
        const data = await res.json();

        if (!data.success) {
            showError(data.message || 'Something went wrong');
            return;
        }

        showResult(data);
    } catch (err) {
        showError('Network error. Please try again.');
    } finally {
        loading.classList.add('hidden');
        downloadBtn.disabled = false;
    }
}

function showError(msg) {
    errorMessage.textContent = msg;
    errorBox.classList.remove('hidden');
}

function showResult(data) {
    // Profile info
    profileInfo.innerHTML = '';
    if (data.profile_image_uri) {
        const img = document.createElement('img');
        img.src = data.profile_image_uri;
        img.alt = 'Profile';
        profileInfo.appendChild(img);
    }
    if (data.username) {
        const span = document.createElement('span');
        span.className = 'username';
        span.textContent = `@${data.username}`;
        profileInfo.appendChild(span);
    }

    // Caption
    caption.textContent = data.caption || '';

    // Media list
    mediaList.innerHTML = '';
    if (data.media && data.media.length) {
        data.media.forEach(item => {
            const div = document.createElement('div');
            div.className = 'media-item';

            const meta = document.createElement('div');
            meta.className = 'meta';
            meta.textContent = `${item.type} • ${item.container || ''} • ${item.quality || ''}`;

            const link = document.createElement('a');
            link.href = item.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = `Download ${item.type}`;

            div.appendChild(meta);
            div.appendChild(link);
            mediaList.appendChild(div);
        });
    } else {
        mediaList.textContent = 'No media found.';
    }

    resultBox.classList.remove('hidden');
}