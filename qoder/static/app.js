// Research Document Search Assistant - Frontend Logic

const API_BASE = '/api/documents';

// Search documents
async function searchDocuments() {
    const keyword = document.getElementById('searchInput').value.trim();
    const docType = document.getElementById('typeFilter').value;
    const tag = document.getElementById('tagFilter').value.trim();
    
    if (!keyword) {
        showResults([]);
        return;
    }
    
    let url = `${API_BASE}/search?keyword=${encodeURIComponent(keyword)}`;
    if (docType) url += `&doc_type=${encodeURIComponent(docType)}`;
    if (tag) url += `&tag=${encodeURIComponent(tag)}`;
    
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const results = await response.json();
        showResults(results, keyword);
    } catch (err) {
        document.getElementById('resultsList').innerHTML = 
            `<p class="placeholder" style="color:red;">搜索出错: ${escapeHtml(err.message)}</p>`;
    }
}

// Display results
function showResults(results, keyword) {
    const container = document.getElementById('resultsList');
    
    if (!results || results.length === 0) {
        container.innerHTML = '<p class="placeholder">未找到匹配的资料</p>';
        return;
    }
    
    container.innerHTML = results.map(r => `
        <div class="result-item">
            <div class="result-header">
                <span class="result-title" onclick="showDetail(${r.id})">${escapeHtml(r.title)}</span>
                <div class="result-meta">
                    <span class="badge badge-${['reading', 'experiment', 'todo'].includes(r.doc_type) ? r.doc_type : 'reading'}">${escapeHtml(getTypeName(r.doc_type))}</span>
                    <span>${escapeHtml(r.source_file)}</span>
                </div>
            </div>
            ${r.tags ? `<div class="result-meta">标签: ${escapeHtml(r.tags)}</div>` : ''}
            <div class="result-paragraph">${highlightKeyword(escapeHtml(r.matched_paragraph), keyword)}</div>
            <div class="result-actions">
                <button class="btn-delete" onclick="deleteDocument(${r.id})">删除</button>
            </div>
        </div>
    `).join('');
}

// Show document detail
async function showDetail(id) {
    try {
        const response = await fetch(`${API_BASE}/${id}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const doc = await response.json();
        
        const paragraphs = doc.paragraphs ? JSON.parse(doc.paragraphs) : [doc.content];
        
        document.getElementById('detailContent').innerHTML = `
            <h2>${escapeHtml(doc.title)}</h2>
            <div class="detail-meta">
                <p>类型: ${escapeHtml(getTypeName(doc.doc_type))} | 来源: ${escapeHtml(doc.source_file)}</p>
                ${doc.tags ? `<p>标签: ${escapeHtml(doc.tags)}</p>` : ''}
                <p>上传时间: ${doc.created_at ? new Date(doc.created_at).toLocaleString() : '未知'}</p>
            </div>
            <div class="detail-body">${paragraphs.map(p => escapeHtml(p)).join('\n\n')}</div>
        `;
        document.getElementById('detailModal').style.display = 'flex';
    } catch (err) {
        alert('获取详情失败: ' + err.message);
    }
}

function closeModal() {
    document.getElementById('detailModal').style.display = 'none';
}

// Upload files
async function uploadFiles(files) {
    const status = document.getElementById('uploadStatus');
    status.innerHTML = '';
    
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch(`${API_BASE}/upload`, {
                method: 'POST',
                body: formData,
            });
            
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || `HTTP ${response.status}`);
            }
            
            const doc = await response.json();
            status.innerHTML += `<p style="color:green;">✓ 已上传: ${escapeHtml(doc.title)} (ID: ${doc.id})</p>`;
        } catch (err) {
            status.innerHTML += `<p style="color:red;">✗ 上传失败 ${escapeHtml(file.name)}: ${escapeHtml(err.message)}</p>`;
        }
    }
}

// Delete document
async function deleteDocument(id) {
    if (!confirm('确定删除此文档？')) return;
    
    try {
        const response = await fetch(`${API_BASE}/${id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        // Re-search
        searchDocuments();
    } catch (err) {
        alert('删除失败: ' + err.message);
    }
}

// Helpers
function getTypeName(type) {
    const names = { reading: '阅读笔记', experiment: '实验记录', todo: '待办' };
    return names[type] || type;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function highlightKeyword(text, keyword) {
    if (!keyword) return text;
    const regex = new RegExp(`(${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    // Search on Enter
    document.getElementById('searchInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') searchDocuments();
    });
    
    // File upload
    const fileInput = document.getElementById('fileInput');
    const dropZone = document.getElementById('dropZone');
    
    fileInput.addEventListener('change', (e) => {
        uploadFiles(e.target.files);
    });
    
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '#1a73e8';
    });
    
    dropZone.addEventListener('dragleave', () => {
        dropZone.style.borderColor = '#ccc';
    });
    
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '#ccc';
        uploadFiles(e.dataTransfer.files);
    });
});
