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
        Papers(papers);
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
const ADMIN_KEY = "IHAVEAPLANA."
function isAdminMode() {
    // Check URL for ?admin=1
    const urlParams = new URLSearchParams(window.location.search);
    // Check localStorage
    return urlParams.get('admin') === ADMIN_KEY;
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
                    <button class="preview-btn" onclick="previewPaper('${p.supabase_url}')">Preview</button>
                    <button class="download-btn" onclick="downloadPaper('${p.filename}')">Download</button>
                    <button class="ai-btn" onclick="generateQuestions('${p.filename})">AI Questions</button>
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
        }else if(response.status === 429){
            alert("Too many attempts, Please wait a minute and try again.");
        }
         else {
            alert("❌ " + (data.message || data.error));
        }
    } catch (error) {
        alert("❌ Delete failed. Is the backend running?");
        console.error(error);
    }
}
 function downloadPaper(filename) {
    window.location.href = `${API_URL}/download/${encodeURIComponent(filename)}`;
 }

function previewPaper(url){
    if(!url){
        alert("NO preview available for this paper.");
        return;
    }
    window.open(url,'_blank');
}

// ─── AI QUESTION GENERATOR ───
async function generateQuestions(filename) {
    const modal = document.getElementById('aiModal');
    const content = document.getElementById('aiContent');
    modal.style.display = 'flex';
    content.innerHTML = '<p style="text-align:center;color:#888;">🤖 Generating questions... 5-10 seconds.</p>';

    try {
        const response = await fetch(`${API_URL}/generate-questions/${encodeURIComponent(filename)}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (response.ok) {
            content.innerHTML = `
                <h3 style="color: var(--accent); margin-bottom: 15px;">📝 Practice Questions</h3>
                <div style="white-space: pre-wrap; line-height: 1.8;">${data.questions}</div>
                <p style="margin-top: 20px; font-size: 13px; color: #888; text-align: center;">AI-generated · Verify with your textbook</p>
            `;
        } else {
            content.innerHTML = `<p style="color: #EF4444;">❌ ${data.message || 'AI failed'}</p>`;
        }
    } catch (error) {
        content.innerHTML = '<p style="color: #EF4444;">❌ Could not reach AI.</p>';
        console.error(error);
    }
}

function closeAIModal() {
    document.getElementById('aiModal').style.display = 'none';
}