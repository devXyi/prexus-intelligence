/**
 * modules/meteorium/alerts.js
 * Prexus Intelligence — Alert Command Center
 * THE GREAT FILE · Phase 2
 *
 * FIXES:
 *  - XSS: sanitizeHTML() on all dynamic fields in _card()
 *  - XSS: filter onclick replaced with data-filter + delegated listener
 *  - Removed window._met_alerts_filter global
 */

import { store } from '../../js/store.js';
import { fPct, riskColor, riskClass, sanitizeHTML } from '../../js/utils.js';
import { updateTopbar } from './meteorium.js';

const ALERTS = [
  { id:'AL-001', asset:'SAO-AGR-008', name:'São Paulo Agri Hub',   sev:'CRITICAL', type:'PHYSICAL',
    msg:'Fire-climate compound event. Drought (0.82), fire probability 87%, heat stress 74%. Compound damage amplifier 3.1×. Immediate asset protection review required.',
    score:0.87, src:'FIRMS VIIRS 375m + ERA5 + Carbon Monitor', ts:'09:14Z',
    chain:[{label:'Temp Anomaly +2.4°C',val:0.74,color:'#F59E0B'},{label:'Drought Index',val:0.82,color:'#F97316'},{label:'Fire Probability',val:0.87,color:'#EF4444'}],
    amp:3.1, action:'Activate emergency supply chain diversification. Hedge agri exposure. Engage local crisis management.' },
  { id:'AL-002', asset:'MUM-INF-001', name:'Mumbai Port Terminal', sev:'HIGH',     type:'PHYSICAL',
    msg:'Monsoon anomaly: precipitation +147% above 10-year ERA5 baseline. Flood susceptibility 0.68. Port operations at risk during Q3 window.',
    score:0.71, src:'Open-Meteo ERA5 Reanalysis', ts:'08:57Z',
    chain:[{label:'Precip Anomaly +147%',val:0.71,color:'#0EA5E9'},{label:'Soil Saturation',val:0.64,color:'#0EA5E9'},{label:'Flood Susceptibility',val:0.68,color:'#F59E0B'}],
    amp:1.6, action:'Initiate flood contingency protocol. Review cargo storage elevation. Brief logistics team.' },
  { id:'AL-003', asset:'CHE-MFG-004', name:'Chennai Auto Cluster', sev:'HIGH',     type:'PHYSICAL',
    msg:'Heat stress probability 68% over 7-day forecast. Temperature anomaly +2.4°C above baseline.',
    score:0.65, src:'ECMWF Forecast · Open-Meteo', ts:'08:41Z',
    chain:[{label:'Temp Anomaly +2.4°C',val:0.65,color:'#F59E0B'},{label:'Heat Stress 7-day',val:0.68,color:'#F97316'}],
    amp:1.0, action:'Implement heat action plan. Review shift schedules. Check HVAC capacity.' },
  { id:'AL-004', asset:'SHA-MFG-007', name:'Shanghai Industrial',  sev:'ELEVATED', type:'TRANSITION',
    msg:'Carbon policy risk 0.71. CO₂ intensity 0.68 normalized. Regulatory exposure elevated under SSP2-4.5.',
    score:0.61, src:'Carbon Monitor CO₂ API', ts:'08:22Z',
    chain:[{label:'CO₂ Intensity Norm',val:0.68,color:'#8B5CF6'},{label:'Policy Risk Score',val:0.71,color:'#8B5CF6'}],
    amp:1.0, action:'Review carbon offset strategy. Assess regulatory timeline. Model carbon price scenarios.' },
  { id:'AL-005', asset:'DEL-ENE-002', name:'Delhi Power Grid Node', sev:'ELEVATED', type:'PHYSICAL',
    msg:'Heat stress probability 52% over forecast window. Grid demand surge risk during peak summer.',
    score:0.58, src:'Open-Meteo ECMWF Forecast', ts:'07:55Z',
    chain:[{label:'Heat Stress 52%',val:0.52,color:'#F59E0B'},{label:'Grid Demand Risk',val:0.58,color:'#F97316'}],
    amp:1.0, action:'Coordinate with grid operator on demand response. Review backup capacity.' },
];

let _filter = 'ALL';

export function init(container) {
  updateTopbar({ alertCount: ALERTS.length });
  _render(container);
}

export function destroy() { _filter = 'ALL'; }

function _render(container) {
  container.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
      <div style="font-size:8.5px;color:var(--text-muted);letter-spacing:.12em;text-transform:uppercase;flex:1">
        ${ALERTS.length} active decisions · ${ALERTS.filter(a=>a.sev==='CRITICAL').length} critical · ordered by severity
      </div>
      <div style="display:flex;gap:6px" id="alert-filters">
        ${['ALL','CRITICAL','HIGH','ELEVATED'].map(f=>`
          <button data-filter="${f}"
            style="font-size:8px;letter-spacing:.1em;padding:3px 10px;border-radius:2px;cursor:pointer;
            border:1px solid ${_filter===f?'var(--cobalt-hi)':'var(--border)'};
            color:${_filter===f?'var(--cobalt)':'var(--text-secondary)'};
            background:${_filter===f?'var(--cobalt-lo)':'transparent'};
            text-transform:uppercase;font-family:var(--font-data);transition:all .15s">
            ${f}
          </button>`).join('')}
      </div>
    </div>
    <div id="alert-list">${_filtered().map(_card).join('')}</div>`;

  // FIX: delegated listener — no filter value injected into onclick
  container.querySelector('#alert-filters')?.addEventListener('click', e => {
    const btn = e.target.closest('[data-filter]');
    if (!btn) return;
    _filter = btn.dataset.filter;
    const list = container.querySelector('#alert-list');
    if (list) list.innerHTML = _filtered().map(_card).join('');
    container.querySelectorAll('#alert-filters [data-filter]').forEach(b => {
      const active = b.dataset.filter === _filter;
      b.style.borderColor = active ? 'var(--cobalt-hi)' : 'var(--border)';
      b.style.color       = active ? 'var(--cobalt)'    : 'var(--text-secondary)';
      b.style.background  = active ? 'var(--cobalt-lo)' : 'transparent';
    });
  });
}

function _filtered() {
  return _filter === 'ALL' ? ALERTS : ALERTS.filter(a => a.sev === _filter);
}

function _card(al) {
  const c   = riskColor(al.score);
  const cls = riskClass(al.score);
  const bg  = al.sev==='CRITICAL'?'rgba(239,68,68,.2)':al.sev==='HIGH'?'rgba(245,158,11,.2)':'var(--cobalt-mid)';
  const tx  = al.sev==='CRITICAL'?'#fca5a5':al.sev==='HIGH'?'#fcd34d':'var(--cobalt)';
  const bd  = al.sev==='CRITICAL'?'rgba(239,68,68,.3)':al.sev==='HIGH'?'rgba(245,158,11,.3)':'var(--cobalt-hi)';

  // FIX: sanitize all dynamic string fields before innerHTML injection
  const safeName   = sanitizeHTML(al.name   || '');
  const safeAsset  = sanitizeHTML(al.asset  || '');
  const safeType   = sanitizeHTML(al.type   || '');
  const safeMsg    = sanitizeHTML(al.msg    || '');
  const safeAction = sanitizeHTML(al.action || '');
  const safeSrc    = sanitizeHTML(al.src    || '');
  const safeSev    = sanitizeHTML(al.sev    || '');

  const chainHTML = al.chain.map((n, i) => `
    <div class="met-cascade-node">
      <div class="met-cascade-dot" style="background:${n.color};box-shadow:0 0 4px ${n.color}"></div>
      <span class="met-cascade-label" style="font-size:10px">${sanitizeHTML(n.label)}</span>
      <span class="met-cascade-val" style="font-size:13px;color:${n.color}">${fPct(n.val)}</span>
    </div>${i < al.chain.length - 1 ? '<div class="met-cascade-arrow">↓</div>' : ''}`
  ).join('');

  return `<div class="met-decision ${cls}" style="margin-bottom:10px">
    <div class="met-dec-header">
      <span class="met-dec-badge" style="background:${bg};color:${tx};border:1px solid ${bd}">${safeSev}</span>
      <span class="met-dec-asset">${safeName}</span>
      <span class="met-dec-type">${safeType} RISK</span>
      <span class="met-dec-score" style="color:${c}">${fPct(al.score)}</span>
    </div>
    <div class="met-dec-msg">${safeMsg}</div>
    <div class="met-risk-bar" style="margin-bottom:8px"><div class="met-risk-fill" style="width:${al.score*100}%;background:${c}"></div></div>
    <div class="met-cascade" style="margin-bottom:8px">
      <div class="met-cascade-title">Risk Propagation Chain</div>
      <div class="met-cascade-chain">${chainHTML}</div>
      ${al.amp>1?`<div class="met-cascade-amp"><span class="met-cascade-amp-label">Compound Amplifier</span><span class="met-cascade-amp-val" style="color:${c}">${al.amp.toFixed(1)}×</span></div>`:''}
    </div>
    <div style="background:rgba(0,0,0,.25);border:1px solid var(--border);border-radius:2px;padding:8px 10px;margin-bottom:8px">
      <div style="font-size:7.5px;letter-spacing:.15em;text-transform:uppercase;color:var(--text-muted);margin-bottom:3px">Recommended Action</div>
      <div style="font-size:11px;color:var(--text-primary);line-height:1.55">${safeAction}</div>
    </div>
    <div class="met-dec-meta">
      <span>⬡ ${safeAsset}</span><span>◎ ${al.ts}</span>
      <span style="color:var(--text-muted)">SRC: ${safeSrc}</span>
      <div style="margin-left:auto;display:flex;gap:6px">
        <span class="tag tag-cobalt" style="cursor:pointer">ANALYZE</span>
        <span class="tag tag-dim" style="cursor:pointer">DISMISS</span>
      </div>
    </div>
  </div>`;
}
