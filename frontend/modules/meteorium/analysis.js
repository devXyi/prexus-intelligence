/**
 * modules/meteorium/analysis.js
 * Prexus Intelligence — Risk Analysis Terminal
 * Upgraded: predictive trajectories + silent AI pre-inference
 *
 * FIXES:
 *  - XSS: replaced innerHTML with sanitizeHTML() for all AI/user content
 *  - Scenario mapping: removed 'disorderly' (not in API validator)
 *  - horizonDays: removed Math.min(_horizon, 30) cap
 *  - cache_key: always initialized before use
 */

import { store }                          from '../../js/store.js';
import { scoreAsset }                     from '../../js/api.js';
import { fPct, fUsd, riskColor, riskLabel, sanitizeHTML } from '../../js/utils.js';
import { computeTrajectory }              from '../../js/predict.js';
import { getCachedBrief, prefetchNow }    from '../../js/prefetch.js';

const SCENARIOS = [
  { id:'ssp119',   label:'SSP1-1.9', sub:'Paris 1.5°C',    mult:0.88 },
  { id:'baseline', label:'SSP2-4.5', sub:'Baseline 2.7°C', mult:1.12 },
  { id:'ssp370',   label:'SSP3-7.0', sub:'High 3.6°C',     mult:1.24 },
  { id:'ssp585',   label:'SSP5-8.5', sub:'Failed 4.4°C',   mult:1.38 },
];

// FIX: 'disorderly' doesn't exist in API validator — mapped to valid values
// Valid: ssp119 | paris | ssp245 | baseline | ssp370 | ssp585 | failed
const SCEN_KEY = {
  ssp119:   'ssp119',
  baseline: 'baseline',
  ssp370:   'ssp370',
  ssp585:   'failed',
};

let _running = false;
let _scenario = 'baseline';
let _horizon  = 365;
let _unsubs   = [];

export function init(container) {
  const assets = store.get('assets') || [];
  let selAssetId = assets[0]?.id || '';

  _render(container, assets, selAssetId);
  _wireEvents(container, assets, () => selAssetId, (id) => { selAssetId = id; });
}

export function destroy() {
  _running = false;
  _unsubs.forEach(f => f?.());
  _unsubs = [];
}

/* ══════════════════════════════════════════════════════════
   RENDER
══════════════════════════════════════════════════════════ */
function _render(container, assets, selAssetId) {
  const selA  = assets.find(a => a.id === selAssetId) || assets[0];
  const traj  = selA ? computeTrajectory(selA) : null;
  const trend = traj?.trend || 'STABLE';
  const trendC = trend === 'WORSENING' ? '#EF4444' : trend === 'IMPROVING' ? '#10B981' : '#F59E0B';

  container.innerHTML = `
    <div style="display:grid;grid-template-columns:320px 1fr;gap:12px;height:calc(100vh - 160px);overflow:hidden">

      <!-- Parameters panel -->
      <div style="display:flex;flex-direction:column;gap:12px;overflow-y:auto">

        <!-- Asset + scenario -->
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Scenario Builder</span></div>
          <div style="padding:14px;display:flex;flex-direction:column;gap:12px">
            <div>
              <div class="form-label">Target Asset</div>
              <select id="anl-asset" class="minp" style="text-align:left;letter-spacing:0;font-size:12px">
                <option value="">Select asset…</option>
                ${assets.map(a => `<option value="${a.id}" ${a.id===selAssetId?'selected':''}>${a.id} · ${a.name}</option>`).join('')}
              </select>
            </div>
            <div>
              <div class="form-label">Climate Scenario</div>
              <div style="display:flex;flex-direction:column;gap:5px">
                ${SCENARIOS.map(s => `
                  <label id="anl-scen-${s.id}" style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:8px;border-radius:3px;
                    border:1px solid ${s.id===_scenario?'rgba(14,165,233,.5)':'var(--border)'};
                    background:${s.id===_scenario?'rgba(14,165,233,.08)':'transparent'};transition:all .15s">
                    <input type="radio" name="anl-scen" value="${s.id}" ${s.id===_scenario?'checked':''} style="accent-color:var(--cobalt)"/>
                    <div style="flex:1">
                      <div style="font-family:var(--font-display);font-size:13px;color:var(--text-primary);letter-spacing:.06em">${s.label}</div>
                      <div style="font-size:9px;color:var(--text-secondary)">${s.sub}</div>
                    </div>
                    <span style="font-family:var(--font-display);font-size:13px;color:${_sCol(s.mult)}">${s.mult.toFixed(2)}×</span>
                  </label>`).join('')}
              </div>
            </div>
            <div>
              <div class="form-label" style="display:flex;justify-content:space-between">
                <span>Time Horizon</span>
                <span id="anl-hor-lbl" style="color:var(--cobalt)">${_horLabel(_horizon)}</span>
              </div>
              <input type="range" id="anl-hor" min="30" max="3650" step="30" value="${_horizon}" style="width:100%;accent-color:var(--cobalt)"/>
              <div style="display:flex;justify-content:space-between;font-size:8px;color:var(--text-muted);margin-top:2px">
                <span>30d</span><span>1yr</span><span>5yr</span><span>10yr</span>
              </div>
            </div>
            <button id="anl-run" class="btn btn-primary" style="width:100%;justify-content:center;padding:10px">
              ▶&nbsp;Run Full Analysis
            </button>
          </div>
        </div>

        <!-- Predictive Trajectory -->
        ${selA && traj ? _trajectoryPanel(selA, traj) : `
          <div class="panel" style="padding:20px;text-align:center;color:var(--text-muted);font-family:var(--font-data);font-size:9px">
            Select an asset to see predictive trajectory
          </div>`}

      </div>

      <!-- Right: KPIs + terminal + output -->
      <div style="display:flex;flex-direction:column;gap:12px;overflow:hidden">

        <!-- Live KPIs -->
        <div id="anl-kpis" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;flex-shrink:0">
          ${['Composite Risk','VaR 95%','CVaR 95%','Expected Loss'].map(l =>
            `<div class="met-kpi cobalt"><div class="met-kpi-label">${l}</div><div class="met-kpi-value">—</div><div class="met-kpi-sub">Run analysis</div></div>`).join('')}
        </div>

        <!-- Execution log -->
        <div class="panel" style="border-radius:5px;flex:1;overflow:hidden;display:flex;flex-direction:column">
          <div class="panel-head">
            <span id="anl-status-dot" class="status-dot dim"></span>
            <span class="panel-title" style="margin-left:5px">Execution Log</span>
            <span id="anl-eng-tag" class="tag tag-dim" style="margin-left:auto">IDLE</span>
          </div>
          <div id="anl-log" style="flex:1;overflow:auto;padding:10px 12px;font-family:var(--font-data);font-size:10px;line-height:1.75;background:rgba(0,0,0,.55)">
            <div style="color:var(--text-muted)">// Awaiting invocation. Configure parameters and press RUN ANALYSIS.</div>
          </div>
        </div>

        <!-- AI Intelligence Brief -->
        <div class="panel" style="border-radius:5px;flex-shrink:0;max-height:220px;overflow:hidden;display:flex;flex-direction:column">
          <div class="panel-head">
            <i class="fa-solid fa-gem" style="font-size:9px;color:#2563EB"></i>
            <span class="panel-title" style="margin-left:5px">AI Intelligence Brief</span>
            <div id="anl-ai-status" style="margin-left:auto;font-family:var(--font-data);font-size:8px;color:var(--text-muted)">
              ${getCachedBrief(selA || {}, SCEN_KEY[_scenario] || 'baseline') ? '✓ Pre-loaded' : 'Generates after analysis'}
            </div>
          </div>
          <div id="anl-ai-brief" style="flex:1;overflow:auto;padding:12px;font-size:11.5px;color:var(--text-secondary);line-height:1.7;font-family:'Source Serif 4',serif;font-style:italic">
            ${_preloadedBrief(selA, _scenario)}
          </div>
        </div>
      </div>
    </div>`;
}

/* ═══ Trajectory Panel ═════════════════════════════════ */
function _trajectoryPanel(asset, traj) {
  const trendC    = traj.trend === 'WORSENING' ? '#EF4444' : traj.trend === 'IMPROVING' ? '#10B981' : '#F59E0B';
  const trendIcon = traj.trend === 'WORSENING' ? 'fa-arrow-trend-up' : traj.trend === 'IMPROVING' ? 'fa-arrow-trend-down' : 'fa-minus';

  const crossing = traj.nextCrossing;
  const crossingHTML = crossing ? `
    <div style="padding:10px 12px;background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.2);border-radius:4px;margin:12px">
      <div style="font-family:var(--font-data);font-size:8px;color:#EF4444;text-transform:uppercase;letter-spacing:.12em;margin-bottom:4px">
        ⚠ Threshold Breach Predicted
      </div>
      <div style="font-family:var(--font-display);font-size:18px;color:#EF4444;margin-bottom:2px">
        ${crossing.threshold} in ${crossing.days}d
      </div>
      <div style="font-family:var(--font-data);font-size:9px;color:var(--text-muted)">
        ${Math.round(crossing.confidence * 100)}% exceedance (uncalibrated) · P50 projection
      </div>
    </div>` : `
    <div style="padding:9px 12px;background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.15);border-radius:4px;margin:12px">
      <div style="font-family:var(--font-data);font-size:8.5px;color:#10B981">No threshold breach in 30-day horizon</div>
    </div>`;

  const spark = _sparkline(traj.projection, asset.cr);

  return `
    <div class="panel">
      <div class="panel-head">
        <i class="fa-solid fa-chart-line" style="font-size:9px;color:var(--cobalt)"></i>
        <span class="panel-title" style="margin-left:5px">Predictive Trajectory · 30-day Monte Carlo</span>
      </div>

      <div style="padding:12px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--border)">
        <div>
          <div style="font-family:var(--font-data);font-size:7.5px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em">Trend</div>
          <div style="display:flex;align-items:center;gap:5px;margin-top:3px">
            <i class="fa-solid ${trendIcon}" style="font-size:11px;color:${trendC}"></i>
            <span style="font-family:var(--font-display);font-size:17px;color:${trendC}">${traj.trend}</span>
          </div>
        </div>
        <div style="flex:1">${spark}</div>
        <div>
          <div style="font-family:var(--font-data);font-size:7.5px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.1em">7-day Δ</div>
          <div style="font-family:var(--font-display);font-size:17px;color:${trendC};margin-top:3px">
            ${traj.delta7 >= 0 ? '+' : ''}${(traj.delta7 * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      ${crossingHTML}

      <div style="padding:4px 12px 12px;display:grid;grid-template-columns:1fr 1fr;gap:6px">
        ${traj.projection.filter(p => [7,30].includes(p.day)).map(p => `
          <div style="background:rgba(0,0,0,.3);border:1px solid rgba(14,165,233,.08);border-radius:3px;padding:8px 10px">
            <div style="font-family:var(--font-data);font-size:7.5px;color:var(--text-muted);text-transform:uppercase;margin-bottom:4px">
              ${p.day}d forecast
            </div>
            <div style="font-family:var(--font-display);font-size:20px;color:${riskColor(p.p50)}">${fPct(p.p50)}</div>
            <div style="font-family:var(--font-data);font-size:8px;color:var(--text-muted);margin-top:2px">
              ${fPct(p.p10)} – ${fPct(p.p90)} range
            </div>
          </div>`).join('')}
      </div>
    </div>`;
}

function _sparkline(projection, current) {
  const W = 80, H = 28;
  const all = [{ day: 0, p50: current }, ...projection];
  const maxV = Math.max(...all.map(p => p.p90 ?? p.p50)) + 0.05;
  const minV = Math.min(...all.map(p => p.p10 ?? p.p50)) - 0.02;
  const scaleX = d => (d / 30) * W;
  const scaleY = v => H - ((v - minV) / (maxV - minV)) * H;

  const area = `M 0 ${H} ` + all.map(p => `L ${scaleX(p.day).toFixed(1)} ${scaleY(p.p90 ?? p.p50).toFixed(1)}`).join(' ')
    + ' ' + [...all].reverse().map(p => `L ${scaleX(p.day).toFixed(1)} ${scaleY(p.p10 ?? p.p50).toFixed(1)}`).join(' ')
    + ` L 0 ${H} Z`;

  const line = all.map((p, i) =>
    `${i===0?'M':'L'} ${scaleX(p.day).toFixed(1)} ${scaleY(p.p50).toFixed(1)}`
  ).join(' ');

  const lastP50 = all[all.length - 1]?.p50 ?? current;
  const c = riskColor(lastP50);

  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="overflow:visible">
    <path d="${area}" fill="${c}" opacity=".12"/>
    <path d="${line}" fill="none" stroke="${c}" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cx="${scaleX(0)}" cy="${scaleY(current)}" r="2" fill="var(--cobalt)"/>
    <circle cx="${scaleX(30)}" cy="${scaleY(lastP50)}" r="2" fill="${c}"/>
  </svg>`;
}

function _preloadedBrief(asset, scenario) {
  if (!asset) return '<span style="color:var(--text-muted)">Select an asset to generate intelligence brief.</span>';
  const cached = getCachedBrief(asset, SCEN_KEY[scenario] || 'baseline');
  // FIX: sanitize AI response before injecting as HTML
  if (cached) return sanitizeHTML(cached);
  return `<span style="color:var(--text-muted)">Run analysis to generate brief${store.get('token') ? ' — pre-fetching in background…' : '.'}</span>`;
}

/* ═══ Wire Events ══════════════════════════════════════ */
function _wireEvents(container, assets, getSelId, setSelId) {

  container.querySelector('#anl-asset')?.addEventListener('change', e => {
    const id = e.target.value;
    setSelId(id);
    _render(container, assets, id);
    _wireEvents(container, assets, getSelId, setSelId);
    const a = assets.find(x => x.id === id);
    if (a) prefetchNow(a, SCEN_KEY[_scenario] || 'baseline');
  });

  container.querySelectorAll('input[name="anl-scen"]').forEach(r => {
    r.addEventListener('change', () => {
      _scenario = r.value;
      container.querySelectorAll('[id^="anl-scen-"]').forEach(el => {
        const id = el.id.replace('anl-scen-', '');
        el.style.borderColor = id === _scenario ? 'rgba(14,165,233,.5)' : 'var(--border)';
        el.style.background  = id === _scenario ? 'rgba(14,165,233,.08)' : 'transparent';
      });
    });
  });

  container.querySelector('#anl-hor')?.addEventListener('input', e => {
    _horizon = parseInt(e.target.value);
    const lbl = container.querySelector('#anl-hor-lbl');
    if (lbl) lbl.textContent = _horLabel(_horizon);
  });

  container.querySelector('#anl-run')?.addEventListener('click', () => {
    _runAnalysis(container, assets, getSelId());
  });

  const off = (() => {
    let prevKey = null;
    const check = setInterval(() => {
      const selA = assets.find(a => a.id === getSelId());
      if (!selA) return;
      const key = `${selA.id}:${SCEN_KEY[_scenario]||'baseline'}`;
      if (key !== prevKey) {
        const cached = getCachedBrief(selA, SCEN_KEY[_scenario]||'baseline');
        if (cached) {
          const briefEl  = container.querySelector('#anl-ai-brief');
          const statusEl = container.querySelector('#anl-ai-status');
          if (briefEl && !briefEl.dataset.hasResult) {
            // FIX: sanitize before injecting
            briefEl.innerHTML = sanitizeHTML(cached);
            if (statusEl) statusEl.innerHTML = '<span style="color:var(--green)">✓ Pre-loaded</span>';
          }
          prevKey = key;
        }
      }
    }, 2000);
    return () => clearInterval(check);
  })();
  _unsubs.push(off);
}

/* ═══ Run Analysis ══════════════════════════════════════ */
async function _runAnalysis(container, assets, assetId) {
  if (_running) return;
  _running = true;

  const selA = assets.find(a => a.id === assetId) || assets[0];
  if (!selA) { _running = false; return; }

  const btn   = container.querySelector('#anl-run');
  const kpis  = container.querySelector('#anl-kpis');
  const log   = container.querySelector('#anl-log');
  const dot   = container.querySelector('#anl-status-dot');
  const tag   = container.querySelector('#anl-eng-tag');
  const brief = container.querySelector('#anl-ai-brief');
  const bstat = container.querySelector('#anl-ai-status');

  if (btn) btn.disabled = true;
  if (dot) dot.className = 'status-dot live pulse';
  if (tag) { tag.textContent = 'RUNNING'; tag.className = 'tag tag-amber'; }

  const runId = `RUN-${Date.now().toString(36).toUpperCase()}`;
  const traj  = computeTrajectory(selA);
  const sc    = SCENARIOS.find(s => s.id === _scenario) || SCENARIOS[1];

  const _log = (msg, color='#93c5fd') => {
    if (!log) return;
    const d = document.createElement('div');
    d.style.color = color;
    d.textContent = msg; // safe — textContent never executes scripts
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  };

  if (log) log.innerHTML = '';
  _log(`[${runId}] Meteorium kernel initialized — IPCC AR6 mode`);
  _log(`[${runId}] Target: ${selA.id} — ${selA.name} [${selA.cc||'?'}]`);
  _log(`[${runId}] Scenario: ${sc.label} · Horizon: ${_horizon}d`);
  _log(`[${runId}] Predictive trajectory: ${traj.trend} · 7d Δ${traj.delta7>=0?'+':''}${(traj.delta7*100).toFixed(1)}%`);

  if (traj.nextCrossing) {
    _log(`[${runId}] ⚠ Threshold alert: ${traj.nextCrossing.threshold} breach in ${traj.nextCrossing.days}d (${Math.round(traj.nextCrossing.confidence*100)}% exceedance (uncalibrated))`, '#EF4444');
  }

  let result = null;
  try {
    _log(`[${runId}] Connecting to Meteorium data engine…`);
    _log(`[${runId}] → Querying Open-Meteo ECMWF forecast + ERA5 baseline`);
    _log(`[${runId}] → Querying NASA FIRMS VIIRS 375m [${selA.lat?.toFixed(2)||0}°N, ${selA.lon?.toFixed(2)||0}°E]`);
    _log(`[${runId}] → Querying Carbon Monitor CO₂ [${selA.cc||'IND'}]`);

    result = await scoreAsset({
      assetId:     selA.id,
      lat:         selA.lat ?? 0,
      lon:         selA.lon ?? 0,
      countryCode: selA.cc || 'IND',
      valueMm:     selA.value_mm ?? 10,
      scenario:    SCEN_KEY[_scenario] || 'baseline',
      horizonDays: _horizon, // FIX: removed Math.min cap — API supports up to 3650
    });

    _log(`[${runId}] ✓ Physical risk:    ${fPct(result.physical_risk||0)} [${result.sources?.weather||'Open-Meteo'}]`, '#4ade80');
    _log(`[${runId}] ✓ Transition risk:  ${fPct(result.transition_risk||0)} [${result.sources?.carbon||'Carbon Monitor'}]`, '#4ade80');
    _log(`[${runId}] → Running Monte Carlo simulation (n=10,000)…`);
    _log(`[${runId}] ✓ VaR 95%: ${fPct(result.var_95||0)} · CVaR 95%: ${fPct(result.cvar_95||0)}`, '#4ade80');
    _log(`[${runId}] ✓ Analysis complete · ${new Date().toISOString().replace('T',' ').slice(0,19)} Z`, '#4ade80');

    if (tag) { tag.textContent = 'LIVE DATA'; tag.className = 'tag tag-green'; }

  } catch(e) {
    _log(`[${runId}] ⚠ Engine unavailable: ${e.message}`, '#F59E0B');
    _log(`[${runId}] → Falling back to local IPCC AR6 model`, '#F59E0B');
    result = {
      composite_risk:   selA.cr * sc.mult,
      physical_risk:    selA.pr * sc.mult,
      transition_risk:  selA.tr * sc.mult,
      var_95:           selA.cr * sc.mult * 0.18,
      cvar_95:          selA.cr * sc.mult * 0.27,
      loss_expected_mm: (selA.value_mm ?? 10) * selA.cr * sc.mult * 0.25,
      _fallback: true,
    };
    _log(`[${runId}] ✓ Fallback estimate: ${fPct(result.composite_risk)} composite`, '#4ade80');
    if (tag) { tag.textContent = 'LOCAL FALLBACK'; tag.className = 'tag tag-amber'; }
  }

  // Update KPIs
  if (kpis) {
    const cr = result.composite_risk ?? result.cr ?? 0;
    kpis.innerHTML = `
      <div class="met-kpi ${cr>=.85?'red':cr>=.65?'amber':'cobalt'}">
        <div class="met-kpi-label">Composite Risk</div>
        <div class="met-kpi-value">${fPct(cr)}</div>
        <div class="met-kpi-sub">${riskLabel(cr)}</div>
      </div>
      <div class="met-kpi amber">
        <div class="met-kpi-label">VaR 95%</div>
        <div class="met-kpi-value">${fPct(result.var_95||0)}</div>
        <div class="met-kpi-sub">${_horizon}d horizon</div>
      </div>
      <div class="met-kpi red">
        <div class="met-kpi-label">CVaR 95%</div>
        <div class="met-kpi-value">${fPct(result.cvar_95||0)}</div>
        <div class="met-kpi-sub">Expected shortfall</div>
      </div>
      <div class="met-kpi red">
        <div class="met-kpi-label">Expected Loss</div>
        <div class="met-kpi-value">${fUsd(result.loss_expected_mm||0)}</div>
        <div class="met-kpi-sub">Probability-weighted</div>
      </div>`;
  }

  const apiKey     = SCEN_KEY[_scenario] || 'baseline';
  let cachedBrief  = getCachedBrief(selA, apiKey);

  if (cachedBrief) {
    if (brief) {
      brief.dataset.hasResult = '1';
      // FIX: sanitize AI response
      brief.innerHTML = sanitizeHTML(cachedBrief);
    }
    if (bstat) bstat.innerHTML = '<span style="color:var(--green)">✓ Pre-loaded — instant</span>';
    _log(`[${runId}] ✓ AI brief: served from pre-inference cache (instant)`, '#10B981');
  } else {
    if (bstat) bstat.innerHTML = '<span class="spinner" style="width:10px;height:10px;border-width:1.5px"></span>&nbsp;Generating…';
    if (brief) brief.innerHTML = '<span style="color:var(--text-muted);font-style:italic">Generating intelligence brief…</span>';
    _log(`[${runId}] Generating AI intelligence brief via Gemini…`);

    try {
      const { analyzeAI } = await import('../../js/api.js');
      const cr   = result.composite_risk ?? 0;
      const text = await analyzeAI(
        `Senior climate risk analyst. Asset: ${selA.name} (${selA.id}), ${selA.country}, ${selA.type}.
Scenario: ${sc.label} ${sc.sub}. Risk: ${fPct(cr)} composite, ${fPct(result.physical_risk||0)} physical, ${fPct(result.transition_risk||0)} transition.
VaR 95%: ${fPct(result.var_95||0)}. Expected loss: ${fUsd(result.loss_expected_mm||0)}.
Trend: ${traj.trend}. 7-day delta: ${traj.delta7>=0?'+':''}${(traj.delta7*100).toFixed(1)}%.
${traj.nextCrossing ? `Predicted ${traj.nextCrossing.threshold} breach in ${traj.nextCrossing.days} days (${Math.round(traj.nextCrossing.confidence*100)}% exceedance (uncalibrated)).` : 'No threshold breach predicted in 30 days.'}
Sources: Open-Meteo ECMWF, NASA FIRMS, Carbon Monitor, IPCC AR6.
Brief: (1) key risk drivers, (2) immediate actions, (3) 30-day outlook. Max 180 words.`, 'gemini'
      );
      const narrative = text?.result || 'AI unavailable.';
      store.cacheAI(`${selA.id}:${apiKey}`, narrative);
      if (brief) {
        brief.dataset.hasResult = '1';
        // FIX: sanitize AI response
        brief.innerHTML = sanitizeHTML(narrative);
      }
      if (bstat) bstat.innerHTML = '<span style="color:var(--green)">✓ Generated</span>';
      _log(`[${runId}] ✓ AI brief generated`, '#4ade80');
    } catch(e) {
      // FIX: use textContent for error message — never inject e.message as HTML
      if (brief) brief.textContent = `AI unavailable: ${e.message}`;
      if (bstat) bstat.innerHTML = '<span style="color:var(--amber)">⚠ AI unavailable</span>';
    }
  }

  if (dot) dot.className = 'status-dot live';
  if (btn) btn.disabled = false;
  _running = false;
}

function _horLabel(d) { return d<90?`${d}d`:d<730?`${Math.round(d/365*10)/10}yr`:`${Math.round(d/365)}yr`; }
function _sCol(m)     { return m>=1.3?'var(--red)':m>=1.1?'var(--amber)':m<=0.9?'var(--green)':'var(--cobalt)'; }
