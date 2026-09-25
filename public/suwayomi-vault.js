/**
 * Suwayomi Private Vault Extension
 * Intercepts Suwayomi WebUI GraphQL & REST traffic to isolate and protect
 * private manga categories (default category '_').
 * 
 * Default State: LOCKED (Category '_' and its manhwa completely invisible)
 * Unlock Hotkey: Ctrl + Shift + H (or Ctrl + Shift + X)
 * Default Vault PIN: 2507 (customizable)
 */
(function() {
    'use strict';

    // Ensure direct navigation to /manga/:id opens the manga page instead of defaulting to library
    const mangaRouteMatch = window.location.pathname.match(/^\/manga\/(\d+(?:\/.*)?)$/);
    if (mangaRouteMatch) {
        window.location.replace('/manga/manga/' + mangaRouteMatch[1] + window.location.search + window.location.hash);
        return;
    }

    const PRIVATE_CATEGORY_NAMES = new Set(['_', 'private', 'hidden']);
    const STORAGE_KEY_UNLOCKED = 'suwayomi_vault_unlocked';
    const STORAGE_KEY_PIN = 'suwayomi_vault_pin';
    const DEFAULT_PIN = '2507';

    function isVaultUnlocked() {
        return sessionStorage.getItem(STORAGE_KEY_UNLOCKED) === '1';
    }

    function getVaultPin() {
        return localStorage.getItem(STORAGE_KEY_PIN) || DEFAULT_PIN;
    }

    function isPrivateCategory(cat) {
        if (!cat) return false;
        const name = (cat.name || '').trim();
        return PRIVATE_CATEGORY_NAMES.has(name) || name === '_';
    }

    function isPrivateManga(manga) {
        if (!manga) return false;
        const catNodes = manga.categories?.nodes || manga.categories || [];
        if (Array.isArray(catNodes)) {
            return catNodes.some(c => isPrivateCategory(c));
        }
        return false;
    }

    // ─── 1. GraphQL & REST Response Sanitization ───
    function sanitizeGraphQLData(data) {
        if (!data || typeof data !== 'object') return data;

        // A. Filter Category Lists (e.g. GET_CATEGORIES_LIBRARY, GET_CATEGORIES_BASE)
        if (data.categories && Array.isArray(data.categories.nodes)) {
            const originalLength = data.categories.nodes.length;
            data.categories.nodes = data.categories.nodes.filter(c => !isPrivateCategory(c));
            if (typeof data.categories.totalCount === 'number') {
                data.categories.totalCount -= (originalLength - data.categories.nodes.length);
            }
        }

        // B. Filter Single Category Request (e.g. GET_CATEGORY_MANGAS)
        if (data.category) {
            if (isPrivateCategory(data.category)) {
                data.category.mangas = { nodes: [], totalCount: 0, pageInfo: { hasNextPage: false, hasPreviousPage: false } };
            } else if (data.category.mangas && Array.isArray(data.category.mangas.nodes)) {
                data.category.mangas.nodes = data.category.mangas.nodes.filter(m => !isPrivateManga(m));
            }
        }

        // C. Filter Manga Lists (e.g. library search, all manga query)
        if (data.mangas && Array.isArray(data.mangas.nodes)) {
            const originalLength = data.mangas.nodes.length;
            data.mangas.nodes = data.mangas.nodes.filter(m => !isPrivateManga(m));
            if (typeof data.mangas.totalCount === 'number') {
                data.mangas.totalCount -= (originalLength - data.mangas.nodes.length);
            }
        }

        // D. Filter Single Manga Query
        if (data.manga && isPrivateManga(data.manga)) {
            data.manga = null;
        }

        return data;
    }

    // ─── 2. Intercept window.fetch ───
    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
        const response = await originalFetch.apply(this, args);
        if (isVaultUnlocked()) {
            return response;
        }

        try {
            const url = (typeof args[0] === 'string') ? args[0] : (args[0]?.url || '');

            // Handle GraphQL API
            if (url.includes('/api/graphql') || url.includes('/graphql')) {
                const clone = response.clone();
                const json = await clone.json();
                if (json && json.data) {
                    const sanitizedData = sanitizeGraphQLData(json.data);
                    const newBody = JSON.stringify({ ...json, data: sanitizedData });
                    return new Response(newBody, {
                        status: response.status,
                        statusText: response.statusText,
                        headers: response.headers
                    });
                }
            }

            // Handle REST Categories API
            if (url.includes('/api/v1/category')) {
                const clone = response.clone();
                const json = await clone.json();
                if (Array.isArray(json)) {
                    const filtered = json.filter(c => !isPrivateCategory(c));
                    return new Response(JSON.stringify(filtered), {
                        status: response.status,
                        statusText: response.statusText,
                        headers: response.headers
                    });
                }
            }
        } catch (err) {
            // In case of parsing failure, fallback to original response
        }

        return response;
    };

    // ─── 3. DOM & Visual Redaction ───
    function injectStyles() {
        if (document.getElementById('suwayomi-vault-styles')) return;
        const style = document.createElement('style');
        style.id = 'suwayomi-vault-styles';
        style.textContent = `
            /* Stealth hiding of private tab */
            body:not(.vault-unlocked) button[role="tab"][data-category-name="_"],
            body:not(.vault-unlocked) button[role="tab"][data-category-name="private"],
            body:not(.vault-unlocked) button[role="tab"][data-category-name="hidden"] {
                display: none !important;
            }

            /* Unlocked floating status indicator */
            #suwayomi-vault-indicator {
                position: fixed;
                bottom: 18px;
                right: 18px;
                background: rgba(22, 101, 52, 0.88);
                color: #86efac;
                border: 1px solid rgba(134, 239, 172, 0.35);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                padding: 6px 14px;
                border-radius: 20px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 12px;
                font-weight: 600;
                box-shadow: 0 4px 16px rgba(0,0,0,0.4);
                cursor: pointer;
                z-index: 999999;
                display: flex;
                align-items: center;
                gap: 6px;
                transition: all 0.2s ease;
                user-select: none;
            }
            #suwayomi-vault-indicator:hover {
                background: rgba(185, 28, 28, 0.88);
                color: #fca5a5;
                border-color: rgba(252, 165, 165, 0.35);
                transform: scale(1.03);
            }

            /* Vault Unlock Modal */
            #suwayomi-vault-modal-backdrop {
                position: fixed;
                top: 0; left: 0; width: 100vw; height: 100vh;
                background: rgba(0,0,0,0.72);
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 1000000;
            }
            #suwayomi-vault-modal {
                background: #18181b;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 14px;
                padding: 24px;
                width: 90%;
                max-width: 360px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.6);
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                color: #f4f4f5;
            }
            #suwayomi-vault-modal h3 {
                margin: 0 0 8px;
                font-size: 1.15rem;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            #suwayomi-vault-modal p {
                margin: 0 0 16px;
                font-size: 0.85rem;
                color: #a1a1aa;
                line-height: 1.4;
            }
            #suwayomi-vault-pin-input {
                width: 100%;
                padding: 10px 14px;
                background: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                color: #fff;
                font-size: 1rem;
                outline: none;
                box-sizing: border-box;
                margin-bottom: 16px;
                text-align: center;
                letter-spacing: 2px;
            }
            #suwayomi-vault-pin-input:focus {
                border-color: #6366f1;
                box-shadow: 0 0 0 2px rgba(99,102,241,0.25);
            }
            .suwayomi-vault-btn-row {
                display: flex;
                gap: 10px;
                justify-content: flex-end;
            }
            .suwayomi-vault-btn {
                padding: 8px 16px;
                border-radius: 8px;
                font-size: 0.85rem;
                font-weight: 600;
                cursor: pointer;
                border: none;
                transition: background 0.15s ease;
            }
            .suwayomi-vault-btn-sec {
                background: #27272a;
                color: #d4d4d8;
            }
            .suwayomi-vault-btn-sec:hover {
                background: #3f3f46;
            }
            .suwayomi-vault-btn-pri {
                background: #6366f1;
                color: #fff;
            }
            .suwayomi-vault-btn-pri:hover {
                background: #4f46e5;
            }
        `;
        document.head.appendChild(style);

        if (isVaultUnlocked()) {
            document.body.classList.add('vault-unlocked');
        }
    }

    // Hide any tabs with text '_' via MutationObserver when locked
    function setupMutationObserver() {
        if (isVaultUnlocked()) return;

        function scanTabs() {
            if (isVaultUnlocked()) return;
            const tabs = document.querySelectorAll('button[role="tab"]');
            tabs.forEach(tab => {
                const text = tab.textContent.trim().toLowerCase();
                if (text === '_' || text === 'private' || text === 'hidden') {
                    tab.style.display = 'none';
                    tab.setAttribute('data-category-name', text);
                }
            });
        }

        scanTabs();
        const observer = new MutationObserver(scanTabs);

        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                scanTabs();
                observer.observe(document.body, { childList: true, subtree: true });
            });
        }
    }

    // ─── 4. Modal and Indicator UI ───
    function showVaultModal() {
        if (document.getElementById('suwayomi-vault-modal-backdrop')) return;

        const backdrop = document.createElement('div');
        backdrop.id = 'suwayomi-vault-modal-backdrop';
        backdrop.onclick = (e) => {
            if (e.target === backdrop) backdrop.remove();
        };

        const modal = document.createElement('div');
        modal.id = 'suwayomi-vault-modal';

        modal.innerHTML = `
            <h3>🔐 Private Manga Vault</h3>
            <p>Enter your vault passcode to decrypt and display private collections.</p>
            <input type="password" id="suwayomi-vault-pin-input" placeholder="Passcode (default: 2507)" autocomplete="off" />
            <div id="suwayomi-vault-error" style="color: #f87171; font-size: 0.8rem; margin-bottom: 12px; display: none;">Invalid passcode</div>
            <div class="suwayomi-vault-btn-row">
                <button type="button" class="suwayomi-vault-btn suwayomi-vault-btn-sec" id="suwayomi-vault-cancel">Cancel</button>
                <button type="button" class="suwayomi-vault-btn suwayomi-vault-btn-pri" id="suwayomi-vault-submit">Unlock</button>
            </div>
        `;

        backdrop.appendChild(modal);
        document.body.appendChild(backdrop);

        const input = document.getElementById('suwayomi-vault-pin-input');
        const submitBtn = document.getElementById('suwayomi-vault-submit');
        const cancelBtn = document.getElementById('suwayomi-vault-cancel');
        const errEl = document.getElementById('suwayomi-vault-error');

        input.focus();

        const submit = () => {
            const entered = input.value;
            const correct = getVaultPin();
            if (entered === correct) {
                sessionStorage.setItem(STORAGE_KEY_UNLOCKED, '1');
                backdrop.remove();
                location.reload();
            } else {
                errEl.style.display = 'block';
                input.value = '';
                input.focus();
            }
        };

        submitBtn.onclick = submit;
        cancelBtn.onclick = () => backdrop.remove();
        input.onkeydown = (e) => {
            if (e.key === 'Enter') submit();
            if (e.key === 'Escape') backdrop.remove();
        };
    }

    function lockVault() {
        sessionStorage.removeItem(STORAGE_KEY_UNLOCKED);
        location.reload();
    }

    function renderIndicator() {
        if (!isVaultUnlocked()) return;
        if (document.getElementById('suwayomi-vault-indicator')) return;

        const el = document.createElement('div');
        el.id = 'suwayomi-vault-indicator';
        el.title = 'Click to lock private vault and hide category _';
        el.innerHTML = `<span>🔓</span><span>Private Vault Active</span>`;
        el.onclick = () => {
            if (confirm('Lock private manga vault and hide category _?')) {
                lockVault();
            }
        };
        document.body.appendChild(el);
    }

    // ─── 5. Hotkey & Drawer Listeners ───
    window.addEventListener('keydown', (e) => {
        // Ctrl + Shift + H or Ctrl + Shift + X
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'H' || e.key === 'h' || e.key === 'X' || e.key === 'x')) {
            e.preventDefault();
            if (isVaultUnlocked()) {
                if (confirm('Lock private vault and hide category _?')) {
                    lockVault();
                }
            } else {
                showVaultModal();
            }
        }
    });

    // ─── 6. Automated SyncYomi Sync Triggers: Tab Open, Reload, Visibility & Close ───
    (function setupSyncTriggers() {
        const SYNC_MUTATION = JSON.stringify({ query: "mutation { startSync(input: {}) { clientMutationId } }" });
        let lastSyncTime = 0;
        const COOLDOWN_MS = 10000;

        function triggerSync(force) {
            const now = Date.now();
            if (!force && (now - lastSyncTime < COOLDOWN_MS)) return;
            lastSyncTime = now;

            // 1. Dashboard server-side endpoint (handles server-side debounce and auth)
            try {
                if (navigator.sendBeacon) {
                    navigator.sendBeacon('/api/suwayomi/sync');
                } else {
                    fetch('/api/suwayomi/sync', { method: 'POST', keepalive: true }).catch(() => {});
                }
            } catch (e) {}

            // 2. Direct GraphQL mutation with credentials
            try {
                fetch('/manga/api/graphql', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: SYNC_MUTATION,
                    credentials: 'include',
                    keepalive: true
                }).catch(() => {});
            } catch (e) {}
        }

        // A. Trigger immediately on page load / bfcache restore
        window.addEventListener('load', () => triggerSync(true));
        window.addEventListener('pageshow', () => triggerSync(true));

        // B. Trigger when switching tabs or backgrounding app
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'hidden') {
                triggerSync(false);
            }
        });

        // C. Trigger on tab close / navigation away / reload initiation
        window.addEventListener('pagehide', () => triggerSync(true));
        window.addEventListener('beforeunload', () => triggerSync(true));
    })();

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            injectStyles();
            setupMutationObserver();
            renderIndicator();
        });
    } else {
        injectStyles();
        setupMutationObserver();
        renderIndicator();
    }
})();
