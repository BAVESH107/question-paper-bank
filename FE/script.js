const API_URL="https://question-paper-bank.onrender.com";
document.addEventListener('DOMContentLoaded', () => {
    loadAllPapers();
});

// ─── FETCH ALL PAPERS ───
async function loadAllPapers() {
    const list = document.getElementById('papersList');
    list.innerHTML = '<p class="loading">Loading papers...</p>';

    try {
        const response = await fetch(`${API_URL}/papers`);
        const papers = await response.json();
        displayPapers(papers);
    } catch (error) {
        list.innerHTML = '<p class="loading">❌ Could not connect to server. Is the backend running?</p>';
        console.error(error);
    }
}

// ─── SEARCH PAPERS ───
async function searchPapers() {
    const query = document.getElementById('searchInput').value.trim();
    const dept = document.getElementById('deptFilter').value;
    const sem = document.getElementById('semFilter').value;
    const year = document.getElementById('yearFilter').value.trim();

    const list = document.getElementById('papersList');
    list.innerHTML = '<p class="loading">Searching...</p>';

    const params = new URLSearchParams();
    if (query) params.append('q', query);
    if (dept) params.append('dept', dept);
    if (sem) params.append('sem', sem);
    if (year) params.append('year', year);

    try {
        const response = await fetch(`${API_URL}/search?${params.toString()}`);
        const papers = await response.json();
        displayPapers(papers);
    } catch (error) {
        list.innerHTML = '<p class="loading">❌ Search failed. Is the backend running?</p>';
        console.error(error);
    }
}

// ─── CHECK IF ADMIN MODE ───
const ADMIN_KEY = "BKL"
function isAdminMode() {
    // Check URL for ?admin=1
    const urlParams = new URLSearchParams(window.location.search);
    // Check localStorage
    return localStorage.getItem('adminMode') === ADMIN_KEY;
}

// ─── DISPLAY PAPERS ───
function displayPapers(papers) {
    const list = document.getElementById('papersList');
    const adminMode = isAdminMode();

    if (!papers || papers.length === 0) {
        list.innerHTML = `
            <div class="paper-card" style="text-align:center; border-left-color:#94a3b8;">
                <h3>📭 No papers found</h3>
                <p style="color:#64748b; font-size:14px;">Try a different search or check back later.Or press reset button once</p>
            </div>
        `;
        return;
    }

    let html = "";
    papers.forEach(p => {
        html += `
            <div class="paper-card">
                <h3>📄 ${p.subject || p.filename}</h3>
                <div class="paper-meta">
                    <span class="tag">${p.department || '—'}</span>
                    <span class="tag">Sem ${p.semester || '—'}</span>
                    <span class="tag">${p.year || '—'}</span>
                    <span class="tag">${p.exam_type || '—'}</span>
                </div>
                <div class="paper-actions">
                    <a href="${API_URL}/download/${encodeURIComponent(p.filename)}" target="_blank">
                        <button class="download-btn">⬇️ Download</button>
                    </a>
                    ${adminMode ? `<button class="delete-btn" onclick="deletePaper('${p.filename}')">🗑️ Delete</button>` : ''}
                </div>
            </div>
        `;
    });
    list.innerHTML = html;
}
// ─── DELETE PAPER ───
async function deletePaper(filename) {
    const password = prompt("🔐 Enter admin password to delete:");
    if (!password) return;

    const confirmDelete = confirm(`⚠️ Are you sure you want to delete "${filename}"?\n\nThis cannot be undone.`);
    if (!confirmDelete) return;

    try {
        const response = await fetch(`${API_URL}/delete/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
            headers: { 'X-Admin-Password': password }
        });

        const data = await response.json();

        if (response.ok) {
            alert("✅ " + data.message);
            loadAllPapers();
        } else {
            alert("❌ " + (data.message || data.error));
        }
    } catch (error) {
        alert("❌ Delete failed. Is the backend running?");
        console.error(error);
    }
}