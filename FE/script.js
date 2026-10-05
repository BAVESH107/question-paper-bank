const API_URL = "https://question-paper-bank.onrender.com";
fetch(`${API_URL}/api/track-view`,{method: 'POST'}).catch(()=>{});

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
        list.innerHTML = '<p class="loading">Could not connect to server. Please try again.</p>';
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
        list.innerHTML = '<p class="loading">Search failed. Please try again.</p>';
        console.error(error);
    }
}

// ─── CHECK IF ADMIN MODE ───
const ADMIN_KEY = "IHAVEAPLANA.";

function isAdminMode() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('admin') === ADMIN_KEY;
}

function displayPapers(papers) {
    const list = document.getElementById('papersList');
    const adminMode = isAdminMode();

    // If admin, inject the stats banner at the top
    if (adminMode) {
        injectAdminStats();
    }

    if (!papers || papers.length === 0) {
        list.innerHTML = `
            <div class="paper-card" style="text-align:center; padding: 40px;">
                <p style="color: var(--text-secondary); font-size: 14px;">No papers found. Try a different search or reset the filters.</p>
            </div>
        `;
        return;
    }

    let html = "";
    papers.forEach(p => {
        html += `
            <div class="paper-card">
                <h3>${p.subject || p.filename}</h3>
                <div class="paper-meta">
                    <span>${p.department || '—'}</span>
                    <span class="dot">·</span>
                    <span>Semester ${p.semester || '—'}</span>
                    <span class="dot">·</span>
                    <span>${p.year || '—'}</span>
                    <span class="dot">·</span>
                    <span>${p.exam_type || '—'}</span>
                </div>
                <div class="paper-actions">
                    <button class="preview-btn" onclick="previewPaper('${p.supabase_url}')">Preview</button>
                    <button class="ai-btn" onclick="generateQuestions('${p.filename}')">✦ AI Practice</button>
                    <button class="download-btn" onclick="downloadPaper('${p.filename}')">Download PDF</button>
                    ${adminMode ? `<button class="delete-btn" onclick="deletePaper('${p.filename}')">Delete</button>` : ''}
                </div>
            </div>
        `;
    });
    list.innerHTML = html;
}


// ─── INJECT ADMIN STATS BANNER ───
async function injectAdminStats() {
    // Don't re-inject if it already exists
    if (document.getElementById('adminStatsBanner')) return;

    const list = document.getElementById('papersList');
    const banner = document.createElement('div');
    banner.id = 'adminStatsBanner';
    banner.innerHTML = `<p style="color:#6B7280; font-size:13px; text-align:center;">Loading stats...</p>`;
    banner.style.cssText = 'background:#FFFFFF; border:1px solid #E5E7EB; border-radius:10px; padding:16px; margin-bottom:16px; display:flex; justify-content:space-around; text-align:center;';
    list.parentNode.insertBefore(banner, list);

    try {
        const password = localStorage.getItem('qs_admin_pass') || prompt("Enter admin password for stats:");
        if (!password) {
            banner.remove();
            return;
        }
        localStorage.setItem('qs_admin_pass', password);

        const response = await fetch(`${API_URL}/api/analytics`, {
            headers: { 'X-Admin-Password': password }
        });

        if (!response.ok) {
            banner.innerHTML = `<p style="color:#DC2626; font-size:13px;">Could not load stats.</p>`;
            return;
        }

        const data = await response.json();
        banner.innerHTML = `
            <div><p style="font-size:24px; font-weight:800; color:#2563EB; margin:0;">${data.total_views}</p><p style="font-size:11px; color:#6B7280; font-weight:600; margin:4px 0 0;">TOTAL VIEWS</p></div>
            <div><p style="font-size:24px; font-weight:800; color:#2563EB; margin:0;">${data.views_today}</p><p style="font-size:11px; color:#6B7280; font-weight:600; margin:4px 0 0;">TODAY</p></div>
            <div><p style="font-size:24px; font-weight:800; color:#2563EB; margin:0;">${data.views_this_week}</p><p style="font-size:11px; color:#6B7280; font-weight:600; margin:4px 0 0;">THIS WEEK</p></div>
        `;
    } catch (e) {
        banner.innerHTML = `<p style="color:#DC2626; font-size:13px;">Server error.</p>`;
    }
}
// ─── DELETE PAPER ───
async function deletePaper(filename) {
    const password = prompt("Enter admin password to delete:");
    if (!password) return;

    const confirmDelete = confirm(`Are you sure you want to delete "${filename}"?`);
    if (!confirmDelete) return;

    try {
        const response = await fetch(`${API_URL}/delete/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
            headers: { 'X-Admin-Password': password }
        });

        const data = await response.json();

        if (response.ok) {
            alert(data.message);
            loadAllPapers();
        } else if (response.status === 429) {
            alert("Too many attempts. Please wait a minute.");
        } else {
            alert(data.message || data.error);
        }
    } catch (error) {
        alert("Delete failed. Please try again.");
        console.error(error);
    }
}

// ─── DOWNLOAD PAPER ───
function downloadPaper(filename) {
    window.location.href = `${API_URL}/download/${encodeURIComponent(filename)}`;
}

// ─── PREVIEW PAPER ───
function previewPaper(url) {
    if (!url) {
        alert("No preview available.");
        return;
    }
    window.open(url, '_blank');
}

// ─── AI QUESTION GENERATOR (UPDATED) ───
async function generateQuestions(filename) {
    // Open a new tab immediately to show loading state
    const newTab = window.open('', '_blank');
    newTab.document.write(`
        <div style="text-align:center; font-family: sans-serif; margin-top: 50px; color:#6B7280;">
            <h2>Generating practice questions...</h2>
            <p>This may take up to 15 seconds. Please do not close this tab.</p>
        </div>
    `);

    try {
        // FIXED: Using API_URL constant and the correct endpoint
        const response = await fetch(`${API_URL}/generate-questions/${encodeURIComponent(filename)}`, {
            method: 'POST'
        });

        const contentType = response.headers.get("content-type");

        // Handle Rate Limiting (Too many requests)
        if (response.status === 429) {
            newTab.document.body.innerHTML = `
                <div style="text-align:center; font-family: sans-serif; margin-top: 50px; padding: 20px;">
                    <p style="color: #DC2626; font-size: 18px; font-weight: bold;">Too many requests!</p>
                    <p style="color: #6B7280; font-size: 14px; margin-top: 10px;">You have reached the limit. Please wait 60 seconds before trying again.</p>
                </div>`;
            return;
        }

        // If successful and it's a PDF
        if (response.ok && contentType && contentType.includes("application/pdf")) {
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            newTab.location.href = url;
        } else {
            // Handle other errors (like scanned PDFs or server crashes)
            let errorMsg = "AI generation failed.";
            try {
                const data = await response.json();
                errorMsg = data.message || data.error || errorMsg;
            } catch (e) {
                errorMsg = `Server error (${response.status})`;
            }
            newTab.document.body.innerHTML = `
                <div style="text-align:center; font-family: sans-serif; margin-top: 50px; padding: 20px;">
                    <p style="color: #DC2626; font-size: 16px;">${errorMsg}</p>
                    <p style="color: #6B7280; font-size: 13px; margin-top: 16px;">Please try again later.</p>
                </div>
            `;
        }
    } catch (error) {
        newTab.document.body.innerHTML = `
            <div style="text-align:center; font-family: sans-serif; margin-top: 50px; padding: 20px;">
                <p style="color: #DC2626; font-size: 16px;">Could not reach AI server.</p>
                <p style="color: #6B7280; font-size: 13px; margin-top: 16px;">Please check your internet connection and try again.</p>
            </div>
        `;
        console.error(error);
    }
}

// ─── CLOSE AI MODAL ───
function closeAIModal() {
    document.getElementById('aiModal').style.display = 'none';
}