/**
 * Knowledge Base MCP Server - Web UI 应用逻辑
 */

// ===========================================
// 全局状态
// ===========================================

const state = {
    knowledgeBases: [],
    selectedKB: null,
    selectedFiles: [],
    currentPage: 'dashboard',
    settingsSchema: null,
    currentConfig: {}
};

// ===========================================
// API 调用
// ===========================================

const API = {
    /**
     * 基础请求方法
     */
    async request(url, options = {}) {
        try {
            const response = await fetch(url, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            return data;
        } catch (error) {
            console.error(`API Error: ${url}`, error);
            throw error;
        }
    },

    /**
     * 健康检查
     */
    async healthCheck() {
        return this.request('/health');
    },

    /**
     * 获取知识库列表
     */
    async listKnowledgeBases() {
        return this.request('/api/knowledge-bases');
    },

    /**
     * 创建知识库
     */
    async createKnowledgeBase(name, description = '') {
        return this.request(`/api/knowledge-bases?name=${encodeURIComponent(name)}&description=${encodeURIComponent(description)}`, {
            method: 'POST'
        });
    },

    /**
     * 获取知识库详情
     */
    async getKnowledgeBase(name) {
        return this.request(`/api/knowledge-bases/${encodeURIComponent(name)}`);
    },

    /**
     * 删除知识库
     */
    async deleteKnowledgeBase(name) {
        return this.request(`/api/knowledge-bases/${encodeURIComponent(name)}?confirm=true`, {
            method: 'DELETE'
        });
    },

    /**
     * 导入文档
     */
    async ingestDocument(kbName, filePath, extractEntities = true) {
        return this.request(`/api/knowledge-bases/${encodeURIComponent(kbName)}/ingest?file_path=${encodeURIComponent(filePath)}&extract_entities=${extractEntities}`, {
            method: 'POST'
        });
    },

    /**
     * 语义搜索
     */
    async search(kbName, query, topK = 5, type = 'vector') {
        if (type === 'hybrid') {
            return this.request(`/api/knowledge-bases/${encodeURIComponent(kbName)}/hybrid_search?query=${encodeURIComponent(query)}&top_k=${topK}`);
        }
        return this.request(`/api/knowledge-bases/${encodeURIComponent(kbName)}/search?query=${encodeURIComponent(query)}&top_k=${topK}`);
    },

    /**
     * 上传文件
     */
    async uploadFile(kbName, file, extractEntities = true) {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`/api/knowledge-bases/${encodeURIComponent(kbName)}/upload?extract_entities=${extractEntities}`, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || `HTTP ${response.status}`);
        }

        return data;
    },

    /**
     * 获取当前配置
     */
    async getConfig() {
        return this.request('/api/config');
    },

    /**
     * 更新配置
     */
    async updateConfig(settings) {
        return this.request('/api/config', {
            method: 'POST',
            body: JSON.stringify({ settings })
        });
    },

    /**
     * 获取提供商配置
     */
    async getProviders() {
        return this.request('/api/config/providers');
    },

    /**
     * 测试服务连接
     */
    async testConnection(service) {
        return this.request(`/api/config/test/${service}`, {
            method: 'POST'
        });
    }
};

// ===========================================
// 页面导航
// ===========================================

function navigateTo(page) {
    // 更新导航状态
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === page) {
            item.classList.add('active');
        }
    });

    // 更新页面显示
    document.querySelectorAll('.page').forEach(p => {
        p.classList.remove('active');
    });
    document.getElementById(`page-${page}`).classList.add('active');

    state.currentPage = page;

    // 加载页面数据
    switch (page) {
        case 'dashboard':
            refreshDashboard();
            break;
        case 'knowledge-bases':
            loadKnowledgeBases();
            break;
        case 'search':
            loadKBSelects();
            break;
        case 'upload':
            loadKBSelects();
            break;
        case 'settings':
            loadSettings();
            break;
    }
}

// ===========================================
// 仪表盘
// ===========================================

async function refreshDashboard() {
    try {
        // 检查服务状态
        const health = await API.healthCheck();
        document.getElementById('stat-status').textContent = '运行中';
        document.getElementById('stat-status').style.color = 'var(--success)';

        // 获取知识库列表
        const kbs = await API.listKnowledgeBases();
        state.knowledgeBases = kbs.data || [];

        // 更新统计
        document.getElementById('stat-kb-count').textContent = state.knowledgeBases.length;

        let totalDocs = 0;
        let totalChunks = 0;
        state.knowledgeBases.forEach(kb => {
            totalDocs += kb.document_count || 0;
            totalChunks += kb.chunk_count || 0;
        });

        document.getElementById('stat-doc-count').textContent = totalDocs;
        document.getElementById('stat-chunk-count').textContent = totalChunks;

        // 显示最近的知识库
        renderRecentKBs();
    } catch (error) {
        document.getElementById('stat-status').textContent = '离线';
        document.getElementById('stat-status').style.color = 'var(--danger)';
        showToast('无法连接到服务', 'error');
    }
}

function renderRecentKBs() {
    const container = document.getElementById('recent-kb-list');
    const recentKBs = state.knowledgeBases.slice(0, 5);

    if (recentKBs.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted" style="padding: 48px;">
                <i class="ri-inbox-line" style="font-size: 48px; display: block; margin-bottom: 16px;"></i>
                <p>暂无知识库</p>
                <button class="btn btn-primary mt-4" onclick="showCreateKBModal()">
                    <i class="ri-add-line"></i> 创建第一个知识库
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = recentKBs.map(kb => `
        <div class="kb-card" onclick="showKBDetail('${kb.name}')">
            <div class="kb-card-header">
                <div class="kb-card-title">${kb.name}</div>
                <div class="kb-card-badge">活跃</div>
            </div>
            <div class="kb-card-desc">${kb.description || '暂无描述'}</div>
            <div class="kb-card-stats">
                <div class="kb-stat">
                    <div class="kb-stat-value">${kb.document_count || 0}</div>
                    <div class="kb-stat-label">文档</div>
                </div>
                <div class="kb-stat">
                    <div class="kb-stat-value">${kb.chunk_count || 0}</div>
                    <div class="kb-stat-label">分块</div>
                </div>
                <div class="kb-stat">
                    <div class="kb-stat-value">${kb.embedding_model || '-'}</div>
                    <div class="kb-stat-label" style="font-size: 10px;">Embedding</div>
                </div>
            </div>
        </div>
    `).join('');
}

// ===========================================
// 知识库管理
// ===========================================

async function loadKnowledgeBases() {
    try {
        const kbs = await API.listKnowledgeBases();
        state.knowledgeBases = kbs.data || [];
        renderKBList();
    } catch (error) {
        showToast('加载知识库列表失败: ' + error.message, 'error');
    }
}

function renderKBList() {
    const container = document.getElementById('kb-list');

    if (state.knowledgeBases.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted" style="padding: 48px; grid-column: 1 / -1;">
                <i class="ri-database-2-line" style="font-size: 64px; display: block; margin-bottom: 16px;"></i>
                <p style="font-size: 18px; margin-bottom: 24px;">暂无知识库</p>
                <button class="btn btn-primary" onclick="showCreateKBModal()">
                    <i class="ri-add-line"></i> 创建知识库
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = state.knowledgeBases.map(kb => `
        <div class="kb-card" onclick="showKBDetail('${kb.name}')">
            <div class="kb-card-header">
                <div class="kb-card-title">${kb.name}</div>
                <div class="kb-card-badge">活跃</div>
            </div>
            <div class="kb-card-desc">${kb.description || '暂无描述'}</div>
            <div class="kb-card-stats">
                <div class="kb-stat">
                    <div class="kb-stat-value">${kb.document_count || 0}</div>
                    <div class="kb-stat-label">文档</div>
                </div>
                <div class="kb-stat">
                    <div class="kb-stat-value">${kb.chunk_count || 0}</div>
                    <div class="kb-stat-label">分块</div>
                </div>
                <div class="kb-stat">
                    <div class="kb-stat-value">${kb.embedding_model || '-'}</div>
                    <div class="kb-stat-label" style="font-size: 10px;">Embedding</div>
                </div>
            </div>
        </div>
    `).join('');
}

function showCreateKBModal() {
    document.getElementById('create-kb-modal').classList.add('active');
    document.getElementById('kb-name').value = '';
    document.getElementById('kb-description').value = '';
    document.getElementById('kb-name').focus();
}

function hideCreateKBModal() {
    document.getElementById('create-kb-modal').classList.remove('active');
}

async function createKB() {
    const name = document.getElementById('kb-name').value.trim();
    const description = document.getElementById('kb-description').value.trim();

    if (!name) {
        showToast('请输入知识库名称', 'warning');
        return;
    }

    if (!/^[a-zA-Z0-9_]+$/.test(name)) {
        showToast('名称只能包含英文字母、数字和下划线', 'warning');
        return;
    }

    try {
        await API.createKnowledgeBase(name, description);
        showToast(`知识库 "${name}" 创建成功`, 'success');
        hideCreateKBModal();
        loadKnowledgeBases();
    } catch (error) {
        showToast('创建失败: ' + error.message, 'error');
    }
}

async function showKBDetail(name) {
    try {
        const result = await API.getKnowledgeBase(name);
        const kb = result.data;

        state.selectedKB = name;

        document.getElementById('kb-detail-title').textContent = `知识库: ${name}`;
        document.getElementById('kb-detail-content').innerHTML = `
            <div class="kb-detail-info">
                <div class="kb-detail-item">
                    <div class="kb-detail-label">名称</div>
                    <div class="kb-detail-value">${kb.name}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">描述</div>
                    <div class="kb-detail-value">${kb.description || '暂无描述'}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">Embedding 模型</div>
                    <div class="kb-detail-value">${kb.embedding_model || '-'}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">向量维度</div>
                    <div class="kb-detail-value">${kb.embedding_dimension || '-'}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">文档数量</div>
                    <div class="kb-detail-value">${kb.document_count || 0}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">分块数量</div>
                    <div class="kb-detail-value">${kb.chunk_count || 0}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">创建时间</div>
                    <div class="kb-detail-value">${kb.created_at ? new Date(kb.created_at).toLocaleString() : '-'}</div>
                </div>
                <div class="kb-detail-item">
                    <div class="kb-detail-label">更新时间</div>
                    <div class="kb-detail-value">${kb.updated_at ? new Date(kb.updated_at).toLocaleString() : '-'}</div>
                </div>
            </div>
        `;

        document.getElementById('kb-detail-modal').classList.add('active');
    } catch (error) {
        showToast('获取详情失败: ' + error.message, 'error');
    }
}

function hideKBDetailModal() {
    document.getElementById('kb-detail-modal').classList.remove('active');
    state.selectedKB = null;
}

async function deleteKB() {
    if (!state.selectedKB) return;

    if (!confirm(`确定要删除知识库 "${state.selectedKB}" 吗？此操作不可恢复！`)) {
        return;
    }

    try {
        await API.deleteKnowledgeBase(state.selectedKB);
        showToast(`知识库 "${state.selectedKB}" 已删除`, 'success');
        hideKBDetailModal();
        loadKnowledgeBases();
    } catch (error) {
        showToast('删除失败: ' + error.message, 'error');
    }
}

// ===========================================
// 搜索测试
// ===========================================

async function loadKBSelects() {
    try {
        const kbs = await API.listKnowledgeBases();
        state.knowledgeBases = kbs.data || [];

        const options = '<option value="">选择知识库</option>' +
            state.knowledgeBases.map(kb => `<option value="${kb.name}">${kb.name}</option>`).join('');

        document.getElementById('search-kb-select').innerHTML = options;
        document.getElementById('upload-kb-select').innerHTML = options;
    } catch (error) {
        console.error('加载知识库列表失败:', error);
    }
}

async function performSearch() {
    const kbName = document.getElementById('search-kb-select').value;
    const query = document.getElementById('search-query').value.trim();
    const type = document.getElementById('search-type').value;

    if (!kbName) {
        showToast('请选择知识库', 'warning');
        return;
    }

    if (!query) {
        showToast('请输入搜索内容', 'warning');
        return;
    }

    const container = document.getElementById('search-results');
    container.innerHTML = `
        <div class="text-center" style="padding: 48px;">
            <i class="ri-loader-4-line progress-icon loading" style="font-size: 48px;"></i>
            <p class="mt-4">搜索中...</p>
        </div>
    `;

    try {
        const result = await API.search(kbName, query, 10, type);
        const results = result.data || [];

        if (results.length === 0) {
            container.innerHTML = `
                <div class="text-center text-muted" style="padding: 48px;">
                    <i class="ri-search-line" style="font-size: 48px; display: block; margin-bottom: 16px;"></i>
                    <p>未找到相关结果</p>
                </div>
            `;
            return;
        }

        container.innerHTML = results.map((item, index) => `
            <div class="search-result-item">
                <div class="search-result-header">
                    <div>
                        <span class="search-result-score">
                            <i class="ri-star-line"></i>
                            ${(item.score * 100).toFixed(1)}%
                        </span>
                        <span class="search-result-source">${item.source || 'vector'}</span>
                    </div>
                    <span class="text-muted">#${index + 1}</span>
                </div>
                <div class="search-result-text">${escapeHtml(item.text)}</div>
                <div class="search-result-meta">
                    ${item.metadata ? Object.entries(item.metadata).map(([k, v]) => `<span>${k}: ${v}</span>`).join('') : ''}
                </div>
            </div>
        `).join('');
    } catch (error) {
        container.innerHTML = `
            <div class="text-center" style="padding: 48px; color: var(--danger);">
                <i class="ri-error-warning-line" style="font-size: 48px; display: block; margin-bottom: 16px;"></i>
                <p>搜索失败: ${error.message}</p>
            </div>
        `;
    }
}

// ===========================================
// 文件上传
// ===========================================

function initUploadZone() {
    const dropZone = document.getElementById('file-drop-zone');
    const fileInput = document.getElementById('file-input');

    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
}

function handleFiles(fileList) {
    const files = Array.from(fileList);
    state.selectedFiles = [...state.selectedFiles, ...files];
    renderFileList();
    updateUploadButton();
}

function removeFile(index) {
    state.selectedFiles.splice(index, 1);
    renderFileList();
    updateUploadButton();
}

function renderFileList() {
    const container = document.getElementById('upload-file-list');

    if (state.selectedFiles.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = state.selectedFiles.map((file, index) => `
        <div class="file-item">
            <div class="file-item-info">
                <div class="file-item-icon">
                    <i class="ri-file-text-line"></i>
                </div>
                <div>
                    <div class="file-item-name">${file.name}</div>
                    <div class="file-item-size">${formatFileSize(file.size)}</div>
                </div>
            </div>
            <button class="file-item-remove" onclick="removeFile(${index})">
                <i class="ri-close-line"></i>
            </button>
        </div>
    `).join('');
}

function updateUploadButton() {
    const btn = document.getElementById('upload-btn');
    const kbSelect = document.getElementById('upload-kb-select');
    btn.disabled = state.selectedFiles.length === 0 || !kbSelect.value;
}

async function uploadFiles() {
    const kbName = document.getElementById('upload-kb-select').value;
    const extractEntities = document.getElementById('extract-entities').checked;

    if (!kbName) {
        showToast('请选择知识库', 'warning');
        return;
    }

    if (state.selectedFiles.length === 0) {
        showToast('请选择要上传的文件', 'warning');
        return;
    }

    const container = document.getElementById('upload-progress');
    container.innerHTML = '';

    let successCount = 0;
    let errorCount = 0;

    for (const file of state.selectedFiles) {
        const progressId = `progress-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

        container.innerHTML += `
            <div id="${progressId}" class="progress-item loading">
                <div class="progress-icon loading">
                    <i class="ri-loader-4-line"></i>
                </div>
                <div class="progress-info">
                    <div class="progress-name">${file.name}</div>
                    <div class="progress-status">上传中...</div>
                </div>
            </div>
        `;

        try {
            const result = await API.uploadFile(kbName, file, extractEntities);
            const progressEl = document.getElementById(progressId);

            if (result.success) {
                progressEl.className = 'progress-item success';
                progressEl.innerHTML = `
                    <div class="progress-icon success">
                        <i class="ri-check-line"></i>
                    </div>
                    <div class="progress-info">
                        <div class="progress-name">${file.name}</div>
                        <div class="progress-status success">${result.message || '上传成功'}</div>
                    </div>
                `;
                successCount++;
            } else {
                throw new Error(result.message);
            }
        } catch (error) {
            const progressEl = document.getElementById(progressId);
            progressEl.className = 'progress-item error';
            progressEl.innerHTML = `
                <div class="progress-icon error">
                    <i class="ri-close-line"></i>
                </div>
                <div class="progress-info">
                    <div class="progress-name">${file.name}</div>
                    <div class="progress-status error">${error.message}</div>
                </div>
            `;
            errorCount++;
        }
    }

    // 清空文件列表
    state.selectedFiles = [];
    renderFileList();
    updateUploadButton();

    // 显示结果
    if (errorCount === 0) {
        showToast(`成功上传 ${successCount} 个文件`, 'success');
    } else {
        showToast(`上传完成: ${successCount} 成功, ${errorCount} 失败`, 'warning');
    }
}

// ===========================================
// 工具函数
// ===========================================

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
        success: 'ri-check-line',
        error: 'ri-close-line',
        warning: 'ri-alert-line',
        info: 'ri-information-line'
    };

    toast.innerHTML = `
        <i class="${icons[type] || icons.info}"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ===========================================
// 配置管理
// ===========================================

// 提供商默认配置
const EMBEDDING_DEFAULTS = {
    openai: { url: 'https://api.openai.com/v1', model: 'text-embedding-3-small' },
    deepseek: { url: 'https://api.deepseek.com/v1', model: 'deepseek-embedding' },
    fastembed: { url: '', model: 'BAAI/bge-small-en-v1.5' },
};

const LLM_DEFAULTS = {
    deepseek: { url: 'https://api.deepseek.com/v1' },
    openai: { url: 'https://api.openai.com/v1' },
    mimo: { url: 'https://api.mimo.ai/v1' },
};

async function loadSettings() {
    try {
        const result = await API.getConfig();
        state.currentConfig = result.data;
        populateSettingsForm();
    } catch (error) {
        showToast('加载配置失败: ' + error.message, 'error');
    }
}

function populateSettingsForm() {
    const c = state.currentConfig;

    // Embedding
    document.getElementById('setting-embedding-provider').value = c.EMBEDDING_PROVIDER || 'openai';
    document.getElementById('setting-embedding-api-key').value = '';
    document.getElementById('setting-embedding-api-key').placeholder = c.EMBEDDING_API_KEY || 'sk-...';
    document.getElementById('setting-embedding-model').value = c.EMBEDDING_MODEL || '';
    document.getElementById('setting-embedding-base-url').value = c.EMBEDDING_BASE_URL || '';
    document.getElementById('setting-embedding-dimension').value = c.EMBEDDING_DIMENSION || '';

    // LLM
    document.getElementById('setting-extract-entities').value = c.KB_MCP_EXTRACT_ENTITIES || 'true';
    document.getElementById('setting-extract-llm').value = c.KB_MCP_EXTRACT_LLM || 'deepseek';
    document.getElementById('setting-llm-api-key').value = '';
    document.getElementById('setting-llm-api-key').placeholder = c.LLM_API_KEY || 'sk-...';
    document.getElementById('setting-llm-base-url').value = c.LLM_BASE_URL || '';

    // Qdrant
    document.getElementById('setting-qdrant-url').value = c.QDRANT_URL || 'http://localhost:6333';

    // Neo4j
    document.getElementById('setting-neo4j-uri').value = c.NEO4J_URI || 'bolt://localhost:7687';
    document.getElementById('setting-neo4j-user').value = c.NEO4J_USER || 'neo4j';
    document.getElementById('setting-neo4j-password').value = '';
    document.getElementById('setting-neo4j-password').placeholder = c.NEO4J_PASSWORD || '密码';

    // 根据提供商显示/隐藏字段
    onEmbeddingProviderChange();
    onLLMProviderChange();
}

function onEmbeddingProviderChange() {
    const provider = document.getElementById('setting-embedding-provider').value;
    const apiKeyGroup = document.getElementById('embedding-api-key-group');
    const baseUrlGroup = document.getElementById('embedding-base-url-group');

    if (provider === 'fastembed') {
        apiKeyGroup.style.display = 'none';
        baseUrlGroup.style.display = 'none';
    } else {
        apiKeyGroup.style.display = '';
        baseUrlGroup.style.display = '';
    }

    // 填充默认值
    const defaults = EMBEDDING_DEFAULTS[provider];
    if (defaults) {
        const modelInput = document.getElementById('setting-embedding-model');
        const urlInput = document.getElementById('setting-embedding-base-url');

        if (!modelInput.value) {
            modelInput.placeholder = defaults.model;
        }
        if (!urlInput.value) {
            urlInput.placeholder = defaults.url || '自动';
        }
    }
}

function onLLMProviderChange() {
    const provider = document.getElementById('setting-extract-llm').value;
    const defaults = LLM_DEFAULTS[provider];

    if (defaults) {
        const urlInput = document.getElementById('setting-llm-base-url');
        if (!urlInput.value) {
            urlInput.placeholder = defaults.url;
        }
    }
}

async function saveSettings() {
    try {
        const settings = {
            // Embedding
            EMBEDDING_PROVIDER: document.getElementById('setting-embedding-provider').value,
            EMBEDDING_API_KEY: document.getElementById('setting-embedding-api-key').value,
            EMBEDDING_MODEL: document.getElementById('setting-embedding-model').value,
            EMBEDDING_BASE_URL: document.getElementById('setting-embedding-base-url').value,
            EMBEDDING_DIMENSION: document.getElementById('setting-embedding-dimension').value,

            // LLM
            KB_MCP_EXTRACT_ENTITIES: document.getElementById('setting-extract-entities').value,
            KB_MCP_EXTRACT_LLM: document.getElementById('setting-extract-llm').value,
            LLM_API_KEY: document.getElementById('setting-llm-api-key').value,
            LLM_BASE_URL: document.getElementById('setting-llm-base-url').value,

            // Qdrant
            QDRANT_URL: document.getElementById('setting-qdrant-url').value,

            // Neo4j
            NEO4J_URI: document.getElementById('setting-neo4j-uri').value,
            NEO4J_USER: document.getElementById('setting-neo4j-user').value,
            NEO4J_PASSWORD: document.getElementById('setting-neo4j-password').value,
        };

        const result = await API.updateConfig(settings);

        if (result.success) {
            showToast(result.message || '配置已保存', 'success');
            loadSettings(); // 刷新显示
        } else {
            showToast('保存失败: ' + result.message, 'error');
        }
    } catch (error) {
        showToast('保存失败: ' + error.message, 'error');
    }
}

async function testConnection(service) {
    const btn = document.getElementById(`btn-test-${service}`);
    const resultEl = document.getElementById(`result-${service}`);
    const card = document.getElementById(`settings-${service}`);

    // 显示加载状态
    btn.disabled = true;
    btn.innerHTML = '<i class="ri-loader-4-line" style="animation: spin 1s linear infinite"></i> 测试中...';
    resultEl.className = 'test-result-inline';
    resultEl.style.display = 'none';
    card.classList.remove('test-success', 'test-error');

    try {
        const result = await API.testConnection(service);

        if (result.success) {
            btn.className = 'btn btn-test success';
            btn.innerHTML = '<i class="ri-check-line"></i> 连接成功';
            resultEl.className = 'test-result-inline show success';
            resultEl.innerHTML = `<i class="ri-check-line"></i> ${result.message}`;
            card.classList.add('test-success');
        } else {
            btn.className = 'btn btn-test error';
            btn.innerHTML = '<i class="ri-close-line"></i> 连接失败';
            resultEl.className = 'test-result-inline show error';
            resultEl.innerHTML = `<i class="ri-error-warning-line"></i> ${result.message}`;
            card.classList.add('test-error');
        }
    } catch (error) {
        btn.className = 'btn btn-test error';
        btn.innerHTML = '<i class="ri-close-line"></i> 连接失败';
        resultEl.className = 'test-result-inline show error';
        resultEl.innerHTML = `<i class="ri-error-warning-line"></i> 测试失败: ${error.message}`;
        card.classList.add('test-error');
    }

    btn.disabled = false;

    // 3秒后恢复按钮样式
    setTimeout(() => {
        btn.className = 'btn btn-outline btn-test';
        btn.innerHTML = '<i class="ri-link"></i> 测试连接';
    }, 3000);
}

// ===========================================
// 初始化
// ===========================================

document.addEventListener('DOMContentLoaded', () => {
    // 初始化导航
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(item.dataset.page);
        });
    });

    // 初始化上传区域
    initUploadZone();

    // 监听知识库选择变化
    document.getElementById('upload-kb-select').addEventListener('change', updateUploadButton);

    // 监听回车搜索
    document.getElementById('search-query').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            performSearch();
        }
    });

    // 加载仪表盘
    navigateTo('dashboard');
});
