/**
 * modules/meteorium/meteorium.js
 * Prexus Intelligence — Meteorium Shell
 * THE GREAT FILE · Phase 2
 */

import { store } from '../../js/store.js';
import { riskHealth, gatewayHealth, getAssets } from '../../js/api.js';
import { startClock, fPct } from '../../js/utils.js';

const MODULE_LOADERS = {
  dashboard: () => import('./dashboard.js'),
  alerts:    () => import('./alerts.js'),
  signals:   () => import('./signals.js'),
  analysis:  () => import('./analysis.js'),
  portfolio: () => import('./portfolio.js'),
  pipeline:  () => import('./pipeline.js'),
  sources:   () => import('./sources.js'),
  ai:        () => import('./ai.js'),
};

const MODULE_META = {
  dashboard: { label: 'Intelligence Overview',  icon: '⬡', section: 'COMMAND'  },
  alerts:    { label: 'Alert Command Center',    icon: '⚠', section: 'COMMAND'  },
  signals:   { label: 'Climate Signals',         icon: '◈', section: 'ANALYSIS' },
  analysis:  { label: 'Risk Analysis',           icon: '◉', section: 'ANALYSIS' },
  portfolio: { label: 'Asset Portfolio',         icon: '≡', section: 'ANALYSIS' },
  pipeline:  { label: 'Pipeline Status',         icon: '⊕', section: 'SYSTEM'   },
  sources:   { label: 'Data Sources',            icon: '◎', section: 'SYSTEM'   },
  ai:        { label: 'AI Intelligence',         icon: '✦', section: 'SYSTEM'   },
};

let _currentModule  = null;
let _currentModId   = '';
let _moduleCache    = {};
let _clockStop      = null;
let _healthInterval = null;

export function initMeteorium(opts = {}) {
  const { onBack, onLogout } = opts;
  _renderShell(onBack, onLogout);
  _startClock();
  _fetchSystemHealth();
  _healthInterval = setInterval(_fetchSystemHealth, 60_000);
  _ensureAssets();
  navigateTo('dashboard');
}

export function destroyMeteorium() {
  if (_clockStop)      { _clockStop();                  _clockStop = null; }
  if (_healthInterval) { clearInterval(_healthInterval); _healthInterval = null; }
  if (_currentModule?.destroy) _currentModule.destroy();
  _currentModule = null;
  _currentModId  = '';
  _moduleCache   = {};
}

function _renderShell(onBack, onLogout) {
  const root = document.getElementById('meteorium-root');
  if (!root) return;
  const user = store.get('user');
  const org  = store.get('org');

  root.innerHTML = `
    <div id="met-shell">
      <div class="met-cls">FOUO // Sensitive But Unclassified // Distribution Authorized</div>
      <div id="met-topbar">
        <div class="met-tb-logo">
          <div style="display:flex;flex-direction:column;gap:1px">
            <span class="met-tb-wordmark">PREXUS</span>
            <span class="met-tb-product">Meteorium v2.0</span>
          </div>
        </div>
        <div class="met-tb-instruments">
          ${_inst('Global Risk','0%','cobalt','met-inst-risk')}
          <div class="met-tb-div"></div>
          ${_inst('Signals','0','cobalt','met-inst-signals')}
          ${_inst('Alerts','0','cobalt','met-inst-alerts')}
          ${_inst('Assets','0','cobalt','met-inst-assets')}
          <div class="met-tb-div"></div>
          ${_inst('Engine','—','dim','met-inst-engine')}
          ${_inst('Queue','—','dim','met-inst-queue')}
        </div>
        <div class="met-tb-right">
          <div>
            <div id="met-clock" class="met-tb-clock">—</div>
            <div id="met-date" class="met-tb-date" style="text-align:right">—</div>
          </div>
          <div class="met-tb-user" id="met-user-btn" title="Back to Hub">
            <div class="met-tb-avatar">⬡</div>
            <div>
              <div style="font-size:9px;color:var(--text-primary);font-family:var(--font-data);letter-spacing:.06em">
                ${(user?.full_name || user?.email || 'USER').toUpperCase().slice(0,14)}
              </div>
              <div style="font-size:7px;color:var(--text-muted);letter-spacing:.1em;text-transform:uppercase">
                ${org?.orgName?.slice(0,18) || 'ORG ADMIN'}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div id="met-main">
        <div id="met-sidebar">
          <div id="met-nav"></div>
          <div class="met-sidebar-bottom">
            <div class="met-sidebar-status">
              <span class="status-dot live pulse"></span>
              <span style="font-size:8px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted)">System Nominal</span>
            </div>
            <div class="met-sidebar-meta"><span>${user?.email?.slice(0,22) || '—'}</span></div>
            <div class="met-sidebar-meta">Role: <span class="role">ORG_ADMIN</span></div>
            <button class="met-btn-signout" id="met-signout-btn">
              <i class="fa-solid fa-right-from-bracket" style="font-size:8px"></i>Sign Out
            </button>
          </div>
        </div>
        <div id="met-workspace">
          <div id="met-workspace-head">
            <span class="met-ws-title" id="met-ws-title">Intelligence Overview</span>
            <div class="met-ws-right">
              <span class="tag tag-cobalt" id="met-ws-tag">DASHBOARD</span>
            </div>
          </div>
          <div id="met-workspace-body"></div>
        </div>
      </div>
    </div>`;

  _renderNav();
  document.getElementById('met-user-btn')?.addEventListener('click', () => { if (onBack) onBack(); });
  document.getElementById('met-signout-btn')?.addEventListener('click', () => { if (onLogout) onLogout(); });
}

function _inst(label, value, cls, id) {
  return `<div class="met-tb-instrument">
    <div class="met-tb-instrument-label">${label}</div>
    <div class="met-tb-instrument-value ${cls}" id="${id}">${value}</div>
  </div>`;
}

function _renderNav() {
  const nav = document.getElementById('met-nav');
  if (!nav) return;
  const sections = ['COMMAND','ANALYSIS','SYSTEM'];
  let html = '';
  for (const sec of sections) {
    const items = Object.entries(MODULE_META).filter(([,m]) => m.section === sec);
    html += `<div class="met-nav-section"><div class="met-nav-section-label">${sec}</div>`;
    for (const [id, meta] of items) {
      const badge = id === 'alerts' ? `<span class="met-nav-badge crit" id="nav-badge-alerts">0</span>` : '';
      html += `<div class="met-nav-item" id="nav-${id}" onclick="window._met.nav('${id}')">
        <span class="met-nav-icon">${meta.icon}</span><span>${meta.label}</span>${badge}
      </div>`;
    }
    html += `</div>`;
  }
  nav.innerHTML = html;
}

export async function navigateTo(modId) {
  if (modId === _currentModId) return;
  if (_currentModule?.destroy) { try { _currentModule.destroy(); } catch {} }
  document.querySelectorAll('.met-nav-item').forEach(el => el.classList.remove('active'));
  document.getElementById(`nav-${modId}`)?.classList.add('active');
  const meta = MODULE_META[modId];
  const titleEl = document.getElementById('met-ws-title');
  const tagEl   = document.getElementById('met-ws-tag');
  if (titleEl) titleEl.textContent = meta?.label || modId;
  if (tagEl)   tagEl.textContent   = modId.toUpperCase();
  const body = document.getElementById('met-workspace-body');
  if (body) body.innerHTML = `<div class="met-view" style="padding:20px;text-align:center;color:var(--text-muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase"><span class="spinner"></span>&nbsp;Loading…</div>`;
  _currentModId = modId;
  try {
    if (!_moduleCache[modId]) {
      const loader = MODULE_LOADERS[modId];
      if (!loader) throw new Error(`No loader: ${modId}`);
      _moduleCache[modId] = await loader();
    }
    _currentModule = _moduleCache[modId];
    if (body) body.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'met-view';
    body?.appendChild(wrapper);
    await _currentModule.init(wrapper);
  } catch (err) {
    console.error(`[Meteorium] Module error (${modId}):`, err);
    if (body) body.innerHTML = `<div class="met-view" style="padding:20px">
      <div style="background:var(--red-lo);border:1px solid rgba(239,68,68,.3);border-radius:4px;padding:14px;font-size:11px;color:var(--red)">
        ⚠ Module failed to load: ${err.message}
      </div></div>`;
  }
}

window._met = { nav: navigateTo };

function _startClock() {
  _clockStop = startClock(({ time, date }) => {
    const c = document.getElementById('met-clock');
    const d = document.getElementById('met-date');
    if (c) c.textContent = time;
    if (d) d.textContent = date;
  });
}

async function _fetchSystemHealth() {
  try {
    const [, rh] = await Promise.allSettled([gatewayHealth(), riskHealth()]);
    if (rh.status === 'fulfilled') {
      const data = rh.value;
      const rust  = data.rust_engine    || false;
      const queue = data.queue?.available || false;
      _setInst('met-inst-engine', rust  ? 'RUST'   : 'PY',     rust  ? 'green' : 'amber');
      _setInst('met-inst-queue',  queue ? 'ONLINE' : 'OFF',    queue ? 'green' : 'amber');
    }
  } catch {}
}

function _setInst(id, value, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
  el.className   = `met-tb-instrument-value ${cls}`;
}

export function updateTopbar({ alertCount, signalCount, portfolioRisk } = {}) {
  if (alertCount !== undefined) {
    _setInst('met-inst-alerts', String(alertCount), alertCount > 0 ? 'red' : 'cobalt');
    const badge = document.getElementById('nav-badge-alerts');
    if (badge) badge.textContent = alertCount;
  }
  if (signalCount !== undefined) _setInst('met-inst-signals', String(signalCount), 'cobalt');
  if (portfolioRisk !== undefined) {
    store.set('portfolioRisk', portfolioRisk);
    const cls = portfolioRisk >= 0.65 ? 'red' : portfolioRisk >= 0.45 ? 'amber' : 'cobalt';
    _setInst('met-inst-risk', fPct(portfolioRisk), cls);
  }
}

async function _ensureAssets() {
  if ((store.get('assets') || []).length === 0) {
    try {
      const assets = await getAssets();
      if (Array.isArray(assets)) { store.set('assets', assets); _setInst('met-inst-assets', String(assets.length), 'cobalt'); }
    } catch {}
  } else {
    _setInst('met-inst-assets', String((store.get('assets') || []).length), 'cobalt');
  }
}

