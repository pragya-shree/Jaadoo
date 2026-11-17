// JAADOO Spaceship Terminal Client

(function () {
    'use strict';

    // -------------------------------------------------------------------------
    // Visitor & Session Identity
    // -------------------------------------------------------------------------
    // Persistent visitor identity (ensures private conversation isolation)
    let visitorId = localStorage.getItem('jaadoo_visitor_id');
    if (!visitorId) {
        visitorId = 'visitor_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9) + Math.random().toString(36).substring(2, 9);
        localStorage.setItem('jaadoo_visitor_id', visitorId);
    }

    // Active conversation ID — survives refresh, switches when user selects another
    let sessionId = localStorage.getItem('jaadoo_session_id');
    if (!sessionId) {
        sessionId = 'earthling_' + Date.now() + '_' + Math.random().toString(36).substring(2, 7);
        localStorage.setItem('jaadoo_session_id', sessionId);
    }

    function authHeaders(extraHeaders = {}) {
        return {
            'X-Visitor-Id': visitorId,
            ...extraHeaders
        };
    }

    // -------------------------------------------------------------------------
    // DOM References
    // -------------------------------------------------------------------------
    const starsContainer = document.getElementById('terminalStars');
    const messagesStream = document.getElementById('messagesStream');
    const composerForm = document.getElementById('composerForm');
    const composerInput = document.getElementById('composerInput');
    const sendBtn = document.getElementById('sendBtn');
    const alienPorthole = document.getElementById('alienPorthole');
    const alienAvatar = document.getElementById('alienAvatar');
    const alienStatusText = document.getElementById('alienStatusText');
    const terminalStatusBadge = document.getElementById('terminalStatusBadge');
    const terminalStatusText = document.getElementById('terminalStatusText');
    const demoStrip = document.getElementById('demoStrip');
    const curiosityBtn = document.getElementById('curiosityBtn');

    const logBadgeCount = document.getElementById('logBadgeCount');
    const memBadgeCount = document.getElementById('memBadgeCount');

    // Drawer (Ship Log)
    const drawerBackdrop = document.getElementById('drawerBackdrop');
    const drawerPanel = document.getElementById('drawerPanel');
    const drawerCloseBtn = document.getElementById('drawerCloseBtn');
    const drawerBody = document.getElementById('drawerBody');
    const drawerTabs = document.querySelectorAll('.drawer-tab');

    // Conversations Sidebar
    const convBackdrop = document.getElementById('convBackdrop');
    const convSidebar = document.getElementById('convSidebar');
    const convCloseBtn = document.getElementById('convCloseBtn');
    const convList = document.getElementById('convList');
    const newConversationBtn = document.getElementById('newConversationBtn');
    const openConversationsBtn = document.getElementById('openConversationsBtn');

    // Delete modal
    const modalBackdrop = document.getElementById('modalBackdrop');
    const modalCancelBtn = document.getElementById('modalCancelBtn');
    const modalConfirmBtn = document.getElementById('modalConfirmBtn');

    let currentDrawerTab = 'diary';
    let isThinking = false;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // -------------------------------------------------------------------------
    // Starfield Atmosphere
    // -------------------------------------------------------------------------
    if (starsContainer) {
        for (let i = 0; i < 75; i++) {
            const s = document.createElement('i');
            s.className = 'star';
            const size = Math.random() * 2 + 1;
            s.style.left = `${Math.random() * 100}%`;
            s.style.top = `${Math.random() * 100}%`;
            s.style.width = `${size}px`;
            s.style.height = `${size}px`;
            s.style.setProperty('--d', `${2.5 + Math.random() * 4}s`);
            s.style.animationDelay = `-${Math.random() * 5}s`;
            starsContainer.appendChild(s);
        }
    }

    // -------------------------------------------------------------------------
    // Utilities
    // -------------------------------------------------------------------------
    function scrollToBottom() {
        if (!messagesStream) return;
        messagesStream.scrollTop = messagesStream.scrollHeight;
    }

    function formatTime(dateOrStr) {
        const d = dateOrStr ? new Date(dateOrStr) : new Date();
        return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
    }

    function formatDate(dateStr) {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        const now = new Date();
        const diffDays = Math.floor((now - d) / 86400000);
        if (diffDays === 0) return 'Today';
        if (diffDays === 1) return 'Yesterday';
        if (diffDays < 7) return d.toLocaleDateString(undefined, { weekday: 'long' });
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }

        function setThinking(thinking) {
            isThinking = thinking;
            if (!alienPorthole || !alienStatusText) return;
            if (thinking) {
                alienPorthole.classList.add('thinking');
                alienStatusText.classList.add('thinking-state');
                alienStatusText.textContent = 'Decoding quantum frequencies...';
                if (sendBtn) sendBtn.disabled = true;
            } else {
                alienPorthole.classList.remove('thinking');
                alienStatusText.classList.remove('thinking-state');
                alienStatusText.textContent = 'Transceiver listening from Sector 7-G';
                if (sendBtn) sendBtn.disabled = false;
            }
        }

        function autoResizeTextarea() {
            if (!composerInput) return;
            composerInput.style.height = 'auto';
            const newHeight = Math.min(composerInput.scrollHeight, 110);
            composerInput.style.height = `${newHeight}px`;
        }

            function escapeHtml(str) {
                const d = document.createElement('div');
                d.textContent = str || '';
                return d.innerHTML;
            }

            // -------------------------------------------------------------------------
            // Message Rendering
            // -------------------------------------------------------------------------
            function appendHumanMessage(text, timestamp) {
                const entry = document.createElement('div');
                entry.className = 'msg-entry user';

                const body = document.createElement('div');
                body.className = 'msg-body';
                body.textContent = text;
                entry.appendChild(body);

            const meta = document.createElement('div');
            meta.className = 'msg-meta-line';
            meta.innerHTML = `<span>You</span><span>•</span><span>${formatTime(timestamp)}</span>`;
            entry.appendChild(meta);

                messagesStream.appendChild(entry);
                scrollToBottom();
                return entry;
            }

            function appendJaadooMessage(text, source, timestamp, onComplete) {
                source = source || 'ai';
                const entry = document.createElement('div');
                entry.className = 'msg-entry assistant';

                const body = document.createElement('div');
                body.className = 'msg-body';
                entry.appendChild(body);

                const meta = document.createElement('div');
                meta.className = 'msg-meta-line';
                let metaHtml = `<span>Jaadoo</span><span>•</span><span>${formatTime(timestamp)}</span>`;
                if (source === 'fallback') {
                    metaHtml += `<span>•</span><span class="fallback-tag">[simulated transmission]</span>`;
                }
                meta.innerHTML = metaHtml;
                entry.appendChild(meta);

                messagesStream.appendChild(entry);
                scrollToBottom();

                // Skip animation for history replays and reduced-motion preference
                if (reducedMotion || timestamp) {
                    body.textContent = text;
                    scrollToBottom();
                    if (onComplete) onComplete();
                    return entry;
                }

                    let idx = 0;
                    const total = text.length;
                    const speed = Math.max(10, Math.min(22, Math.floor(1800 / total)));

                    function tick() {
                        if (idx < total) {
                            const chunk = Math.min(3, total - idx);
                            body.textContent += text.substr(idx, chunk);
                            idx += chunk;
                            scrollToBottom();
                            setTimeout(tick, speed);
                        } else {
                            if (onComplete) onComplete();
                        }
                    }
                    tick();
                    return entry;
                }

                function appendDiscoveryLine(icon, message) {
                    const line = document.createElement('div');
                    line.className = 'stream-discovery';
                    line.innerHTML = `<span>${icon}</span><span>${message}</span>`;
                    messagesStream.appendChild(line);
                    scrollToBottom();
                }

                    // -------------------------------------------------------------------------
                    // Load full conversation history from server
                    // -------------------------------------------------------------------------
                    async function loadConversationHistory(sid) {
                        try {
                            const res = await fetch(`/api/conversations/${encodeURIComponent(sid)}/messages`, {
                                headers: authHeaders()
                            });
                            if (res.status === 404 || res.status === 403) {
                                return false;
                            }
                            if (!res.ok) {
                                throw new Error(`HTTP ${res.status}`);
                            }
                            const messages = await res.json();
                            if (!messages || messages.length === 0) return false;

                                    // Clear placeholder/welcome and render all messages chronologically
                                    messagesStream.innerHTML = '';
                                    for (const msg of messages) {
                                        if (msg.role === 'user') {
                                            appendHumanMessage(msg.content, msg.timestamp);
                                        } else if (msg.role === 'assistant') {
                                            appendJaadooMessage(msg.content, msg.source, msg.timestamp);
                                        }
                                    }
                                    return true;
                                } catch (e) {
                                    console.warn('[Terminal] Could not load conversation history:', e);
                                    messagesStream.innerHTML = `
                <div class="msg-entry assistant">
                    <div class="msg-body">Transmission static detected. Could not restore orbital archives for this frequency. You can continue transmitting below.</div>
                    <div class="msg-meta-line"><span>Sector 7-G Link</span></div>
                </div>`;
                                    return false;
                                }
                            }

                                // -------------------------------------------------------------------------
                                // Switch to a different conversation
                                // -------------------------------------------------------------------------
                                async function switchConversation(newSessionId) {
                                    sessionId = newSessionId;
                                    localStorage.setItem('jaadoo_session_id', sessionId);

        messagesStream.innerHTML = `
                                        < div class="msg-entry assistant" >
                <div class="msg-body">Loading transmission log...</div>
                <div class="msg-meta-line"><span>Sector 7-G Link</span></div>
            </div > `;

                                    const loaded = await loadConversationHistory(sessionId);
                                    if (!loaded) {
                                        messagesStream.innerHTML = `
                <div class="msg-entry assistant">
                    <div class="msg-body">Zorp! Transmission received. My saucer is in high orbit above your quadrant. I have thousands of questions about your species. What do you call yourself, Earthling?</div>
                    <div class="msg-meta-line">
                        <span>Sector 7-G Link</span><span>•</span>
                        <span class="msg-time-stamp">Orbit Time</span>
                    </div>
                </div>`;
                                }

                            closeConvSidebar();
                            updateStatus();
                        }

                        // -------------------------------------------------------------------------
                        // Start a brand-new conversation
                        // -------------------------------------------------------------------------
                        function startNewConversation() {
                            const newId = 'earthling_' + Date.now() + '_' + Math.random().toString(36).substring(2, 7);
                            switchConversation(newId);
                        }

                        // -------------------------------------------------------------------------
                        // Conversations Sidebar (List, Rename, Delete)
                        // -------------------------------------------------------------------------
                        function openConvSidebar() {
                            convBackdrop.classList.add('open');
                            convSidebar.classList.add('open');
                            loadConversationList();
                        }

                        function closeConvSidebar() {
                            convBackdrop.classList.remove('open');
                            convSidebar.classList.remove('open');
                        }

                                async function loadConversationList() {
                                    convList.innerHTML = '<div class="drawer-empty">Scanning transmission log...</div>';
                                    try {
                                        const res = await fetch('/api/conversations', {
                                            headers: authHeaders()
                                        });
                                        if (!res.ok) throw new Error('Failed to fetch conversations');
                                        const conversations = await res.json();

                                        if (!conversations.length) {
                                            convList.innerHTML = '<div class="drawer-empty">No previous transmissions found.</div>';
                                            return;
                                        }

                                            convList.innerHTML = '';
                                            conversations.forEach(conv => {
                                                const isCurrent = (conv.session_id === sessionId);
                                                const item = document.createElement('div');
                                                item.className = 'conv-item' + (isCurrent ? ' conv-item--active' : '');
                                                item.dataset.sessionId = conv.session_id;

                                                const title = conv.title || 'Untitled transmission';
                                                const date = formatDate(conv.last_active);
                                                const count = conv.message_count || 0;

                                                item.innerHTML = `
                    <div class="conv-item-main" title="Open transmission">
                        <div class="conv-item-title">${escapeHtml(title)}</div>
                        <div class="conv-item-meta">${escapeHtml(date)} · ${count} msg${count !== 1 ? 's' : ''}</div>
                    </div>
                    <div class="conv-item-actions">
                        <button class="conv-rename-btn" data-session="${escapeHtml(conv.session_id)}" title="Rename transmission" aria-label="Rename">✎</button>
                        <button class="conv-delete-btn" data-session="${escapeHtml(conv.session_id)}" title="Delete transmission" aria-label="Delete">✕</button>
                    </div>
                `;

                                                // Click on body -> open conversation
                                                item.querySelector('.conv-item-main').addEventListener('click', () => {
                                                    switchConversation(conv.session_id);
                                                });

                                                    // Click on rename -> prompt
                                                    item.querySelector('.conv-rename-btn').addEventListener('click', async (e) => {
                                                        e.stopPropagation();
                                                        const currentTitle = conv.title || '';
                                                        const newTitle = window.prompt('Rename this transmission:', currentTitle);
                                                        if (newTitle && newTitle.trim() && newTitle.trim() !== currentTitle) {
                                                            try {
                                                                const patchRes = await fetch(`/api/conversations/${encodeURIComponent(conv.session_id)}/title`, {
                                                                    method: 'PATCH',
                                                                    headers: authHeaders({ 'Content-Type': 'application/json' }),
                                                                    body: JSON.stringify({ title: newTitle.trim() })
                                                                });
                                                    if (patchRes.ok) {
                                                        loadConversationList();
                                                    }
                                                } catch (err) {
                                                    console.error('[Terminal] Failed to rename transmission:', err);
                                                }
                                            }
                });

                                    // Click on delete -> confirm modal
                                    item.querySelector('.conv-delete-btn').addEventListener('click', (e) => {
                                        e.stopPropagation();
                                        confirmDeleteConversation(conv.session_id, conv.title || 'this transmission');
                                    });

                                    convList.appendChild(item);
                                });
                            } catch (e) {
                                console.error('[Terminal] Failed to load conversations:', e);
                                convList.innerHTML = '<div class="drawer-empty">Could not reach the ship\'s archive. Please check your link.</div>';
                            }
                        }

                        // -------------------------------------------------------------------------
                        // Delete Conversation — with confirmation modal
                        // -------------------------------------------------------------------------
                        let _pendingDeleteId = null;

                        function confirmDeleteConversation(sid, titleText) {
                            _pendingDeleteId = sid;
                            const modalTitle = document.getElementById('modalTitle');
                            if (modalTitle) modalTitle.textContent = `Delete "${titleText}"?`;
                            modalBackdrop.classList.add('open');
                        }

                                function closeModal() {
                                    modalBackdrop.classList.remove('open');
                                    _pendingDeleteId = null;
                                }

                            async function executeDelete() {
                                if (!_pendingDeleteId) return;
                                const sid = _pendingDeleteId;
                                closeModal();
                                try {
                                    const res = await fetch(`/api/conversations/${encodeURIComponent(sid)}`, {
                                        method: 'DELETE',
                                        headers: authHeaders()
                                    });
                                    if (!res.ok) throw new Error('Delete failed');

                                    if (sid === sessionId) {
                                        startNewConversation();
                                    } else {
                                        loadConversationList();
                                    }
                                } catch (e) {
                                    console.error('[Terminal] Failed to delete conversation:', e);
                                }
                            }

                            if (modalCancelBtn) modalCancelBtn.addEventListener('click', closeModal);
                            if (modalConfirmBtn) modalConfirmBtn.addEventListener('click', executeDelete);
                            if (modalBackdrop) {
                                modalBackdrop.addEventListener('click', (e) => {
                                    if (e.target === modalBackdrop) closeModal();
                                });
                            }

                            // -------------------------------------------------------------------------
                            // Keyboard navigation
                            // -------------------------------------------------------------------------
                            window.addEventListener('keydown', (e) => {
                                if (e.key === 'Escape') {
                                    if (modalBackdrop && modalBackdrop.classList.contains('open')) {
                                        closeModal();
                                    } else if (convSidebar && convSidebar.classList.contains('open')) {
                                        closeConvSidebar();
                                    } else if (drawerPanel && drawerPanel.classList.contains('open')) {
                                        closeDrawer();
                                    }
                                }
                            });

                            // -------------------------------------------------------------------------
                            // Input handlers
                            // -------------------------------------------------------------------------
                            if (composerInput) {
                                composerInput.addEventListener('input', autoResizeTextarea);
                                composerInput.addEventListener('keydown', function (e) {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        submitMessage();
                                    }
                                });
                            }

                            if (composerForm) {
                                composerForm.addEventListener('submit', function (e) {
                                    e.preventDefault();
                                    submitMessage();
                                });
                            }

                                    // -------------------------------------------------------------------------
                                    // Status & Badge Counts
                                    // -------------------------------------------------------------------------
                                    async function updateStatus() {
                                        try {
                                            const res = await fetch(`/api/status?session_id=${encodeURIComponent(sessionId)}`, {
                                                headers: authHeaders()
                                            });
                                            if (!res.ok) return;
                                            const data = await res.json();

                                            if (terminalStatusBadge && terminalStatusText) {
                                                if (data.mode === 'live') {
                                                    terminalStatusBadge.classList.remove('demo-state');
                                                    terminalStatusText.textContent = 'Orbit Link Live';
                                                    if (demoStrip) demoStrip.classList.remove('active');
                                                } else {
                                                    terminalStatusBadge.classList.add('demo-state');
                                                    terminalStatusText.textContent = 'Simulation Mode';
                                                    if (demoStrip) demoStrip.classList.add('active');
                                                }
                                            }

                                    if (data.counts) {
                                        const totalLogs = (data.counts.diary_entries || 0) + (data.counts.earth_knowledge || 0);
                                        if (logBadgeCount) logBadgeCount.textContent = totalLogs > 0 ? `(${totalLogs})` : '';
                                        if (memBadgeCount) memBadgeCount.textContent = (data.counts.user_memories || 0) > 0 ? `(${data.counts.user_memories})` : '';
                                    }
                                } catch (e) {
                                    console.warn('[Terminal] Status poll warning:', e);
                                }
                            }

                                // -------------------------------------------------------------------------
                                // Send Message Workflow
                                // -------------------------------------------------------------------------
                                async function submitMessage() {
                                    if (!composerInput || isThinking) return;
                                    const text = composerInput.value.trim();
                                    if (!text) return;

                                    appendHumanMessage(text);
                                    composerInput.value = '';
                                    composerInput.style.height = 'auto';
                                    setThinking(true);

                                        try {
                                            const res = await fetch('/api/chat', {
                                                method: 'POST',
                                                headers: authHeaders({ 'Content-Type': 'application/json' }),
                                                body: JSON.stringify({
                                                    session_id: sessionId,
                                                    message: text,
                                                    user_name: 'Human Friend',
                                                    visitor_id: visitorId
                                                })
                                            });

                                            if (!res.ok) throw new Error(`HTTP ${res.status}`);

                                            const data = await res.json();
                                            setThinking(false);

                                                appendJaadooMessage(data.reply, data.source, null, () => {
                                                    if (data.user_memory) {
                                                        appendDiscoveryLine('✦', `Noted in Memory Core: ${data.user_memory.key}`);
                                                    }
                                                    if (data.earth_knowledge) {
                                                        appendDiscoveryLine('✦', `Decoded in Earth Archive: ${data.earth_knowledge.topic}`);
                                                    }

                                                    if (data.curiosity_question) {
                                                        setTimeout(() => {
                                                            appendJaadooMessage(`${data.curiosity_question}`, data.source);
                                                        }, 600);
                                                    }

                                                updateStatus();
                                            });

        } catch (err) {
                                    console.error('[Terminal] Transmission error:', err);
                                    setThinking(false);
                                    appendJaadooMessage('Zorp! Cosmic interference broke the link. Please retry transmission.', 'fallback');
                                } finally {
                                    composerInput.focus();
                                }
                            }

                                // -------------------------------------------------------------------------
                                // Curiosity Mode
                                // -------------------------------------------------------------------------
                                async function handleCuriosity() {
                                    if (isThinking) return;
                                    setThinking(true);
                                    if (curiosityBtn) curiosityBtn.disabled = true;

                                    try {
                                        const res = await fetch('/api/curiosity', {
                                            headers: authHeaders()
                                        });
                                        if (res.ok) {
                                            const data = await res.json();
                                            setThinking(false);
                                            appendJaadooMessage(`✦ ${data.question}`, 'ai');
                                        } else {
                                            setThinking(false);
                                        }
                                    } catch (e) {
                                        console.warn(e);
                                        setThinking(false);
                                    } finally {
                                        if (curiosityBtn) curiosityBtn.disabled = false;
                                    }
                                }

                                if (curiosityBtn) curiosityBtn.addEventListener('click', handleCuriosity);

                                // -------------------------------------------------------------------------
                                // Ship Log Slide-In Drawer (Diary, Knowledge, Memories)
                                // -------------------------------------------------------------------------
                                function openDrawer(tabName) {
                                    tabName = tabName || 'diary';
                                    currentDrawerTab = tabName;
                                    drawerTabs.forEach(t => {
                                        t.classList.toggle('active', t.getAttribute('data-tab') === tabName);
                                    });
                                    drawerBackdrop.classList.add('open');
                                    drawerPanel.classList.add('open');
                                    loadDrawerContent(tabName);
                                }

                                function closeDrawer() {
                                    drawerBackdrop.classList.remove('open');
                                    drawerPanel.classList.remove('open');
                                }

                                if (drawerCloseBtn) drawerCloseBtn.addEventListener('click', closeDrawer);
                                if (drawerBackdrop) drawerBackdrop.addEventListener('click', closeDrawer);

                                drawerTabs.forEach(tab => {
                                    tab.addEventListener('click', () => {
                                        const tabName = tab.getAttribute('data-tab');
                                        drawerTabs.forEach(t => t.classList.remove('active'));
                                        tab.classList.add('active');
                                        currentDrawerTab = tabName;
                                        loadDrawerContent(tabName);
                                    });
                                });

                                const openLogBtn = document.getElementById('openLogBtn');
                                if (openLogBtn) openLogBtn.addEventListener('click', () => openDrawer('diary'));

                                const openMemoryBtn = document.getElementById('openMemoryBtn');
                                if (openMemoryBtn) openMemoryBtn.addEventListener('click', () => openDrawer('memories'));

                                if (openConversationsBtn) openConversationsBtn.addEventListener('click', openConvSidebar);
                                if (convCloseBtn) convCloseBtn.addEventListener('click', closeConvSidebar);
                                if (convBackdrop) convBackdrop.addEventListener('click', closeConvSidebar);
                                if (newConversationBtn) newConversationBtn.addEventListener('click', startNewConversation);

                                    async function loadDrawerContent(tab) {
                                        if (!drawerBody) return;
                                        drawerBody.innerHTML = '<div class="drawer-empty">Scanning terminal records...</div>';

        if (tab === 'diary') {
            try {
                const res  = await fetch('/api/diary');
                const list = await res.json();
                if (!list.length) {
                    drawerBody.innerHTML = '<div class="drawer-empty">No field notes logged yet. Discuss human customs with Jaadoo to record observations.</div>';
                    return;
                }
                drawerBody.innerHTML = list.map(item => `
                                                    < div class= "log-item" >
                        <div class="log-item-header">
                            <h3 class="log-item-title">${escapeHtml(item.title)}</h3>
                            <span class="log-item-tag">${escapeHtml(item.category)}</span>
                        </div>
                        <p class="log-item-body">${escapeHtml(item.observation)}</p>
                        <div class="log-item-footer">
                            <span>Puzzlement: ${item.confusion_level}/10</span>
                            <span>${new Date(item.created_at).toLocaleDateString()}</span>
                        </div>
                    </div >
                                                    `).join('');
            } catch (e) {
                drawerBody.innerHTML = '<div class="drawer-empty">Failed to read field log.</div>';
            }

        } else if (tab === 'knowledge') {
            try {
                const res  = await fetch('/api/earth-knowledge');
                const list = await res.json();
                if (!list.length) {
                    drawerBody.innerHTML = '<div class="drawer-empty">No concepts recorded yet in the Earth Archive.</div>';
                    return;
                }
                drawerBody.innerHTML = list.map(item => `
                                                    < div class= "log-item" >
                        <div class="log-item-header">
                            <h3 class="log-item-title">${escapeHtml(item.topic)}</h3>
                            <span class="log-item-tag">Reinforced ${item.times_reinforced}x</span>
                        </div>
                        <p class="log-item-body">${escapeHtml(item.alien_understanding)}</p>
                        <div class="log-item-footer">
                            <span>Updated: ${new Date(item.updated_at).toLocaleDateString()}</span>
                        </div>
                    </div >
                                                        `).join('');
            } catch (e) {
                drawerBody.innerHTML = '<div class="drawer-empty">Failed to access Earth Archive.</div>';
            }

        } else if (tab === 'memories') {
            try {
                const res  = await fetch(`/ api / memories ? session_id = ${ encodeURIComponent(sessionId) }`, {
                    headers: authHeaders()
                });
                const list = await res.json();
                if (!list.length) {
                    drawerBody.innerHTML = "<div class=\"drawer-empty\">Jaadoo hasn't recorded any personal facts about you yet. Mention your name, pet, or favorite human food.</div>";
                    return;
                }
                drawerBody.innerHTML = list.map(item => `
                                                < div class= "log-item" id = "mem-entry-${item.id}" >
                        <div class="log-item-header">
                            <h3 class="log-item-title">${escapeHtml(item.key)}</h3>
                            <button class="forget-btn" data-id="${item.id}">Forget</button>
                        </div>
                        <p class="log-item-body">${escapeHtml(item.value)}</p>
                    </div >
                                                    `).join('');

                drawerBody.querySelectorAll('.forget-btn').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const id = btn.getAttribute('data-id');
                        try {
                            const del = await fetch(`/ api / memories / ${ id } ? session_id = ${ encodeURIComponent(sessionId) }`, {
                                method: 'DELETE',
                                headers: authHeaders()
                            });
                            if (del.ok) {
                                loadDrawerContent('memories');
                                updateStatus();
                            }
                        } catch (err) {
                            console.error('Failed to delete memory:', err);
                        }
                    });
                });
            } catch (e) {
                drawerBody.innerHTML = '<div class="drawer-empty">Failed to query Memory Core.</div>';
            }
        }
    }

    // -------------------------------------------------------------------------
    // Initialize
    // -------------------------------------------------------------------------
    async function init() {
        updateStatus();
        await loadConversationHistory(sessionId);
    }

    init();

})();
