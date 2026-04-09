const API = '/api';

// ── 페이지 전환 ──────────────────────────────────────────────
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('page-' + btn.dataset.page).classList.add('active');

        if (btn.dataset.page === 'documents') loadDocuments();
        if (btn.dataset.page === 'settings') loadSettings();
        if (btn.dataset.page === 'category') loadCategories();
        if (btn.dataset.page === 'graph') loadGraph();
    });
});

// ══════════════════════════════════════════════════════════════
// ── 영향도 검토 ─────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════

function _mdToHtml(text) {
    if (!text) return '';
    return text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n- /g, '\n• ')
        .replace(/\n/g, '<br>')
        .replace(/\|(.+)\|/g, function(match) {
            return '<div style="overflow-x:auto;font-size:12px;">' + match + '</div>';
        });
}

document.getElementById('btn-review-start').addEventListener('click', startReview);
document.getElementById('review-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); startReview(); }
});

let _reviewAbort = null;

document.getElementById('btn-review-stop').addEventListener('click', () => {
    if (_reviewAbort) _reviewAbort.abort();
});

async function startReview() {
    const input = document.getElementById('review-input').value.trim();
    if (!input) return;

    const resultDiv = document.getElementById('review-result');
    const loadingDiv = document.getElementById('review-loading');
    const guideContent = document.getElementById('review-guide-content');
    const similarList = document.getElementById('review-similar-list');

    const startBtn = document.getElementById('btn-review-start');
    const stopBtn = document.getElementById('btn-review-stop');
    resultDiv.style.display = 'none';
    startBtn.style.display = 'none';
    stopBtn.style.display = '';
    loadingDiv.style.display = 'flex';

    _reviewAbort = new AbortController();

    try {
        const res = await fetch(API + '/review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ requirement: input }),
            signal: _reviewAbort.signal,
        });
        const data = await res.json();
        loadingDiv.style.display = 'none';
        startBtn.style.display = '';
        stopBtn.style.display = 'none';

        if (res.status === 499) {
            guideContent.innerHTML = '<div style="color:var(--text-muted)">요청이 취소되었습니다.</div>';
            resultDiv.style.display = 'block';
            return;
        }

        // 검토 가이드 렌더링
        if (data.findings && data.findings.length > 0) {
            const visibleFindings = data.findings.filter(f => !f.title.includes('참조') || !f.title.includes('DR'));
            let num = 0;
            guideContent.innerHTML = visibleFindings.map((f) => {
                const titleText = f.title.replace(/\s*\(핵심\)\s*/g, '');
                const isFinal = titleText.includes('최종') || titleText.includes('결론');
                const titleClass = isFinal ? 'review-finding-title main-title' : 'review-finding-title';
                const cardStyle = isFinal ? ' style="border-left:3px solid #ef4444;"' : '';
                num++;
                return `<div class="review-finding"${cardStyle}>
                    <div class="${titleClass}">${num}. ${titleText}</div>
                    <div class="review-finding-content">${_mdToHtml(f.content)}</div>
                </div>`;
            }).join('');
        } else if (data.review_text) {
            guideContent.innerHTML = `<div class="review-finding"><div class="review-finding-content">${_mdToHtml(data.review_text)}</div></div>`;
        } else {
            guideContent.innerHTML = '<div style="color:var(--text-muted)">검토 가이드를 생성하지 못했습니다.</div>';
        }

        // 경고
        if (data.warnings && data.warnings.length > 0) {
            guideContent.innerHTML += `<div class="review-finding" style="border-left:3px solid #f59e0b;margin-top:12px;">
                <div class="review-finding-title main-title">📋 최종 요약</div>
                <div class="review-finding-content">${data.warnings.map(w => '- ' + w).join('<br>')}</div>
            </div>`;
        }

        // 유사 SR 렌더링
        if (data.similar_drs && data.similar_drs.length > 0) {
            similarList.innerHTML = data.similar_drs.map(dr =>
                `<div class="review-sr-card">
                    <div class="review-sr-line"><span class="review-sr-label">SR ID</span><span class="review-sr-value">${dr.dr_number}</span></div>
                    <div class="review-sr-line"><span class="review-sr-label">SR 명</span><span class="review-sr-value">${dr.title || ''}</span></div>
                    <div class="review-sr-line"><span class="review-sr-label">관련업무</span><span class="review-sr-value">${(dr.categories || []).join(', ') || '-'}</span></div>
                    <div class="review-sr-btns">
                        <button class="sr-btn sr-btn-view" onclick="_showSrSummary('${dr.dr_number}')">요약보기</button>
                        <button class="sr-btn sr-btn-download" onclick="_downloadSrWord('${dr.dr_number}', '${(dr.title || '').replace(/'/g, "\\'")}')">다운로드</button>
                        <button class="sr-btn sr-btn-graph" onclick="_goToGraph('${dr.dr_number}')">시각화</button>
                    </div>
                </div>`
            ).join('');
        } else {
            similarList.innerHTML = '<div style="color:var(--text-muted)">유사 SR을 찾지 못했습니다.</div>';
        }

        resultDiv.style.display = 'block';
    } catch (e) {
        loadingDiv.style.display = 'none';
        startBtn.style.display = '';
        stopBtn.style.display = 'none';
        if (e.name === 'AbortError') {
            // 사용자가 중지한 경우
        } else {
            guideContent.innerHTML = `<div style="color:var(--danger)">오류: ${e.message}</div>`;
            resultDiv.style.display = 'block';
        }
    } finally {
        _reviewAbort = null;
    }
}

// 유사 SR 상세보기
window._showReviewDrDetail = async function(drNumber) {
    try {
        const res = await fetch(API + '/documents/' + drNumber);
        const data = await res.json();
        const doc = data.document || {};
        const sections = data.sections || [];

        let html = `<h3>${drNumber} ${doc.title || ''}</h3>`;
        html += `<p style="color:var(--text-muted);font-size:13px;">${doc.system || ''} | ${doc.target_year_month || ''}</p>`;
        for (const sec of sections) {
            const sm = sec.summary || '';
            if (!sm) continue;
            html += `<div style="margin:12px 0;padding:10px;background:var(--bg-elevated);border-radius:8px;">
                <div style="font-size:12px;font-weight:600;color:var(--primary);margin-bottom:6px;">${sec.heading_path || ''}</div>
                <div style="font-size:13px;color:var(--text-secondary);white-space:pre-wrap;">${sm}</div>
            </div>`;
        }

        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `<div style="background:var(--bg-surface);border-radius:12px;padding:24px;max-width:700px;max-height:80vh;overflow-y:auto;width:90%;border:1px solid var(--border);">
            ${html}
            <div style="text-align:right;margin-top:16px;"><button onclick="this.closest('div[style*=fixed]').remove()" style="padding:8px 20px;background:var(--primary-deep);color:#fff;border:none;border-radius:8px;cursor:pointer;">닫기</button></div>
        </div>`;
        document.body.appendChild(modal);
    } catch (e) {
        alert('조회 실패: ' + e.message);
    }
};

// ── SR 시각화 팝업 ──
window._goToGraph = async function(drNumber) {
    try {
        // 문서 조회
        const res = await fetch(API + '/documents/' + drNumber);
        const data = await res.json();
        const doc = data.document || {};

        // 카테고리 조회 + 중복 제거
        const catRes = await fetch(API + '/documents/' + drNumber + '/categories');
        const catData = await catRes.json();
        const allCats = catData.categories || [];
        const uniqueCatIds = [...new Set(allCats.map(c => c.category_id))];

        // 카테고리 트리 로드
        if (!_exploreCats || _exploreCats.length === 0) {
            try {
                const treeRes = await fetch(API + '/categories');
                const treeData = await treeRes.json();
                _exploreCats = treeData.categories || [];
            } catch(e) {}
        }

        // 카테고리 이름
        function _name(cid) { const n = _findNode(_exploreCats, cid); return n ? n.name : cid; }
        const catLabels = uniqueCatIds.map(c => _name(c)).join(', ');

        // 팝업
        const modal = document.createElement('div');
        modal.className = 'sr-popup-overlay';
        modal.onclick = function(e) { if (e.target === modal) modal.remove(); };

        const popupW = 700, popupH = 500;
        modal.innerHTML = `
            <div class="sr-popup-content" style="max-width:${popupW}px;max-height:${popupH + 80}px;padding:0;overflow:hidden;display:flex;flex-direction:column;">
                <div class="sr-popup-sticky-header" style="padding:20px 24px 12px;">
                    <button class="sr-popup-x" onclick="this.closest('.sr-popup-overlay').remove()">✕</button>
                    <div class="sr-popup-title">${drNumber}</div>
                    <div class="sr-popup-subtitle">${doc.title || ''}</div>
                    <div style="font-size:13px;color:var(--text-muted);margin-top:4px;">카테고리: ${catLabels || '<span style="color:var(--danger)">미등록 상태입니다</span>'}</div>
                </div>
                <div id="graph-popup-container" style="flex:1;min-height:0;"></div>
            </div>`;
        document.body.appendChild(modal);

        const container = document.getElementById('graph-popup-container');

        if (uniqueCatIds.length === 0) {
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:16px;">카테고리가 미등록 상태입니다.</div>';
            return;
        }

        // _searchDR과 동일한 트리 구성 로직
        const rect = container.getBoundingClientRect();
        const w = rect.width || popupW, h = rect.height || (popupH - 80);
        const graphNodes = [];
        const graphLinks = [];
        const seen = new Set();

        // DR 노드
        const docId = 'doc_' + drNumber;
        graphNodes.push({ id: docId, type: 'document', dr_number: drNumber, name: drNumber, fullTitle: doc.title || '' });
        seen.add(docId);

        // 카테고리 체인 노드
        for (const catId of uniqueCatIds) {
            const parts = catId.split('.');
            let prevId = null;
            for (let i = 1; i <= parts.length; i++) {
                const cid = parts.slice(0, i).join('.');
                if (!seen.has(cid)) {
                    seen.add(cid);
                    const catNode = _findNode(_exploreCats, cid);
                    graphNodes.push({ id: cid, name: catNode ? catNode.name : cid, type: 'category', level: i - 1 });
                }
                if (prevId) {
                    const lk = prevId + '->' + cid;
                    if (!seen.has(lk)) { seen.add(lk); graphLinks.push({ source: prevId, target: cid }); }
                }
                prevId = cid;
            }
            const lk = catId + '->' + docId;
            if (!seen.has(lk)) { seen.add(lk); graphLinks.push({ source: catId, target: docId }); }
        }

        // D3 트리형 그래프 (시각화 메뉴와 동일)
        const svg = d3.select(container).append('svg').attr('width', w).attr('height', h);
        const g = svg.append('g');
        svg.call(d3.zoom().scaleExtent([0.5, 3]).on('zoom', e => g.attr('transform', e.transform)));

        function _fill(d) {
            if (d.type === 'document') return '#a78bfa';
            return _LEVEL_COLORS[d.level] || '#93c5fd';
        }
        function _r(d) { return d.type === 'document' ? 16 : d.level === 0 ? 24 : d.level === 1 ? 20 : 16; }

        // 레벨별 트리 배치
        const maxLevel = Math.max(...graphNodes.filter(n => n.type === 'category').map(n => n.level), 0);
        const totalRows = maxLevel + 2;
        const rowH = h / (totalRows + 1);

        const nodesByLevel = {};
        for (const n of graphNodes) {
            const row = n.type === 'document' ? maxLevel + 1 : n.level;
            if (!nodesByLevel[row]) nodesByLevel[row] = [];
            nodesByLevel[row].push(n);
        }
        for (const [row, nodes] of Object.entries(nodesByLevel)) {
            const r = parseInt(row);
            const count = nodes.length;
            const spacing = Math.min(180, (w - 80) / (count + 1));
            const startX = (w - spacing * (count - 1)) / 2;
            nodes.forEach((n, i) => {
                n.fx = count === 1 ? w / 2 : startX + spacing * i;
                n.fy = rowH * (r + 1);
            });
        }

        const link = g.append('g').selectAll('line').data(graphLinks).join('line')
            .attr('stroke', '#94a3b8').attr('stroke-width', 2).attr('stroke-opacity', 0.5);
        const node = g.append('g').selectAll('g').data(graphNodes).join('g');
        node.append('circle').attr('r', _r).attr('fill', _fill)
            .attr('stroke', d => d.type === 'document' ? 'rgba(167,139,250,0.3)' : 'none')
            .attr('stroke-width', d => d.type === 'document' ? 2 : 0);
        node.each(function(d) {
            const el = d3.select(this);
            if (d.type === 'document') {
                el.append('text').text(d.name).attr('dy', -(_r(d) + 14)).attr('text-anchor', 'middle')
                    .attr('fill', '#6366f1').attr('font-size', '13px').attr('font-weight', '700');
                el.append('text').text(d.fullTitle || '').attr('dy', -(_r(d) + 2)).attr('text-anchor', 'middle')
                    .attr('fill', '#475569').attr('font-size', '11px');
            } else {
                el.append('text').text(d.name).attr('dy', -(_r(d) + 6)).attr('text-anchor', 'middle')
                    .attr('fill', '#1e293b').attr('font-size', '12px').attr('font-weight', '600');
            }
        });

        const sim = d3.forceSimulation(graphNodes)
            .force('link', d3.forceLink(graphLinks).id(d => d.id).distance(rowH * 0.8).strength(1))
            .force('collide', d3.forceCollide().radius(d => _r(d) + 20))
            .on('tick', () => {
                link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                    .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
                node.attr('transform', d => `translate(${d.x},${d.y})`);
            });
    } catch (e) {
        alert('시각화 조회 실패: ' + e.message);
    }
};

// ── SR 요약보기 팝업 ──
window._showSrSummary = async function(drNumber) {
    try {
        const res = await fetch(API + '/documents/' + drNumber);
        const data = await res.json();
        const doc = data.document || {};
        const sections = data.sections || [];

        let headerHtml = `<div class="sr-popup-sticky-header">`;
        headerHtml += `<div class="sr-popup-title">${drNumber}</div>`;
        headerHtml += `<div class="sr-popup-subtitle">${doc.title || ''}</div>`;
        headerHtml += `<div class="sr-popup-meta">${doc.system || ''} | ${doc.target_year_month || ''}</div>`;
        headerHtml += `</div>`;

        let bodyHtml = `<div class="sr-popup-body">`;
        // 통합 요약 표시
        const docSummary = doc.document_summary || '';
        if (docSummary.trim()) {
            bodyHtml += `<div class="sr-popup-section">`;
            bodyHtml += `<div class="sr-popup-section-body">${docSummary.replace(/\n/g, '<br>')}</div>`;
            bodyHtml += `</div>`;
        } else {
            bodyHtml += `<div style="color:var(--text-muted);padding:12px 0;">통합 요약이 없습니다. 문서를 재적재하면 생성됩니다.</div>`;
        }
        bodyHtml += `</div>`;

        const modal = document.createElement('div');
        modal.className = 'sr-popup-overlay';
        modal.onclick = function(e) { if (e.target === modal) modal.remove(); };
        modal.innerHTML = `<div class="sr-popup-content"><button class="sr-popup-x" onclick="this.closest('.sr-popup-overlay').remove()">✕</button>${headerHtml}${bodyHtml}</div>`;
        document.body.appendChild(modal);
    } catch (e) {
        alert('조회 실패: ' + e.message);
    }
};

// ── SR Word 다운로드 ──
window._downloadSrWord = async function(drNumber, title) {
    try {
        const res = await fetch(API + '/documents/' + drNumber);
        const data = await res.json();
        const doc = data.document || {};
        const sections = data.sections || [];

        // HTML → Word 변환 (통합 요약 + 꼭지별 상세)
        const topicCfg = {
            '개발 목적': { type: '과제분석', mode: 'summary' },
            '주요 개발': { type: '과제분석', mode: 'summary' },
            '변경 테이블': { type: 'DB참조', mode: 'content' },
            '변경 소스': { type: '구현방안', mode: 'summary' },
            '검증': { type: '검증방안', mode: 'summary' },
            '이슈': { type: '이슈사항', mode: 'summary' },
            '유의': { type: '이슈사항', mode: 'summary' },
        };

        let html = '<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8"><style>body{font-family:맑은 고딕,sans-serif;font-size:11pt;line-height:1.8;}h1{font-size:16pt;color:#1a56db;}h2{font-size:13pt;color:#1a56db;border-bottom:1px solid #ddd;padding-bottom:6px;margin-top:24px;}h3{font-size:11pt;color:var(--text-muted);margin-top:14px;}p{margin:6px 0;}.meta{color:var(--text-muted);font-size:10pt;margin-bottom:16px;}.detail{background:#f8f9fa;border:1px solid #e5e7eb;border-radius:4px;padding:10px;margin:8px 0;font-size:10pt;}</style></head><body>';
        html += '<h1>' + drNumber + ' ' + (doc.title || '') + '</h1>';
        html += '<p class="meta">' + (doc.system || '') + ' | ' + (doc.target_year_month || '') + ' | AI 요약</p>';

        // 통합 요약 꼭지별
        const docSummary = doc.document_summary || '';
        if (docSummary) {
            const blocks = docSummary.split(/(?=📌|🎯)/).filter(b => b.trim());
            blocks.forEach(block => {
                const lines = block.trim().split('\n');
                const heading = lines[0];
                const body = lines.slice(1).join('\n').trim();
                html += '<h2>' + heading + '</h2>';
                if (body) html += '<p>' + body.replace(/\n/g, '<br>') + '</p>';

                // 꼭지별 상세 추가
                for (const [kw, cfg] of Object.entries(topicCfg)) {
                    if (heading.includes(kw)) {
                        const matched = sections.filter(s => s.section_type === cfg.type);
                        const field = cfg.mode === 'content' ? 'detail' : 'summary';
                        matched.forEach(s => {
                            const val = (cfg.mode === 'content' ? (s.detail || s.content || '') : (s.summary || '')).trim();
                            if (!val) return;
                            html += '<h3>[상세] ' + (s.heading_path || '') + '</h3>';
                            html += '<div class="detail">' + val.replace(/\n/g, '<br>') + '</div>';
                        });
                        break;
                    }
                }
            });
        }
        html += '</body></html>';

        const blob = new Blob(['\ufeff' + html], { type: 'application/msword;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const safeTitle = (title || '').replace(/[\\/:*?"<>|]/g, '_');
        a.href = url;
        a.download = drNumber + '_' + safeTitle + '_AI요약.doc';
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('다운로드 실패: ' + e.message);
    }
};

// ── SR 전체 요약 팝업 (시각화용) ──
window._showSrFullSummary = async function(drNumber) {
    try {
        const res = await fetch(API + '/documents/' + drNumber);
        const data = await res.json();
        const doc = data.document || {};
        const sections = data.sections || [];

        let html = `<div class="sr-popup-title">${drNumber}</div>`;
        html += `<div class="sr-popup-subtitle">${doc.title || ''}</div>`;
        html += `<div class="sr-popup-meta">${doc.system || ''} | ${doc.target_year_month || ''}</div>`;

        // 통합 요약이 있으면 상단에 표시
        if (doc.document_summary && doc.document_summary.trim()) {
            html += `<div class="sr-popup-section">`;
            html += `<div class="sr-popup-section-title" style="font-size:16px;">📋 통합 요약</div>`;
            html += `<div class="sr-popup-section-body">${doc.document_summary.replace(/\n/g, '<br>')}</div>`;
            html += `</div>`;
        }

        const modal = document.createElement('div');
        modal.className = 'sr-popup-overlay';
        modal.onclick = function(e) { if (e.target === modal) modal.remove(); };
        modal.innerHTML = `<div class="sr-popup-content"><button class="sr-popup-x" onclick="this.closest('.sr-popup-overlay').remove()">✕</button>${html}</div>`;
        document.body.appendChild(modal);
    } catch (e) {
        alert('조회 실패: ' + e.message);
    }
};

// ── 플로팅 챗봇 팝업 ──
window._toggleChatPopup = function() {
    const popup = document.getElementById('chat-popup');
    if (popup.style.display === 'none') {
        popup.style.display = 'flex';
        popup.classList.remove('fullscreen');
        document.getElementById('popup-chat-input').focus();
    } else {
        popup.style.display = 'none';
    }
};

window._toggleChatFullscreen = function() {
    const popup = document.getElementById('chat-popup');
    popup.classList.toggle('fullscreen');
    const btn = document.getElementById('chat-fullscreen-btn');
    btn.textContent = popup.classList.contains('fullscreen') ? '⊟' : '⛶';
};

// 드래그 이동
(function() {
    const header = document.getElementById('chat-popup-header');
    const popup = document.getElementById('chat-popup');
    let isDragging = false, startX, startY, startLeft, startTop;

    header.addEventListener('mousedown', function(e) {
        if (e.target.tagName === 'BUTTON' || popup.classList.contains('fullscreen')) return;
        isDragging = true;
        const rect = popup.getBoundingClientRect();
        startX = e.clientX;
        startY = e.clientY;
        startLeft = rect.left;
        startTop = rect.top;
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        popup.style.left = (startLeft + e.clientX - startX) + 'px';
        popup.style.top = (startTop + e.clientY - startY) + 'px';
        popup.style.right = 'auto';
    });

    document.addEventListener('mouseup', function() {
        isDragging = false;
        document.body.style.userSelect = '';
    });
})();

// 8방향 리사이즈
(function() {
    const popup = document.getElementById('chat-popup');
    const edges = ['n','s','w','e','nw','ne','sw','se'];
    edges.forEach(dir => {
        const el = document.createElement('div');
        el.className = 'chat-popup-edge edge-' + dir;
        popup.appendChild(el);
    });

    let active = null, startX, startY, startW, startH, startTop, startLeft;

    popup.addEventListener('mousedown', function(e) {
        const el = e.target;
        if (!el.classList.contains('chat-popup-edge')) return;
        if (popup.classList.contains('fullscreen')) return;
        const dir = edges.find(d => el.classList.contains('edge-' + d));
        if (!dir) return;
        active = dir;
        startX = e.clientX;
        startY = e.clientY;
        const rect = popup.getBoundingClientRect();
        startW = rect.width;
        startH = rect.height;
        startTop = rect.top;
        startLeft = rect.left;
        document.body.style.userSelect = 'none';
        e.stopPropagation();
        e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
        if (!active) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        const minW = 350, minH = 300;

        // 오른쪽 변
        if (active.includes('e')) {
            popup.style.width = Math.max(minW, startW + dx) + 'px';
        }
        // 왼쪽 변
        if (active.includes('w')) {
            const newW = Math.max(minW, startW - dx);
            popup.style.width = newW + 'px';
            popup.style.left = (startLeft + startW - newW) + 'px';
            popup.style.right = 'auto';
        }
        // 아래 변
        if (active.includes('s')) {
            popup.style.height = Math.max(minH, startH + dy) + 'px';
        }
        // 위 변
        if (active.includes('n')) {
            const newH = Math.max(minH, startH - dy);
            popup.style.height = newH + 'px';
            popup.style.top = (startTop + startH - newH) + 'px';
        }
    });

    document.addEventListener('mouseup', function() {
        if (active) {
            active = null;
            document.body.style.userSelect = '';
        }
    });
})();

function _popupMdToHtml(text) {
    if (!text) return '';
    return text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/^### (.+)$/gm, '<div style="font-size:15px;font-weight:700;color:var(--primary);margin:12px 0 6px;">$1</div>')
        .replace(/^## (.+)$/gm, '<div style="font-size:16px;font-weight:700;color:var(--primary);margin:14px 0 6px;">$1</div>')
        .replace(/^📎 (.+)$/gm, '<div style="font-size:14px;font-weight:700;color:var(--primary);margin:12px 0 4px;">📎 $1</div>')
        .replace(/\n- /g, '\n• ')
        .replace(/\n/g, '<br>');
}

function _addPopupMsg(text, type) {
    const container = document.getElementById('popup-chat-messages');
    const div = document.createElement('div');
    div.className = 'pmsg pmsg-' + type;
    if (type === 'bot') {
        div.innerHTML = _popupMdToHtml(text);
    } else {
        div.textContent = text;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

document.getElementById('popup-chat-send').addEventListener('click', _sendPopupChat);
document.getElementById('popup-chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _sendPopupChat(); }
});
document.getElementById('popup-chat-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 100) + 'px';
});

async function _sendPopupChat() {
    const input = document.getElementById('popup-chat-input');
    const question = input.value.trim();
    if (!question) return;
    const dbMode = document.getElementById('popup-db-check').checked;

    _addPopupMsg(question, 'user');
    input.value = '';
    input.style.height = 'auto';
    const loading = _addPopupMsg(dbMode ? 'DB 분석 중...' : '답변 생성 중...', 'loading');

    try {
        let data;
        if (dbMode) {
            const res = await fetch(API + '/db/lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: question }),
            });
            data = await res.json();
            loading.remove();
            _addPopupMsg(data.answer || data.error || '결과 없음', 'bot');
        } else {
            const res = await fetch(API + '/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question, top_k: 10,
                    session_id: _sessionId,
                    chat_history: _chatHistory,
                }),
            });
            data = await res.json();
            loading.remove();
            _addPopupMsg(data.answer || '답변을 생성하지 못했습니다.', 'bot');
            // 대화이력 누적
            _chatHistory.push({role: 'user', content: question});
            _chatHistory.push({role: 'assistant', content: data.answer || ''});
            if (data.session_id) _sessionId = data.session_id;
            if (data.context_type === 'new') {
                _chatHistory = [
                    {role: 'user', content: question},
                    {role: 'assistant', content: data.answer || ''},
                ];
            }
            _prevQuestion = question;
            _prevAnswer = data.answer || '';
            _prevDrNumbers = (data.sources || []).map(s => s.dr_number).filter(Boolean);
        }
    } catch (e) {
        loading.remove();
        _addPopupMsg('오류: 서버에 연결할 수 없습니다.', 'bot');
    }
}

// ── 통계 로드 ────────────────────────────────────────────────
async function loadStats() {
    try {
        const res = await fetch(API + '/health');
        const data = await res.json();
        const s = data.stats;
        document.getElementById('stats').innerHTML =
            `📊 문서: ${s.documents}건<br>📝 섹션: ${s.sections}건<br>🔢 벡터: ${s.vectors}건`;
    } catch (e) {
        document.getElementById('stats').textContent = '서버 연결 안됨';
    }
}
loadStats();

// ── 채팅 ──────────────────────────────────────────────────────
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');
const chatStop = document.getElementById('chat-stop');
const dbLookupCheck = document.getElementById('db-lookup-check');
let _currentRequestId = null;
let _chatHistory = [];   // [{role: "user"|"assistant", content: "..."}]
let _sessionId = '';      // 서버 세션 ID
// 하위호환용 (팝업 채팅에서 사용)
let _prevQuestion = '';
let _prevAnswer = '';
let _prevDrNumbers = [];
chatInput.value = '';

function addMessage(content, type, sources = null, dbResults = null, questionType = '') {
    const div = document.createElement('div');
    div.className = 'message ' + type;
    div.textContent = content;

    if (sources && sources.length > 0) {
        // sr_search / dr_detail: 소스 표시 안 함 (답변 본문에 이미 포함)
        // business: DR번호만 표시
        if (questionType === 'business') {
            const srcDiv = document.createElement('div');
            srcDiv.className = 'sources';
            const drNums = sources.map(s => s.dr_number).filter(Boolean);
            srcDiv.innerHTML = '📎 참조 SR: ' + drNums.join(', ');
            div.appendChild(srcDiv);
        }

        // 피드백 버튼 (모든 유형에 표시)
        const fbDiv = document.createElement('div');
        fbDiv.className = 'feedback-btns';
        fbDiv.innerHTML = '<button onclick="sendFeedback(this,\'positive\')">👍 정확함</button><button onclick="sendFeedback(this,\'negative\')">👎 부정확</button>';
        fbDiv.dataset.question = chatInput.value;
        fbDiv.dataset.sources = JSON.stringify(sources);
        div.appendChild(fbDiv);
    }

    // DB 조회 결과 표시
    if (dbResults && dbResults.length > 0) {
        const dbDiv = document.createElement('div');
        dbDiv.className = 'db-results-container';
        dbDiv.innerHTML = renderDBResults(dbResults);
        div.appendChild(dbDiv);
    }

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function renderDBResults(dbResults) {
    return dbResults.map(r => {
        const schema = r.schema;
        const cols = schema.columns || [];
        const pks = new Set(schema.primary_keys || []);

        // 스키마 테이블
        let html = `<div class="db-result-block">`;
        html += `<div class="db-result-header">🗄️ ${r.table_name} <span style="font-weight:400;color:var(--text-muted)">(${cols.length}개 컬럼)</span></div>`;
        html += `<table class="db-result-table"><thead><tr><th>컬럼명</th><th>타입</th><th>Nullable</th></tr></thead><tbody>`;
        for (const c of cols) {
            const pkBadge = pks.has(c.column_name) ? '<span class="pk-badge">PK</span>' : '';
            html += `<tr><td>${c.column_name}${pkBadge}</td><td>${c.data_type}</td><td>${c.is_nullable}</td></tr>`;
        }
        html += `</tbody></table>`;

        // 샘플 데이터
        if (r.sample_data && r.sample_data.success && r.sample_data.rows && r.sample_data.rows.length > 0) {
            const rows = r.sample_data.rows;
            const keys = Object.keys(rows[0]);
            html += `<div style="margin-top:12px;font-size:12px;color:var(--text-muted);font-weight:600;">📊 샘플 데이터 (${rows.length}행)</div>`;
            html += `<div style="overflow-x:auto;margin-top:6px;"><table class="db-result-table"><thead><tr>`;
            for (const k of keys) html += `<th>${k}</th>`;
            html += `</tr></thead><tbody>`;
            for (const row of rows) {
                html += '<tr>';
                for (const k of keys) {
                    const val = row[k] === null ? '<i style="color:var(--text-muted)">NULL</i>' : String(row[k]).substring(0, 50);
                    html += `<td>${val}</td>`;
                }
                html += '</tr>';
            }
            html += `</tbody></table></div>`;
        }

        html += `</div>`;
        return html;
    }).join('');
}

function _showStopBtn(show) {
    chatStop.style.display = show ? 'inline-block' : 'none';
    chatSend.style.display = show ? 'none' : 'inline-block';
}

async function cancelCurrentRequest() {
    if (!_currentRequestId) return;
    try {
        await fetch(API + '/ask/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: _currentRequestId }),
        });
    } catch (e) { /* ignore */ }
}

chatStop.addEventListener('click', cancelCurrentRequest);

async function sendQuestion() {
    const question = chatInput.value.trim();
    if (!question) return;

    const dbLookup = dbLookupCheck.checked;

    addMessage(question, 'user');
    chatInput.value = '';
    chatInput.style.height = 'auto';
    chatSend.disabled = true;

    if (dbLookup) {
        // ── DB 전용 모드: 벡터검색 없이 순수 DB 조회 ──
        _showStopBtn(false);
        const loadingMsg = addMessage('🤖 AI가 DB를 분석하고 있습니다...', 'loading');
        try {
            const res = await fetch(API + '/db/lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: question }),
            });
            const data = await res.json();
            loadingMsg.remove();
            renderDBResponse(data);
        } catch (e) {
            loadingMsg.remove();
            addMessage('❌ DB 연결 오류: ' + e.message, 'system');
        }
    } else {
        // ── 일반 IA 모드: 벡터검색 + LLM 답변 ──
        _currentRequestId = crypto.randomUUID().replace(/-/g, '').substring(0, 8);
        _showStopBtn(true);
        const loadingMsg = addMessage('답변 생성 중...', 'loading');
        try {
            const res = await fetch(API + '/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    question, top_k: 10, request_id: _currentRequestId,
                    session_id: _sessionId,
                    chat_history: _chatHistory,
                }),
            });
            const data = await res.json();
            loadingMsg.remove();
            if (res.status === 499) {
                addMessage('요청이 중지되었습니다.', 'system');
            } else if (data.context_type === 'unsure') {
                // 사용자에게 선택 요청
                _showStopBtn(false);
                _showContextChoice(question);
            } else {
                addMessage(data.answer, 'bot', data.sources, null, data.question_type);
                // 대화이력 누적
                _chatHistory.push({role: 'user', content: question});
                _chatHistory.push({role: 'assistant', content: data.answer || ''});
                // 세션 ID 갱신 (신규검색 시 서버에서 발급)
                if (data.session_id) _sessionId = data.session_id;
                // 신규검색이면 이전 이력 리셋 (새 주제)
                if (data.context_type === 'new') {
                    _chatHistory = [
                        {role: 'user', content: question},
                        {role: 'assistant', content: data.answer || ''},
                    ];
                }
                // 하위호환용
                _prevQuestion = question;
                _prevAnswer = data.answer || '';
                _prevDrNumbers = (data.sources || []).map(s => s.dr_number).filter(Boolean);
            }
        } catch (e) {
            loadingMsg.remove();
            addMessage('오류: 서버에 연결할 수 없습니다.', 'system');
        }
        _currentRequestId = null;
        _showStopBtn(false);
    }

    chatSend.disabled = false;
    chatInput.focus();
    loadStats();
}

let _unsureQuestion = '';

function _showContextChoice(question) {
    _unsureQuestion = question;
    const div = document.createElement('div');
    div.className = 'message system context-choice';
    div.innerHTML = `
        <div class="ctx-choice-text">이전 대화와 연관된 질문인가요?</div>
        <div class="ctx-choice-btns">
            <button class="ctx-btn ctx-btn-followup" onclick="_selectContextType('followup', this)">이전 내용 기반 답변</button>
            <button class="ctx-btn ctx-btn-new" onclick="_selectContextType('new', this)">새로 검색</button>
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

window._selectContextType = async function(forceType, btnEl) {
    const question = _unsureQuestion;
    if (!question) return;

    // 선택 UI 비활성화
    const choiceDiv = btnEl.closest('.context-choice');
    choiceDiv.querySelectorAll('button').forEach(b => b.disabled = true);
    btnEl.classList.add('ctx-btn-selected');

    _currentRequestId = crypto.randomUUID().replace(/-/g, '').substring(0, 8);
    _showStopBtn(true);
    const loadingMsg = addMessage('답변 생성 중...', 'loading');

    try {
        const res = await fetch(API + '/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question, top_k: 10, request_id: _currentRequestId,
                session_id: _sessionId,
                chat_history: _chatHistory,
                force_type: forceType,
            }),
        });
        const data = await res.json();
        loadingMsg.remove();
        if (res.status === 499) {
            addMessage('요청이 중지되었습니다.', 'system');
        } else {
            addMessage(data.answer, 'bot', data.sources, null, data.question_type);
            _chatHistory.push({role: 'user', content: question});
            _chatHistory.push({role: 'assistant', content: data.answer || ''});
            if (data.session_id) _sessionId = data.session_id;
            if (data.context_type === 'new') {
                _chatHistory = [
                    {role: 'user', content: question},
                    {role: 'assistant', content: data.answer || ''},
                ];
            }
            _prevQuestion = question;
            _prevAnswer = data.answer || '';
            _prevDrNumbers = (data.sources || []).map(s => s.dr_number).filter(Boolean);
        }
    } catch (e) {
        loadingMsg.remove();
        addMessage('오류: 서버에 연결할 수 없습니다.', 'system');
    }
    _currentRequestId = null;
    _showStopBtn(false);
    _unsureQuestion = '';
};

function renderToolsBadges(toolsUsed) {
    if (!toolsUsed || toolsUsed.length === 0) return '';
    const unique = [...new Set(toolsUsed)];
    return '<div class="tools-used">' +
        '<span class="tools-used-label">🔧 사용된 도구:</span>' +
        unique.map(t => `<span class="tool-badge">${t}</span>`).join('') +
        '</div>';
}

function renderDBResponse(data) {
    // LLM Agent 응답 형식: {success, answer, tools_used, tool_results}
    if (data.success === false) {
        addMessage('❌ DB 오류: ' + (data.answer || data.error || '알 수 없는 오류'), 'system');
        return;
    }

    // LLM 자연어 답변 표시
    const answer = data.answer || '';
    const div = addMessage(answer, 'bot');

    // 사용된 도구 배지
    if (data.tools_used && data.tools_used.length > 0) {
        const tb = document.createElement('div');
        tb.innerHTML = renderToolsBadges(data.tools_used);
        div.appendChild(tb);
    }

    // tool_results에서 테이블 데이터가 있으면 렌더링
    if (data.tool_results && data.tool_results.length > 0) {
        for (const tr of data.tool_results) {
            const result = tr.result;
            if (!result) continue;

            // get_all_tables 결과 → 테이블 목록
            if (tr.tool === 'get_all_tables' && Array.isArray(result) && result.length > 0) {
                const listDiv = document.createElement('div');
                listDiv.className = 'db-result-block';
                listDiv.innerHTML = `<div class="db-result-header">📋 테이블 목록 (${result.length}개)</div>`
                    + `<table class="db-result-table"><thead><tr><th>테이블명</th><th>스키마</th><th>타입</th><th>컬럼수</th></tr></thead><tbody>`
                    + result.slice(0, 200).map(t =>
                        `<tr><td style="color:var(--primary);font-weight:600;cursor:pointer" onclick="chatInput.value='${t.table_name}';sendQuestion()">${t.table_name}</td><td>${t.table_schema || '-'}</td><td>${t.table_type || '-'}</td><td>${t.column_count || '-'}</td></tr>`
                    ).join('')
                    + `</tbody></table>`;
                div.appendChild(listDiv);
            }

            // get_table_schema 결과 → 스키마 테이블
            if (tr.tool === 'get_table_schema' && result.columns && result.columns.length > 0) {
                const schemaDiv = document.createElement('div');
                schemaDiv.className = 'db-result-block';
                const pks = new Set(result.primary_keys || []);
                const tname = tr.arguments?.table_name || 'unknown';
                schemaDiv.innerHTML = `<div class="db-result-header">🗄️ ${tname} (${result.columns.length}개 컬럼)</div>`
                    + `<table class="db-result-table"><thead><tr><th>컬럼명</th><th>타입</th><th>Nullable</th></tr></thead><tbody>`
                    + result.columns.map(c => {
                        const pkBadge = pks.has(c.column_name) ? '<span class="pk-badge">PK</span>' : '';
                        return `<tr><td>${c.column_name}${pkBadge}</td><td>${c.data_type}</td><td>${c.is_nullable}</td></tr>`;
                    }).join('')
                    + `</tbody></table>`;
                div.appendChild(schemaDiv);
            }

            // execute_query 결과 → 쿼리 결과 테이블
            if (tr.tool === 'execute_query' && result.success && result.rows && result.rows.length > 0) {
                const qDiv = document.createElement('div');
                qDiv.innerHTML = renderQueryResult(result);
                div.appendChild(qDiv);
            }
        }
    }
}

function renderQueryResult(r) {
    if (!r.rows || r.rows.length === 0) return '';
    const keys = Object.keys(r.rows[0]);
    let html = `<div class="db-result-block"><div style="overflow-x:auto;"><table class="db-result-table"><thead><tr>`;
    for (const k of keys) html += `<th>${k}</th>`;
    html += `</tr></thead><tbody>`;
    for (const row of r.rows) {
        html += '<tr>';
        for (const k of keys) {
            const val = row[k] === null ? '<i style="color:var(--text-muted)">NULL</i>' : String(row[k]).substring(0, 80);
            html += `<td>${val}</td>`;
        }
        html += '</tr>';
    }
    html += `</tbody></table></div></div>`;
    return html;
}

chatSend.addEventListener('click', sendQuestion);
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.shiftKey) {
        // Shift+Enter → 커서 위치에 줄바꿈 삽입
        e.preventDefault();
        const start = chatInput.selectionStart;
        const end = chatInput.selectionEnd;
        chatInput.value = chatInput.value.substring(0, start) + '\n' + chatInput.value.substring(end);
        chatInput.selectionStart = chatInput.selectionEnd = start + 1;
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
    } else if (e.key === 'Enter') {
        // Enter → 전송
        e.preventDefault();
        sendQuestion();
    }
});
chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
});

// ── 피드백 ────────────────────────────────────────────────────
window.sendFeedback = async function(btn, rating) {
    const container = btn.parentElement;
    const question = container.dataset.question;
    const sources = JSON.parse(container.dataset.sources || '[]');

    container.querySelectorAll('button').forEach(b => b.classList.remove('selected'));
    btn.classList.add('selected');

    try {
        await fetch(API + '/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                rating,
                reason: '',
                sources_used: sources.map(s => ({ section_id: s.dr_number + '::' + s.heading_path, score: s.score })),
            }),
        });
    } catch (e) { /* 무시 */ }
};

// ── 문서 목록 ─────────────────────────────────────────────
let _allDocuments = [];  // 문서 데이터 캐시

async function loadDocuments() {
    const docList = document.getElementById('doc-list');
    docList.innerHTML = '로딩 중...';

    try {
        const res = await fetch(API + '/documents');
        const data = await res.json();
        _allDocuments = data.documents || [];
        renderDocuments(_allDocuments);
        document.getElementById('doc-search').value = '';
    } catch (e) {
        docList.innerHTML = '<div style="color:var(--danger);">서버 연결 오류</div>';
    }
}

function renderDocuments(docs) {
    const docList = document.getElementById('doc-list');
    if (docs.length === 0) {
        docList.innerHTML = '<div style="color:var(--text-muted);padding:20px;">검색 결과가 없습니다.</div>';
        return;
    }
    docList.innerHTML = docs.map(d => {
        const invalid = !d.dr_number || !d.title;
        const vc = d.version_count || 1;
        const versionBtn = vc > 1
            ? `<button class="btn-version-toggle" onclick="event.stopPropagation(); _toggleVersions('${d.dr_number}', this)" title="이전 버전 보기">이전 버전 ${vc - 1}건 ▾</button>`
            : '';
        return `
        <div class="doc-card${invalid ? ' doc-card-invalid' : ''}" data-dr="${d.dr_number}">
            <div class="doc-card-content" onclick="showDocDetail('${d.dr_number}', this.closest('.doc-card'))">
                <div class="dr">${d.dr_number || '(DR번호 없음)'}</div>
                <div class="title">${d.title || '(제목 없음)'}${invalid ? ' <span class="doc-warn">⚠️ 비정상</span>' : ''}</div>
                <div class="meta">${d.system || ''} | ${d.target_year_month || ''} | ${d.doc_version || ''} ${versionBtn}</div>
            </div>
            <button class="btn-delete-doc" onclick="event.stopPropagation(); deleteDocument('${d.dr_number}', this.closest('.doc-card'))" title="삭제">🗑️</button>
        </div>`;
    }).join('');
}

window._toggleVersions = async function(drNumber, btnEl) {
    const card = btnEl.closest('.doc-card');
    // 이미 열려있으면 닫기
    const existing = card.nextElementSibling;
    if (existing && existing.classList.contains('doc-versions')) {
        existing.remove();
        btnEl.textContent = btnEl.textContent.replace('▴', '▾');
        return;
    }
    // 버전 목록 조회
    try {
        const res = await fetch(API + '/documents/' + drNumber + '/versions');
        const data = await res.json();
        const versions = data.versions || [];
        if (versions.length <= 1) return;

        // 최신(첫번째) 제외하고 이전 버전만 표시
        const oldVersions = versions.slice(1);
        const div = document.createElement('div');
        div.className = 'doc-versions';
        div.innerHTML = oldVersions.map(v => `
            <div class="doc-version-item" onclick="showDocDetail('${v.dr_number}', this, '${v.target_year_month}')">
                <span class="doc-version-ym">${v.target_year_month}</span>
                <span class="doc-version-title">${v.title || ''}</span>
                <span class="doc-version-file">${v.file_name || ''}</span>
            </div>
        `).join('');
        card.after(div);
        btnEl.textContent = btnEl.textContent.replace('▾', '▴');
    } catch (e) {
        console.error('버전 목록 조회 실패:', e);
    }
};

// 비정상 문서 정리
document.getElementById('btn-cleanup').addEventListener('click', async () => {
    if (!confirm('DR번호가 없거나 요약이 없는 비정상 문서를 삭제합니다.\n계속하시겠습니까?')) return;
    try {
        const res = await fetch(API + '/documents/cleanup', { method: 'POST' });
        const data = await res.json();
        if (data.removed_count > 0) {
            alert(`${data.removed_count}건 정리 완료:\n` + data.removed.map(r => `${r.dr_number || '(빈DR)'} - ${r.reason}`).join('\n'));
        } else {
            alert('정리할 비정상 문서가 없습니다.');
        }
        loadDocuments();
        loadStats();
    } catch (e) {
        alert('정리 실패: ' + e.message);
    }
});

// 검색 필터링
document.getElementById('doc-search').addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    if (!q) { renderDocuments(_allDocuments); return; }
    const filtered = _allDocuments.filter(d =>
        (d.dr_number || '').toLowerCase().includes(q) ||
        (d.title || '').toLowerCase().includes(q) ||
        (d.system || '').toLowerCase().includes(q)
    );
    renderDocuments(filtered);
});

window.deleteDocument = async function(drNumber, cardEl) {
    if (!confirm(`${drNumber} 문서를 삭제하시겠습니까?\n(NoSQL + 벡터DB 모두 삭제됩니다)`)) return;

    try {
        const res = await fetch(API + '/documents/' + drNumber, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            // 상세가 열려있으면 같이 제거
            const detail = cardEl.nextElementSibling;
            if (detail && detail.classList.contains('doc-detail')) detail.remove();
            cardEl.remove();
            loadStats();
        } else {
            alert('삭제 실패: ' + (data.detail || 'unknown error'));
        }
    } catch (e) {
        alert('서버 연결 오류: ' + e.message);
    }
};

window.showDocDetail = async function(drNumber, cardEl, targetYm) {
    // 이미 열려있는 상세 닫기
    const existing = cardEl.nextElementSibling;
    if (existing && existing.classList.contains('doc-detail')) {
        existing.remove();
        return;
    }
    // 다른 곳에 열린 상세도 닫기
    document.querySelectorAll('.doc-detail').forEach(el => el.remove());

    try {
        const url = targetYm
            ? API + '/documents/' + drNumber + '?ym=' + targetYm
            : API + '/documents/' + drNumber;
        const res = await fetch(url);
        const data = await res.json();

        const docSummary = data.document.document_summary || '';
        const sections = data.sections || [];

        // 통합 요약을 📌 꼭지별로 파싱
        const summaryBlocks = [];
        if (docSummary) {
            const blocks = docSummary.split(/(?=📌)/);
            for (const block of blocks) {
                const trimmed = block.trim();
                if (trimmed) summaryBlocks.push(trimmed);
            }
        }

        // 꼭지 → section_type + 표시방식 매핑
        const topicConfig = {
            '개발 목적': { type: '과제분석', mode: 'summary' },
            '주요 개발': { type: '과제분석', mode: 'summary' },
            '변경 테이블': { type: 'DB참조', mode: 'content' },
            '변경 소스': { type: '구현방안', mode: 'summary' },
            '검증': { type: '검증방안', mode: 'summary' },
            '이슈': { type: '이슈사항', mode: 'summary' },
            '유의': { type: '이슈사항', mode: 'summary' },
        };

        function _findDetailByTopic(topic) {
            for (const [kw, cfg] of Object.entries(topicConfig)) {
                if (topic.includes(kw)) {
                    const matched = sections.filter(s => s.section_type === cfg.type);
                    const field = cfg.mode === 'content' ? 'detail' : 'summary';
                    return { sections: matched.filter(s => (s[field] || s.content || '').trim()), field };
                }
            }
            return { sections: [], field: 'summary' };
        }

        const detail = document.createElement('div');
        detail.className = 'doc-detail';
        let html = '<h3>' + data.document.dr_number + ' - ' + data.document.title + '</h3>';

        if (summaryBlocks.length > 0) {
            html += '<div class="doc-summary-box">';
            summaryBlocks.forEach((block, idx) => {
                const firstLine = block.split('\n')[0];
                const { sections: detailSecs, field } = _findDetailByTopic(firstLine);
                const blockId = 'raw-' + drNumber.replace(/[^a-zA-Z0-9]/g, '') + '-' + idx;
                const btnLabel = field === 'content' ? '원문 보기' : '상세 보기';

                html += '<div class="doc-topic">';
                html += '<div class="doc-topic-text">' + block.replace(/\n/g, '<br>') + '</div>';

                if (detailSecs.length > 0) {
                    html += '<div class="doc-topic-rawbtn" onclick="var el=document.getElementById(\'' + blockId + '\');el.style.display=el.style.display===\'none\'?\'block\':\'none\';this.textContent=el.style.display===\'none\'?\'' + btnLabel + ' ▼\':\'' + btnLabel + ' ▲\';">' + btnLabel + ' ▼</div>';
                    html += '<div id="' + blockId + '" style="display:none;">';
                    detailSecs.forEach(s => {
                        const body = (field === 'content' ? (s.detail || s.content || '') : (s.summary || '')).replace(/\n/g, '<br>');
                        html += '<div class="doc-raw-item">';
                        html += '<div class="doc-raw-path">' + (s.heading_path || '') + '</div>';
                        html += '<div class="doc-raw-body">' + body + '</div>';
                        html += '</div>';
                    });
                    html += '</div>';
                }
                html += '</div>';
            });
            html += '</div>';
        } else {
            html += '<div style="color:var(--text-muted)">통합 요약이 없습니다. 문서를 재적재하면 생성됩니다.</div>';
        }

        detail.innerHTML = html;

        // 클릭한 카드 바로 아래에 삽입
        cardEl.insertAdjacentElement('afterend', detail);
    } catch (e) {
        console.error(e);
    }
};

window.toggleEditSection = function(btn) {
    const item = btn.closest('.section-item') || btn.closest('.section-accordion-body');
    const view = item.querySelector('.summary-view');
    let edit = item.querySelector('.summary-edit');

    if (!edit) {
        // 아코디언 구조: 편집 영역 동적 생성
        const editArea = btn.closest('.section-edit-area');
        const sectionId = editArea ? editArea.dataset.sectionId : '';
        edit = document.createElement('div');
        edit.className = 'summary-edit';
        edit.innerHTML = '<textarea class="edit-textarea">' + (view.textContent || '') + '</textarea>'
            + '<div class="edit-actions">'
            + '<button class="btn-save" onclick="saveSectionEdit(this)">💾 저장</button>'
            + '<button class="btn-cancel" onclick="cancelSectionEdit(this)">취소</button>'
            + '</div>';
        edit.dataset.sectionId = sectionId;
        item.appendChild(edit);
    }

    const isEditing = edit.style.display !== 'none';
    view.style.display = isEditing ? '' : 'none';
    edit.style.display = isEditing ? 'none' : '';
    btn.textContent = isEditing ? '✏️ 편집' : '❌ 닫기';
};

window.cancelSectionEdit = function(btn) {
    const item = btn.closest('.section-item') || btn.closest('.section-accordion-body');
    item.querySelector('.summary-view').style.display = '';
    item.querySelector('.summary-edit').style.display = 'none';
    const editBtn = item.querySelector('.btn-edit');
    if (editBtn) editBtn.textContent = '✏️ 편집';
};

window.saveSectionEdit = async function(btn) {
    const item = btn.closest('.section-item') || btn.closest('.section-accordion-body');
    const editEl = btn.closest('.summary-edit');
    const sectionId = (item.dataset && item.dataset.sectionId) || (editEl && editEl.dataset.sectionId) || '';
    const textarea = item.querySelector('.edit-textarea');
    const newSummary = textarea.value.trim();

    btn.disabled = true;
    btn.textContent = '저장 중...';

    try {
        const res = await fetch(API + '/sections/' + sectionId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ summary: newSummary }),
        });
        const data = await res.json();

        if (res.ok) {
            // 뷰 업데이트
            item.querySelector('.summary-view').innerHTML = newSummary.replace(/\n/g, '<br>');
            cancelSectionEdit(btn);
            btn.textContent = '💾 저장';
        } else {
            alert('저장 실패: ' + (data.detail || 'unknown error'));
        }
    } catch (e) {
        alert('서버 연결 오류');
    }

    btn.disabled = false;
    btn.textContent = '💾 저장';
};

// ── 문서 적재 ─────────────────────────────────────────────
const btnScan = document.getElementById('btn-scan');
const folderPath = document.getElementById('folder-path');
const scanResult = document.getElementById('scan-result');
const loadProgress = document.getElementById('load-progress');
const saveFolderCheck = document.getElementById('save-folder-check');

// 폴더 경로 복원 (config.yaml에서)
(async function restoreFolderPath() {
    try {
        const res = await fetch(API + '/loader/folder-path');
        const data = await res.json();
        if (data.folder_path) {
            folderPath.value = data.folder_path;
            saveFolderCheck.checked = true;
        }
    } catch (e) { /* 서버 미연결 시 무시 */ }
})();

// 체크 해제 시 저장된 경로 삭제
saveFolderCheck.addEventListener('change', async () => {
    if (saveFolderCheck.checked) {
        const path = folderPath.value.trim();
        if (path) await fetch(API + '/loader/folder-path', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: path }),
        });
    } else {
        await fetch(API + '/loader/folder-path', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: '' }),
        });
    }
});

// 폴더 경로 변경 시 저장 상태면 같이 업데이트
folderPath.addEventListener('change', async () => {
    if (saveFolderCheck.checked) {
        const path = folderPath.value.trim();
        if (path) await fetch(API + '/loader/folder-path', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: path }),
        });
    }
});

btnScan.addEventListener('click', async () => {
    const path = folderPath.value.trim();
    if (!path) return;

    btnScan.disabled = true;
    btnScan.textContent = '스캔 중...';
    scanResult.style.display = 'none';

    try {
        const res = await fetch(API + '/load-folder/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_path: path }),
        });
        const data = await res.json();

        scanResult.style.display = 'block';
        scanResult.innerHTML = `
            <div class="summary">
                📂 ${data.folder_path}<br>
                총 ${data.total_docx}개 | 신규 <b>${data.new}</b>개 | 적재됨 ${data.already_loaded}개
            </div>
            <div style="margin-bottom:8px;display:flex;gap:10px;align-items:center">
                <label style="font-size:12px;color:var(--text-muted);cursor:pointer"><input type="checkbox" id="select-all-files" onchange="toggleAllFiles(this)"> 전체선택</label>
                <span style="flex:1"></span>
                <button onclick="startLoad('all')">전체 적재</button>
                <button onclick="startLoad('new_only')">신규만 적재</button>
                <button onclick="startLoad('selected')">선택 적재</button>
            </div>
            <div class="file-list">
                ${data.files.map(f => `
                    <div class="file-item">
                        <label style="display:flex;align-items:center;gap:8px;flex:1;cursor:pointer">
                            <input type="checkbox" class="file-check" value="${f.filename}" ${f.status === 'new' ? 'checked' : ''}>
                            <span style="flex:1;word-break:break-all">${f.filename}</span>
                        </label>
                        <span class="status-${f.status}">${f.status === 'new' ? '🆕 신규' : '✅ 적재됨'}</span>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (e) {
        scanResult.style.display = 'block';
        scanResult.innerHTML = '<div style="color:var(--danger);">스캔 실패: ' + e.message + '</div>';
    }

    btnScan.disabled = false;
    btnScan.textContent = '스캔';
});

// 스트리밍 적재 공통 로직
async function streamLoad(url, body, logEl) {
    _isLoadingDoc = true;
    logEl.textContent = 'Connecting...\n';
    let res;
    try {
        res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    } catch (e) {
        logEl.textContent += '\n❌ fetch 실패: ' + e.message + '\n';
        return;
    }
    logEl.textContent = '';
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
            if (!line.trim()) continue;
            try {
                const msg = JSON.parse(line);
                if (msg.type === 'start') {
                    logEl.textContent += `📂 총 ${msg.total}개 파일 적재 시작\n`;
                } else if (msg.type === 'status') {
                    logEl.textContent += `ℹ️ ${msg.message}\n`;
                } else if (msg.type === 'file_start') {
                    logEl.textContent += `\n📄 [${msg.current}/${msg.total}] ${msg.file}\n`;
                } else if (msg.type === 'detail') {
                    if (msg.step === 'parsed') {
                        logEl.textContent += `  📌 DR: ${msg.dr_number} | ${msg.title} | ${msg.total_sections}섹션\n`;
                    } else if (msg.step === 'summarize') {
                        logEl.textContent += `  🤖 [${msg.current}/${msg.total}] LLM 요약: ${msg.heading}\n`;
                    } else if (msg.step === 'summarized') {
                        logEl.textContent += `     ✅ ${msg.summary_length}자 — ${msg.summary_preview?.substring(0, 80)}...\n`;
                    } else if (msg.step === 'embedding') {
                        logEl.textContent += `  🔢 ${msg.message}\n`;
                    } else if (msg.step === 'embedded') {
                        if (msg.status === 'error') {
                            logEl.textContent += `  ${msg.message}\n`;
                        } else {
                            logEl.textContent += `  ✅ ${msg.message}\n`;
                        }
                    } else if (msg.step === 'tagging') {
                        logEl.textContent += `  🏷️ ${msg.message}\n`;
                    } else if (msg.step === 'tagged') {
                        logEl.textContent += `  🏷️ ${msg.message}\n`;
                    } else if (msg.step === 'saving') {
                        logEl.textContent += `  💾 ${msg.message}\n`;
                    } else if (msg.step === 'done') {
                        logEl.textContent += `  ✅ ${msg.message}\n`;
                    } else if (msg.message) {
                        logEl.textContent += `  ℹ️ ${msg.message}\n`;
                    }
                } else if (msg.type === 'result') {
                    if (msg.skipped) {
                        logEl.textContent += `  ⏭️ 이미 적재됨 (skip)\n`;
                    } else if (msg.embedding_failed) {
                        logEl.textContent += `\n  ⚠️ ${msg.dr_number} 적재 완료 (임베딩 실패: ${msg.embedding_error}) — ${msg.sections}섹션, 0벡터, ${msg.tagged_categories?.length || 0}카테고리, ${msg.elapsed?.toFixed(1)}초\n`;
                    } else {
                        logEl.textContent += `\n  🎉 ${msg.dr_number} 적재 완료 — ${msg.sections}섹션, ${msg.chunks}벡터, ${msg.tagged_categories?.length || 0}카테고리, ${msg.elapsed?.toFixed(1)}초\n`;
                    }
                } else if (msg.type === 'error') {
                    const icon = msg.error_type === 'encrypted' ? '🔒'
                               : msg.error_type === 'permission_error' ? '🚫'
                               : msg.error_type === 'invalid_format' ? '📄'
                               : msg.error_type === 'no_dr_number' ? '🏷️'
                               : '❌';
                    logEl.textContent += `  ${icon} ${msg.file || ''}: ${msg.error}\n`;
                } else if (msg.type === 'done') {
                    logEl.textContent += `\n✅ 적재 완료!\n`;
                    logEl.textContent += `DB: 문서 ${msg.stats.documents}건, 섹션 ${msg.stats.sections}건, 벡터 ${msg.stats.vectors}건\n`;
                }
                logEl.scrollTop = logEl.scrollHeight;
            } catch (e) {
                console.error('stream parse error:', e, line);
            }
        }
    }
    _isLoadingDoc = false;
}

window.startLoad = async function(filter) {
    const path = folderPath.value.trim();
    let selectedFiles = [];
    if (filter === 'selected') {
        selectedFiles = [...document.querySelectorAll('.file-check:checked')].map(c => c.value);
        if (selectedFiles.length === 0) { alert('파일을 선택해주세요.'); return; }
    }
    loadProgress.style.display = 'block';
    loadProgress.innerHTML = '<div class="log"></div>';
    const log = loadProgress.querySelector('.log');

    const body = { folder_path: path, filter: filter === 'selected' ? 'all' : filter };
    if (selectedFiles.length > 0) body.selected_files = selectedFiles;

    try {
        await streamLoad(API + '/load-folder/start', body, log);
    } catch (e) {
        log.textContent += '\n❌ 에러: ' + e.message + '\n';
    }
    loadStats();
};

window.toggleAllFiles = function(el) {
    document.querySelectorAll('.file-check').forEach(c => c.checked = el.checked);
};

// ── 개별 파일 적재 ────────────────────────────────────────────
const btnLoadFile = document.getElementById('btn-load-file');
const filePath = document.getElementById('file-path');
const fileLoadProgress = document.getElementById('file-load-progress');

btnLoadFile.addEventListener('click', async () => {
    const path = filePath.value.trim();
    if (!path) return;

    btnLoadFile.disabled = true;
    btnLoadFile.textContent = '적재 중...';
    fileLoadProgress.style.display = 'block';
    fileLoadProgress.innerHTML = '<div class="log"></div>';
    const log = fileLoadProgress.querySelector('.log');

    try {
        await streamLoad(API + '/load-file', { file_path: path }, log);
    } catch (e) {
        log.textContent += '❌ 서버 연결 오류: ' + e.message + '\n';
    }

    btnLoadFile.disabled = false;
    btnLoadFile.textContent = '적재';
    loadStats();
});

// ══════════════════════════════════════════════════════════════
// ── 환경설정 페이지 ──────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════

async function loadSettings() {
    loadLLMConfig();
    loadDBConfig();
}

// ── LLM 설정 ────────────────────────────────────────────────────────

const llmApiUrl = document.getElementById('llm-api-url');
const llmApiKey = document.getElementById('llm-api-key');

async function loadLLMConfig() {
    try {
        const res = await fetch(API + '/llm/config');
        const data = await res.json();
        llmApiUrl.value = data.base_url || '';
        llmApiKey.value = data.api_key || '';
    } catch (e) { /* 서버 미연결 시 무시 */ }
}

document.getElementById('btn-llm-save').addEventListener('click', async () => {
    await saveLLMSettings();
});

async function saveLLMSettings() {
    const statusEl = document.getElementById('llm-status');
    try {
        const res = await fetch(API + '/llm/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                api_key: llmApiKey.value.trim(),
                base_url: llmApiUrl.value.trim(),
            }),
        });
        const data = await res.json();
        statusEl.className = 'db-status success';
        statusEl.textContent = '✅ LLM 설정 저장됨';
        setTimeout(() => { statusEl.textContent = ''; }, 3000);
    } catch (e) {
        statusEl.className = 'db-status error';
        statusEl.textContent = '❌ 저장 실패: ' + e.message;
    }
}

// ── DB 연결 설정 ────────────────────────────────────────────────────

const dbTypeSelect = document.getElementById('db-type-select');
const pgConfig = document.getElementById('pg-config');
const oraConfig = document.getElementById('ora-config');

// DB 타입 변경 시 폼 전환
dbTypeSelect.addEventListener('change', () => {
    const isOracle = dbTypeSelect.value === 'oracle';
    pgConfig.style.display = isOracle ? 'none' : '';
    oraConfig.style.display = isOracle ? '' : 'none';
});

// DB 설정 로드
async function loadDBConfig() {
    try {
        const res = await fetch(API + '/db/config');
        const data = await res.json();

        dbTypeSelect.value = data.active_db_type || 'postgres';
        dbTypeSelect.dispatchEvent(new Event('change'));

        // PostgreSQL
        const pg = data.db_postgres || {};
        document.getElementById('pg-host').value = pg.host || 'localhost';
        document.getElementById('pg-port').value = pg.port || '5432';
        document.getElementById('pg-dbname').value = pg.dbname || 'postgres';
        document.getElementById('pg-user').value = pg.user || 'postgres';
        document.getElementById('pg-password').value = pg.password || '';

        // Oracle
        const ora = data.db_oracle || {};
        document.getElementById('ora-host').value = ora.host || 'localhost';
        document.getElementById('ora-port').value = ora.port || '1521';
        document.getElementById('ora-service').value = ora.service_name || 'ORCL';
        document.getElementById('ora-sid').value = ora.sid || '';
        document.getElementById('ora-user').value = ora.user || 'system';
        document.getElementById('ora-password').value = ora.password || '';
        document.getElementById('ora-thick').checked = ora.thick_mode || false;
    } catch (e) {
        console.error('DB 설정 로드 실패:', e);
    }
}

// DB 설정 저장
document.getElementById('btn-db-save').addEventListener('click', async () => {
    const statusEl = document.getElementById('db-status');
    statusEl.className = 'db-status';
    statusEl.textContent = '저장 중...';

    const body = {
        active_db_type: dbTypeSelect.value,
        db_postgres: {
            user: document.getElementById('pg-user').value,
            password: document.getElementById('pg-password').value,
            host: document.getElementById('pg-host').value,
            port: document.getElementById('pg-port').value,
            dbname: document.getElementById('pg-dbname').value,
        },
        db_oracle: {
            user: document.getElementById('ora-user').value,
            password: document.getElementById('ora-password').value,
            host: document.getElementById('ora-host').value,
            port: document.getElementById('ora-port').value,
            service_name: document.getElementById('ora-service').value,
            sid: document.getElementById('ora-sid').value || null,
            thick_mode: document.getElementById('ora-thick').checked,
            oracle_client_lib_dir: null,
        },
    };

    try {
        const res = await fetch(API + '/db/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        statusEl.className = 'db-status success';
        statusEl.textContent = '✅ 저장 완료';
    } catch (e) {
        statusEl.className = 'db-status error';
        statusEl.textContent = '❌ 저장 실패: ' + e.message;
    }
});

// DB 연결 테스트
document.getElementById('btn-db-test').addEventListener('click', async () => {
    const statusEl = document.getElementById('db-status');
    statusEl.className = 'db-status';
    statusEl.textContent = '🔗 연결 테스트 중...';

    try {
        // 먼저 저장
        document.getElementById('btn-db-save').click();
        await new Promise(r => setTimeout(r, 300));

        const res = await fetch(API + '/db/test', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            statusEl.className = 'db-status success';
            statusEl.textContent = `✅ ${data.message} (${data.db_type})`;
        } else {
            statusEl.className = 'db-status error';
            statusEl.textContent = `❌ 연결 실패: ${data.error}`;
        }
    } catch (e) {
        statusEl.className = 'db-status error';
        statusEl.textContent = '❌ 서버 연결 오류: ' + e.message;
    }
});


// ══════════════════════════════════════════════════════════════
// ── 업무분류 관리 ──────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════

const LEVEL_NAMES = ['대분류', '중분류', '소분류', '상세분류'];
const MAX_LEVEL = 99;
let _catExpanded = false;
const _catExpandedIds = new Set();

async function loadCategories() {
    const tree = document.getElementById('category-tree');
    tree.innerHTML = '<div style="padding:16px;color:var(--text-muted)">로딩 중...</div>';
    try {
        const res = await fetch(API + '/categories');
        const data = await res.json();
        const docCounts = data.doc_counts || {};
        tree.innerHTML = '';
        renderCatTree(data.categories || [], tree, 0, docCounts);
        if ((data.categories || []).length === 0) {
            tree.innerHTML = '<div style="padding:20px;color:var(--text-muted);text-align:center">카테고리가 없습니다. 대분류를 추가해주세요.</div>';
        }
        // Restore expanded state from _catExpandedIds
        _catExpandedIds.forEach(id => {
            const el = document.getElementById('cat-children-' + id);
            if (el) {
                el.classList.remove('collapsed');
                // Update the toggle arrow in the preceding .cat-node row
                const prev = el.previousElementSibling;
                if (prev) {
                    const tog = prev.querySelector('.cat-toggle');
                    if (tog) tog.textContent = '\u25bc';
                }
            }
        });
        // Sync the toggle-all button state
        const allContainers = document.querySelectorAll('.cat-children');
        if (allContainers.length > 0) {
            const allExpanded = Array.from(allContainers).every(c => !c.classList.contains('collapsed'));
            _catExpanded = allExpanded;
        } else {
            _catExpanded = false;
        }
        const toggleBtn = document.getElementById('btn-toggle-all');
        if (toggleBtn) toggleBtn.textContent = _catExpanded ? '\ud83d\udcc1 \uc804\uccb4 \uc811\uae30' : '\ud83d\udcc2 \uc804\uccb4 \ud3bc\uce58\uae30';
    } catch (e) {
        tree.innerHTML = '<div style="padding:16px;color:var(--danger)">서버 연결 오류</div>';
    }
}

function _countDocsUnder(node, docCounts) {
    // 이 노드 자체 + 모든 하위 카테고리에 속한 문서 수 합산
    let count = docCounts[node.id] || 0;
    if (node.children) {
        for (const child of node.children) {
            count += _countDocsUnder(child, docCounts);
        }
    }
    return count;
}

function renderCatTree(nodes, container, level, docCounts) {
    for (const node of nodes) {
        const hasChildren = node.children && node.children.length > 0;
        const isLeaf = !hasChildren;
        const canAddChild = level < MAX_LEVEL;
        const docCount = _countDocsUnder(node, docCounts);

        const row = document.createElement('div');
        row.className = 'cat-node';
        row.dataset.level = level;
        row.style.paddingLeft = (14 + level * 24) + 'px';

        // 토글
        const toggle = document.createElement('button');
        toggle.className = 'cat-toggle' + (hasChildren ? '' : ' leaf');
        toggle.textContent = hasChildren ? '▶' : '';
        row.appendChild(toggle);

        // 이름
        const nameSpan = document.createElement('span');
        nameSpan.className = 'cat-name';
        nameSpan.textContent = node.name;
        if (isLeaf) nameSpan.classList.add('cat-name-leaf');
        row.appendChild(nameSpan);

        // 배지 (해당 카테고리 하위 문서 총 수)
        if (docCount > 0) {
            const badge = document.createElement('span');
            badge.className = 'cat-badge';
            badge.textContent = docCount;
            badge.title = `문서 ${docCount}건`;
            row.appendChild(badge);
        }

        // 액션
        const actions = document.createElement('span');
        actions.className = 'cat-actions';
        actions.innerHTML = `
            <button title="편집" onclick="editCategory('${node.id}','${node.name.replace(/'/g, "\\'")}')">\u270f\ufe0f</button>
            ${canAddChild ? `<button title="\ud558\uc704 \ucd94\uac00" onclick="addCategory('${node.id}', ${level + 1})">\u2795</button>` : ''}
            <button class="cat-btn-del" title="\uc0ad\uc81c" onclick="deleteCategory('${node.id}','${node.name.replace(/'/g, "\\'")}')">\ud83d\uddd1\ufe0f</button>
        `;
        row.appendChild(actions);
        container.appendChild(row);

        if (hasChildren) {
            const childContainer = document.createElement('div');
            childContainer.className = 'cat-children collapsed';
            childContainer.id = 'cat-children-' + node.id;
            renderCatTree(node.children, childContainer, level + 1, docCounts);
            container.appendChild(childContainer);

            toggle.addEventListener('click', () => {
                const collapsed = childContainer.classList.toggle('collapsed');
                toggle.textContent = collapsed ? '\u25b6' : '\u25bc';
                if (collapsed) {
                    _catExpandedIds.delete(node.id);
                } else {
                    _catExpandedIds.add(node.id);
                }
            });
        }

        // leaf 노드: 클릭 시 문서 목록 표시
        if (isLeaf) {
            const docListPanel = document.createElement('div');
            docListPanel.className = 'cat-doc-list collapsed';
            docListPanel.id = 'cat-docs-' + node.id;
            container.appendChild(docListPanel);

            nameSpan.addEventListener('click', () => _toggleCatDocs(node.id, docListPanel, level));
        }
    }
}

async function _toggleCatDocs(catId, panel, level) {
    // 이미 열려있으면 닫기
    if (!panel.classList.contains('collapsed')) {
        panel.classList.add('collapsed');
        return;
    }

    panel.style.paddingLeft = (14 + (level + 1) * 24) + 'px';
    panel.innerHTML = '<div class="cat-doc-loading">문서 조회 중...</div>';
    panel.classList.remove('collapsed');

    try {
        const res = await fetch(API + '/categories/' + catId + '/documents');
        const data = await res.json();
        const docs = data.documents || [];

        if (docs.length === 0) {
            panel.innerHTML = '<div class="cat-doc-empty">태깅된 문서가 없습니다.</div>';
            return;
        }

        panel.innerHTML = docs.map(d =>
            `<div class="cat-doc-item" onclick="window.open('#doc-${d.dr_number}','_self')" title="${d.title || ''}">`
            + `<span class="cat-doc-dr">${d.dr_number}</span>`
            + `<span class="cat-doc-title">${d.title || ''}</span>`
            + `</div>`
        ).join('');
    } catch (e) {
        panel.innerHTML = '<div class="cat-doc-empty">조회 실패: ' + e.message + '</div>';
    }
}


// 전체 펼치기/접기
document.getElementById('btn-toggle-all').addEventListener('click', () => {
    _catExpanded = !_catExpanded;
    const containers = document.querySelectorAll('.cat-children');
    const toggles = document.querySelectorAll('.cat-toggle:not(.leaf)');
    _catExpandedIds.clear();
    containers.forEach(c => {
        if (_catExpanded) {
            c.classList.remove('collapsed');
            // Extract ID from 'cat-children-<id>'
            const nodeId = c.id.replace('cat-children-', '');
            if (nodeId) _catExpandedIds.add(nodeId);
        } else {
            c.classList.add('collapsed');
        }
    });
    toggles.forEach(t => t.textContent = _catExpanded ? '\u25bc' : '\u25b6');
    document.getElementById('btn-toggle-all').textContent = _catExpanded ? '\ud83d\udcc1 \uc804\uccb4 \uc811\uae30' : '\ud83d\udcc2 \uc804\uccb4 \ud3bc\uce58\uae30';
});

// 대분류 추가
document.getElementById('btn-add-root').addEventListener('click', () => {
    addCategory(null, 0);
});

// 카테고리 추가 (인라인 입력)
window.addCategory = function(parentId, level) {
    // 기존 입력 필드 제거
    document.querySelectorAll('.cat-input-row').forEach(el => el.remove());

    const row = document.createElement('div');
    row.className = 'cat-input-row';
    row.style.paddingLeft = (14 + level * 28) + 'px';
    row.innerHTML = `
        <input type="text" placeholder="${LEVEL_NAMES[level] || '항목'}명 입력..." autofocus>
        <button class="btn-ok">확인</button>
        <button class="btn-no">취소</button>
    `;

    // 삽입 위치 결정
    if (parentId) {
        const childContainer = document.getElementById('cat-children-' + parentId);
        if (childContainer) {
            childContainer.appendChild(row);
            childContainer.classList.remove('collapsed');
        } else {
            // children 컨테이너가 없으면 (리프 노드) — 해당 노드 뒤에 삽입
            const allNodes = document.querySelectorAll('.cat-node');
            for (const n of allNodes) {
                const editBtn = n.querySelector('button[title="하위 추가"]');
                if (editBtn && editBtn.getAttribute('onclick')?.includes(`'${parentId}'`)) {
                    n.insertAdjacentElement('afterend', row);
                    break;
                }
            }
        }
    } else {
        document.getElementById('category-tree').appendChild(row);
    }

    const input = row.querySelector('input');
    input.focus();

    const submit = async () => {
        const name = input.value.trim();
        if (!name) return;
        try {
            await fetch(API + '/categories', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ parent_id: parentId, name }),
            });
            loadCategories();
        } catch (e) {
            alert('추가 실패: ' + e.message);
        }
    };

    row.querySelector('.btn-ok').addEventListener('click', submit);
    row.querySelector('.btn-no').addEventListener('click', () => row.remove());
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') submit();
        if (e.key === 'Escape') row.remove();
    });
};

// 카테고리 편집 (인라인)
window.editCategory = function(id, currentName) {
    // 해당 노드 찾기
    const allNodes = document.querySelectorAll('.cat-node');
    for (const node of allNodes) {
        const editBtn = node.querySelector('button[title="편집"]');
        if (editBtn && editBtn.getAttribute('onclick')?.includes(`'${id}'`)) {
            const nameSpan = node.querySelector('.cat-name');
            const original = nameSpan.textContent;
            nameSpan.innerHTML = `
                <input type="text" value="${currentName}" style="
                    padding:4px 8px; background:var(--bg-input); border:1px solid var(--primary);
                    border-radius:5px; color:var(--text-primary); font-size:13px; font-family:inherit;
                    outline:none; width:200px;
                ">
            `;
            const inp = nameSpan.querySelector('input');
            inp.focus();
            inp.select();

            const save = async () => {
                const newName = inp.value.trim();
                if (!newName || newName === currentName) {
                    nameSpan.textContent = original;
                    return;
                }
                try {
                    await fetch(API + '/categories/' + id, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: newName }),
                    });
                    loadCategories();
                } catch (e) {
                    alert('수정 실패: ' + e.message);
                    nameSpan.textContent = original;
                }
            };

            inp.addEventListener('blur', save);
            inp.addEventListener('keydown', e => {
                if (e.key === 'Enter') { inp.blur(); }
                if (e.key === 'Escape') { nameSpan.textContent = original; }
            });
            break;
        }
    }
};

// 카테고리 삭제
window.deleteCategory = async function(id, name) {
    if (!confirm(`"${name}" 카테고리를 삭제하시겠습니까?\n(하위 카테고리도 함께 삭제됩니다)`)) return;
    try {
        await fetch(API + '/categories/' + id, { method: 'DELETE' });
        loadCategories();
    } catch (e) {
        alert('삭제 실패: ' + e.message);
    }
};

// 기존 문서 일괄 재태깅
document.getElementById('btn-retag-all').addEventListener('click', async () => {
    if (!confirm('적재된 모든 문서에 대해 카테고리를 (재)태깅합니다.\nLLM 호출이 문서 수만큼 발생합니다. 진행하시겠습니까?')) return;
    const btn = document.getElementById('btn-retag-all');
    btn.disabled = true;
    btn.textContent = '태깅 중...';
    try {
        const res = await fetch(API + '/categories/retag-all', { method: 'POST' });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
        }
        loadCategories();
        alert('카테고리 재태깅 완료');
    } catch (e) {
        alert('재태깅 실패: ' + e.message);
    }
    btn.disabled = false;
    btn.textContent = '🏷️ 기존문서 일괄태깅';
});

// ══════════════════════════════════════════════════════════════
// ── 카테고리-문서 시각화 (D3 Force Graph — 화면전환 드릴다운) ─
// ══════════════════════════════════════════════════════════════

let _exploreCats = [];
let _exploreDocCounts = {};
let _explorePath = [];
let _gSearchMode = false;

const _LEVEL_LABELS = ['대분류', '중분류', '소분류', '상세분류'];
const _LEVEL_COLORS = ['#f59e0b', '#10b981', '#60a5fa', '#93c5fd'];
const _DOC_COLOR = '#a78bfa';

function _findNode(tree, id) {
    for (const n of tree) {
        if (n.id === id) return n;
        if (n.children) { const f = _findNode(n.children, id); if (f) return f; }
    }
    return null;
}

function _docCountUnder(node) {
    let c = _exploreDocCounts[node.id] || 0;
    if (node.children) for (const ch of node.children) c += _docCountUnder(ch);
    return c;
}

async function loadGraph() {
    try {
        const res = await fetch(API + '/categories');
        const data = await res.json();
        _exploreCats = data.categories || [];
        _exploreDocCounts = data.doc_counts || {};
        _explorePath = [];
        _gSearchMode = false;
        _closeGraphDetail();
        document.getElementById('dr-search-input').value = '';
        document.getElementById('dr-search-result').innerHTML = '';
        _renderGraphLevel(_exploreCats, [], true);
    } catch (e) {
        document.getElementById('graph-container').innerHTML =
            `<div style="padding:20px;color:var(--danger)">서버 연결 오류: ${e.message}</div>`;
    }
}

function _renderBreadcrumb(path) {
    const bc = document.getElementById('explore-breadcrumb');
    if (!bc) return;
    bc.innerHTML = '';
    // 전체
    const allSpan = document.createElement('span');
    allSpan.className = 'explore-crumb' + (path.length === 0 ? ' active' : '');
    allSpan.textContent = '전체';
    allSpan.onclick = () => _navGraph([]);
    bc.appendChild(allSpan);
    // 하위 경로
    for (let i = 0; i < path.length; i++) {
        const sep = document.createElement('span');
        sep.className = 'explore-crumb-sep';
        sep.textContent = '›';
        bc.appendChild(sep);

        const node = _findNode(_exploreCats, path[i]);
        const name = node ? node.name : path[i];
        const isLast = i === path.length - 1;
        const span = document.createElement('span');
        span.className = 'explore-crumb' + (isLast ? ' active' : '');
        span.textContent = name;
        const navPath = path.slice(0, i + 1);
        span.onclick = () => _navGraph(navPath);
        bc.appendChild(span);
    }
}

async function _renderGraphLevel(nodes, path, isInitial) {
    _explorePath = path;
    _renderBreadcrumb(path);
    _closeGraphDetail();

    const container = document.getElementById('graph-container');
    container.innerHTML = '';
    const rect = container.getBoundingClientRect();
    const width = rect.width || 800, height = rect.height || 600;

    const level = path.length;

    // 그래프 노드/링크 구성
    const graphNodes = [];
    const graphLinks = [];

    if (!nodes || nodes.length === 0) {
        // 리프 카테고리 → 상위 체인 + 문서를 D3 트리형(위→아래)으로 표시
        const catId = path[path.length - 1];
        if (!catId) { container.innerHTML = '<div style="padding:20px;color:var(--text-muted)">카테고리가 없습니다.</div>'; return; }
        try {
            const res = await fetch(API + '/categories/' + catId + '/documents');
            const data = await res.json();
            const docs = data.documents || [];
            if (docs.length === 0) { container.innerHTML = '<div style="padding:20px;color:var(--text-muted)">태깅된 문서가 없습니다.</div>'; return; }

            // 상위 카테고리 체인
            let prevChainId = null;
            for (let i = 0; i < path.length; i++) {
                const ancestorId = path[i];
                const ancestorNode = _findNode(_exploreCats, ancestorId);
                const ancestorLevel = ancestorId.split('.').length - 1;
                const isLast = i === path.length - 1;
                graphNodes.push({
                    id: ancestorId, name: ancestorNode ? ancestorNode.name : ancestorId,
                    type: 'category', level: ancestorLevel, isCenter: isLast, catNode: ancestorNode,
                    _treeRow: i  // 트리 행 번호
                });
                if (prevChainId) graphLinks.push({ source: prevChainId, target: ancestorId });
                prevChainId = ancestorId;
            }

            // 문서 노드
            for (let di = 0; di < docs.length; di++) {
                const d = docs[di];
                graphNodes.push({
                    id: d.dr_number, name: d.dr_number + ' ' + (d.title || ''), type: 'document',
                    dr_number: d.dr_number, fullTitle: d.title || '', system: d.system || '',
                    _treeRow: path.length, _treeCol: di, _treeCols: docs.length
                });
                graphLinks.push({ source: catId, target: d.dr_number });
            }

            // 트리형 좌표 직접 계산
            const _isTreeLayout = true;
            const rowH = height / (path.length + 2);
            for (const nd of graphNodes) {
                if (nd._treeRow !== undefined && nd.type !== 'document') {
                    nd.fx = width / 2;
                    nd.fy = rowH * (nd._treeRow + 0.8);
                } else if (nd._treeCol !== undefined) {
                    const cols = nd._treeCols;
                    const spacing = Math.min(180, (width - 100) / cols);
                    const startX = (width - spacing * (cols - 1)) / 2;
                    nd.fx = startX + spacing * nd._treeCol;
                    nd.fy = rowH * (nd._treeRow + 0.8);
                }
            }
        } catch (e) { container.innerHTML = '<div style="padding:20px;color:var(--danger)">조회 실패</div>'; return; }
    } else {
        // 카테고리 노드
        const parentId = path.length > 0 ? path[path.length - 1] : null;
        if (parentId) {
            const parentNode = _findNode(_exploreCats, parentId);
            graphNodes.push({ id: 'center', name: parentNode ? parentNode.name : parentId, type: 'category', level: level - 1, isCenter: true });
        }
        for (const node of nodes) {
            const docCount = _docCountUnder(node);
            const hasChildren = node.children && node.children.length > 0;
            graphNodes.push({ id: node.id, name: node.name, type: 'category', level, docCount, hasChildren, catNode: node });
            if (parentId) graphLinks.push({ source: 'center', target: node.id });
        }
    }

    // D3 Force Graph 그리기
    const svg = d3.select(container).append('svg')
        .attr('width', width).attr('height', height);
    const g = svg.append('g');
    const zoom = d3.zoom().scaleExtent([0.5, 3]).wheelDelta(e => -e.deltaY * 0.002).on('zoom', e => g.attr('transform', e.transform));
    svg.call(zoom);

    const link = g.append('g').selectAll('line').data(graphLinks).join('line')
        .attr('stroke', '#475569').attr('stroke-width', 2).attr('stroke-opacity', 0.5);

    const node = g.append('g').selectAll('g').data(graphNodes).join('g').attr('cursor', 'pointer');

    function _r(d) {
        if (d.isCenter) return 30;
        if (d.type === 'document') return 12;
        return 22;
    }
    function _fill(d) {
        if (d.isCenter) return _LEVEL_COLORS[d.level] || '#94a3b8';
        if (d.type === 'document') return _DOC_COLOR;
        return _LEVEL_COLORS[d.level] || _LEVEL_COLORS[3];
    }

    node.append('circle').attr('r', _r).attr('fill', _fill)
        .attr('stroke', d => d.isCenter ? 'rgba(255,255,255,0.5)' : 'none')
        .attr('stroke-width', d => d.isCenter ? 3 : 0);

    // 라벨
    node.each(function(d) {
        const el = d3.select(this);
        if (d.type === 'document') {
            el.append('text').text(d.dr_number)
                .attr('dy', -(_r(d) + 16)).attr('text-anchor', 'middle')
                .attr('fill', '#6366f1').attr('font-size', '14px').attr('font-weight', '700')
                .style('pointer-events', 'none');
            el.append('text').text((d.fullTitle || '').slice(0, 25) || '')
                .attr('dy', -(_r(d) + 3)).attr('text-anchor', 'middle')
                .attr('fill', '#475569').attr('font-size', '13px')
                .style('pointer-events', 'none');
        } else {
            let label = d.name || d.id;
            if (d.docCount > 0) label += ` (${d.docCount})`;
            el.append('text').text(label)
                .attr('dy', -(_r(d) + 8)).attr('text-anchor', 'middle')
                .attr('fill', '#1e293b').attr('font-size', d.isCenter ? '17px' : d.level === 0 ? '17px' : d.level === 1 ? '16px' : '15px')
                .attr('font-weight', d.isCenter || d.level === 0 ? '700' : '600')
                .style('pointer-events', 'none');
        }
    });

    // 클릭
    node.on('click', (event, d) => {
        event.stopPropagation();
        if (d.type === 'document') { _openGraphDetail(d.dr_number); return; }
        if (d.isCenter) {
            // 센터(부모) 클릭 → 상위 레벨로 이동
            const newPath = _explorePath.slice(0, -1);
            _navGraph(newPath);
            return;
        }
        // 클릭한 카테고리 ID로 path 생성 후 _navGraph로 이동
        const parts = d.id.split('.');
        const clickPath = [];
        for (let i = 1; i <= parts.length; i++) {
            clickPath.push(parts.slice(0, i).join('.'));
        }
        _navGraph(clickPath);
    });

    node.append('title').text(d => {
        if (d.type === 'document') return `${d.dr_number}\n${d.fullTitle}\n클릭: 요약 보기`;
        if (d.isCenter) return d.name;
        return `${d.name}${d.docCount ? '\n문서 ' + d.docCount + '건' : ''}\n클릭: 하위 보기`;
    });

    node.call(d3.drag()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
    );

    const n = graphNodes.length;
    const isRoot = graphLinks.length === 0; // 대분류 첫 화면 (링크 없음)
    const linkDist = n <= 5 ? 160 : n <= 15 ? 120 : 90;
    const charge = isRoot ? -150 : (n <= 5 ? -600 : n <= 15 ? -350 : -200);

    window._graphSim = d3.forceSimulation(graphNodes);
    const sim = window._graphSim;
    sim
        .force('link', d3.forceLink(graphLinks).id(d => d.id).distance(linkDist).strength(0.7))
        .force('charge', d3.forceManyBody().strength(charge))
        .force('center', d3.forceCenter(width / 2, height / 2).strength(isRoot ? 0.3 : 1))
        .force('collide', d3.forceCollide().radius(d => _r(d) + (isRoot ? 25 : 40)))
        .on('tick', () => {
            link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });

    // 초기 로드 시 대분류를 화면 중앙 원형으로 배치
    if (isInitial && isRoot) {
        const cx = width / 2, cy = height / 2;
        const r = Math.min(cx, cy) * 0.25;
        graphNodes.forEach((n, i) => {
            const angle = (2 * Math.PI * i) / graphNodes.length - Math.PI / 2;
            n.x = cx + r * Math.cos(angle);
            n.y = cy + r * Math.sin(angle);
        });
    }
}

window._navGraph = function(path) {
    console.log('_navGraph called with path:', path);
    let nodes = _exploreCats;
    for (const id of path) {
        const node = nodes.find(n => n.id === id);
        if (!node) break;
        nodes = node.children || [];
    }
    _renderGraphLevel(nodes, path);
};

// ── 문서 상세 패널 ──
async function _openGraphDetail(drNumber) {
    const panel = document.getElementById('graph-detail');
    const titleEl = document.getElementById('graph-detail-title');
    const bodyEl = document.getElementById('graph-detail-body');
    panel.style.display = 'flex';
    titleEl.textContent = drNumber;
    bodyEl.innerHTML = '<div style="color:var(--text-muted)">로딩 중...</div>';

    // 그래프를 남은 공간 기준으로 가운데 재정렬
    setTimeout(() => _recenterGraph(), 100);

    try {
        const res = await fetch(API + '/documents/' + drNumber);
        const data = await res.json();
        const doc = data.document || {};
        const sections = data.sections || [];
        titleEl.textContent = `${drNumber} ${doc.title || ''}`;
        let html = `<div class="graph-detail-meta">${doc.system||''} | ${doc.target_year_month||''}</div>`;
        const docSummary = doc.document_summary || '';
        if (docSummary.trim()) {
            html += `<div class="graph-detail-section"><div class="graph-detail-section-body">${docSummary.replace(/\n/g, '<br>')}</div></div>`;
        } else {
            html += '<div style="color:var(--text-muted)">통합 요약이 없습니다.</div>';
        }
        bodyEl.innerHTML = html;
    } catch (e) { bodyEl.innerHTML = `<div style="color:var(--danger)">조회 실패</div>`; }
}

function _closeGraphDetail() {
    const el = document.getElementById('graph-detail');
    if (el) el.style.display = 'none';
    setTimeout(() => _recenterGraph(), 100);
}

function _recenterGraph() {
    const container = document.getElementById('graph-container');
    if (!container || !window._graphSim) return;
    const rect = container.getBoundingClientRect();
    const newW = rect.width;
    const newH = rect.height;
    const newCx = newW / 2;
    const newCy = newH / 2;

    // SVG 크기 업데이트
    const svg = d3.select(container).select('svg');
    if (svg.empty()) return;
    svg.attr('width', newW).attr('height', newH);

    // 현재 노드들의 중심 계산
    const nodes = window._graphSim.nodes();
    if (!nodes.length) return;
    let sumX = 0, sumY = 0;
    nodes.forEach(n => { sumX += n.x || 0; sumY += n.y || 0; });
    const curCx = sumX / nodes.length;
    const curCy = sumY / nodes.length;

    // 모든 노드를 새 중앙으로 이동
    const dx = newCx - curCx;
    const dy = newCy - curCy;
    nodes.forEach(n => {
        n.x += dx; n.y += dy;
        if (n.fx != null) n.fx += dx;
        if (n.fy != null) n.fy += dy;
    });

    // zoom transform 리셋
    const zoom = d3.zoom().scaleExtent([0.5, 3]);
    svg.call(zoom.transform, d3.zoomIdentity);

    // 시뮬레이션 center force 업데이트
    window._graphSim.force('center', d3.forceCenter(newCx, newCy));
    window._graphSim.alpha(0.1).restart();
}
document.getElementById('graph-detail-close').addEventListener('click', _closeGraphDetail);

// ── DR번호 검색 ──
document.getElementById('btn-dr-search').addEventListener('click', _searchDR);
document.getElementById('dr-search-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') _searchDR();
});

async function _searchDR() {
    _closeGraphDetail();
    const input = document.getElementById('dr-search-input').value.trim();
    const resultEl = document.getElementById('dr-search-result');
    if (!input) {
        resultEl.innerHTML = '';
        _renderGraphLevel(_exploreCats, []);
        return;
    }

    const drMatch = input.match(/DR-\d{4}-\d{4,6}/i);
    const dr = drMatch ? drMatch[0].toUpperCase() : input.toUpperCase();

    try {
        const catRes = await fetch(API + '/documents/' + dr + '/categories');
        const catData = await catRes.json();
        const cats = catData.categories || [];

        if (cats.length === 0) {
            resultEl.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:6px 0;">${dr}: 태깅된 카테고리가 없습니다.</div>`;
            return;
        }

        // 문서 제목 가져오기
        let docTitle = '';
        try {
            const docRes = await fetch(API + '/documents/' + dr);
            const docData = await docRes.json();
            docTitle = docData.document?.title || '';
        } catch (_) {}

        // 모든 카테고리 경로를 그래프에 표시
        const container = document.getElementById('graph-container');
        container.innerHTML = '';
        _renderBreadcrumb([]);

        const graphNodes = [];
        const graphLinks = [];
        const seen = new Set();

        // DR 문서 노드
        const docId = 'doc_' + dr;
        graphNodes.push({ id: docId, type: 'document', dr_number: dr, name: dr, fullTitle: docTitle });
        seen.add(docId);

        // 각 카테고리의 전체 경로 노드 추가
        for (const c of cats) {
            const catParts = c.category_id.split('.');
            let prevId = null;
            for (let i = 1; i <= catParts.length; i++) {
                const cid = catParts.slice(0, i).join('.');
                if (!seen.has(cid)) {
                    seen.add(cid);
                    const catNode = _findNode(_exploreCats, cid);
                    const level = i - 1;
                    graphNodes.push({ id: cid, name: catNode ? catNode.name : cid, type: 'category', level, catNode });
                }
                if (prevId) {
                    const linkKey = prevId + '->' + cid;
                    if (!seen.has(linkKey)) { seen.add(linkKey); graphLinks.push({ source: prevId, target: cid }); }
                }
                prevId = cid;
            }
            // 말단 카테고리 → 문서 링크
            const leafId = c.category_id;
            const linkKey = leafId + '->' + docId;
            if (!seen.has(linkKey)) { seen.add(linkKey); graphLinks.push({ source: leafId, target: docId }); }
        }

        // 트리형 배치 (DR 하단 → 상단으로 대분류)
        const rect = container.getBoundingClientRect();
        const width = rect.width || 800, height = rect.height || 600;
        const svg = d3.select(container).append('svg')
            .attr('width', width).attr('height', height);
        const g = svg.append('g');
        const zoom = d3.zoom().scaleExtent([0.5, 3]).wheelDelta(e => -e.deltaY * 0.002).on('zoom', e => g.attr('transform', e.transform));
        svg.call(zoom);

        // 레벨별 행 계산 (대분류=0이 최상단, DR이 최하단)
        const maxLevel = Math.max(...graphNodes.filter(n => n.type === 'category').map(n => n.level), 0);
        const totalRows = maxLevel + 2; // 카테고리 레벨수 + DR행
        const rowH = height / (totalRows + 1);

        // 레벨별 노드 그룹핑
        const nodesByLevel = {};
        for (const n of graphNodes) {
            const row = n.type === 'document' ? maxLevel + 1 : n.level;
            if (!nodesByLevel[row]) nodesByLevel[row] = [];
            nodesByLevel[row].push(n);
        }

        // 각 레벨에서 가로 균등 배치
        for (const [row, nodes] of Object.entries(nodesByLevel)) {
            const r = parseInt(row);
            const count = nodes.length;
            const spacing = Math.min(200, (width - 100) / (count + 1));
            const startX = (width - spacing * (count - 1)) / 2;
            nodes.forEach((n, i) => {
                n.fx = count === 1 ? width / 2 : startX + spacing * i;
                n.fy = rowH * (r + 1);
            });
        }

        const link = g.append('g').selectAll('line').data(graphLinks).join('line')
            .attr('stroke', '#475569').attr('stroke-width', 2).attr('stroke-opacity', 0.5);

        const node = g.append('g').selectAll('g').data(graphNodes).join('g').attr('cursor', 'pointer');

        function _r(d) { return d.type === 'document' ? 16 : d.level === 0 ? 28 : d.level === 1 ? 22 : 16; }
        function _fill(d) { return d.type === 'document' ? '#a78bfa' : _LEVEL_COLORS[d.level] || '#93c5fd'; }

        node.append('circle').attr('r', _r).attr('fill', _fill)
            .attr('stroke', d => d.type === 'document' ? 'rgba(167,139,250,0.3)' : 'none')
            .attr('stroke-width', d => d.type === 'document' ? 2 : 0);

        node.each(function(d) {
            const el = d3.select(this);
            if (d.type === 'document') {
                el.append('text').text(d.dr_number).attr('dy', -(_r(d) + 16)).attr('text-anchor', 'middle')
                    .attr('fill', '#6366f1').attr('font-size', '14px').attr('font-weight', '700').style('pointer-events', 'none');
                el.append('text').text(d.fullTitle || '').attr('dy', -(_r(d) + 3)).attr('text-anchor', 'middle')
                    .attr('fill', '#475569').attr('font-size', '12px').style('pointer-events', 'none');
            } else {
                el.append('text').text(d.name).attr('dy', -(_r(d) + 8)).attr('text-anchor', 'middle')
                    .attr('fill', '#1e293b').attr('font-size', d.level === 0 ? '17px' : '15px')
                    .attr('font-weight', d.level === 0 ? '700' : '600').style('pointer-events', 'none');
            }
        });

        // 클릭 이벤트: 카테고리 → 드릴다운, DR → 요약보기
        node.on('click', (event, d) => {
            event.stopPropagation();
            if (d.type === 'document') {
                _openGraphDetail(d.dr_number);
            } else {
                // 브레드크럼 클릭과 동일하게 해당 카테고리 레벨로 이동
                const catId = d.id;
                const parts = catId.split('.');
                const path = [];
                for (let i = 1; i <= parts.length; i++) {
                    path.push(parts.slice(0, i).join('.'));
                }
                document.getElementById('dr-search-input').value = '';
                resultEl.innerHTML = '';
                _navGraph(path);
            }
        });

        node.append('title').text(d => {
            if (d.type === 'document') return d.dr_number + '\n' + (d.fullTitle || '') + '\n클릭: 요약 보기';
            return d.name + '\n클릭: 하위 보기';
        });

        window._graphSim = d3.forceSimulation(graphNodes);
    const sim = window._graphSim;
    sim
            .force('link', d3.forceLink(graphLinks).id(d => d.id).distance(rowH * 0.8).strength(1))
            .force('collide', d3.forceCollide().radius(d => _r(d) + 30))
            .on('tick', () => {
                link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                    .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
                node.attr('transform', d => `translate(${d.x},${d.y})`);
            });

        resultEl.innerHTML = `<div style="font-size:14px;color:var(--text-secondary);padding:6px 0;">${dr} — ${docTitle} (카테고리 ${cats.length}개)</div>`;
    } catch (e) {
        resultEl.innerHTML = `<div style="color:var(--danger);font-size:13px;padding:6px 0;">조회 실패: ${e.message}</div>`;
    }
}