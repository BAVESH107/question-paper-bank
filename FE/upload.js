const API_URL="https://question-paper-bank.onrender.com";
document.getElementById('uploadForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    const fileInput = document.getElementById('file');
    const file = fileInput.files[0];

    if (!file) {
        showMessage("❌ Please select a PDF file.", "error");
        return;
    }

    // ─── BUILD FORM DATA ───
    const formData = new FormData();
    formData.append('file', file);
    formData.append('subject', document.getElementById('subject').value.trim());
    formData.append('semester', document.getElementById('semester').value);
    formData.append('department', document.getElementById('department').value);
    formData.append('year', document.getElementById('year').value.trim());
    formData.append('exam_type', document.getElementById('exam_type').value);
    formData.append('uploaded_by', document.getElementById('uploaded_by').value.trim());
    formData.append('admin_password', document.getElementById('admin_password').value.trim());

    showMessage("⏳ Uploading...", "info");

    try {
        const response = await fetch(`${API_URL}/upload`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            showMessage("✅ " + data.message, "success");
            document.getElementById('uploadForm').reset();
        }else if(response.status === 429){
            alert("Too many attempts, Please wait a minute and try again.");
        } 
        else {
            showMessage("❌ " + (data.message || data.error), "error");
        }
    } catch (error) {
        showMessage("❌ Upload failed. Is the backend running?", "error");
        console.error(error);
    }
});

function showMessage(msg, type) {
    const div = document.getElementById('message');
    div.innerHTML = msg;
    div.className = 'message-box ' + type;
    div.style.display = 'block';
    div.scrollIntoView({behaviour:'smooth',block:'center'});
}