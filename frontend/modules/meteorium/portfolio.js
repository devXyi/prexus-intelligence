/**
 * modules/meteorium/portfolio.js
 * Prexus Intelligence — Asset Portfolio Registry
 * THE GREAT FILE · Phase 2
 *
 * FIXES:
 *  - XSS: sanitizeHTML() applied to all asset fields injected into innerHTML
 *  - XSS: onclick delete no longer injects a.id into JS string;
 *         uses data-id attribute + delegated event listener instead
 */

import { store } from '../../js/store.js';
import { getAssets, createAsset, deleteAsset } from '../../js/api.js';
import { fPct, fUsd, riskColor, riskLabel, sanitizeHTML } from '../../js/utils.js';

const SIM=[
  {id:'MUM-INF-001',name:'Mumbai Port Terminal',    type:'Infrastructure',country:'India',    cc:'IND',lat:18.93, lon:72.83,  value_mm:450, pr:0.68,tr:0.44,cr:0.71,alerts:2},
  {id:'DEL-ENE-002',name:'Delhi Power Grid Node',   type:'Energy',       country:'India',    cc:'IND',lat:28.61, lon:77.20,  value_mm:280, pr:0.55,tr:0.51,cr:0.58,alerts:1},
  {id:'MUM-FIN-003',name:'BKC Financial Complex',   type:'Financial',    country:'India',    cc:'IND',lat:19.06, lon:72.87,  value_mm:1200,pr:0.38,tr:0.56,cr:0.42,alerts:0},
  {id:'CHE-MFG-004',name:'Chennai Auto Cluster',    type:'Manufacturing',country:'India',    cc:'IND',lat:13.08, lon:80.27,  value_mm:320, pr:0.71,tr:0.38,cr:0.65,alerts:1},
  {id:'SGP-TRN-005',name:'Singapore PSA Terminal',  type:'Transport',    country:'Singapore',cc:'SGP',lat:1.27,  lon:103.82, value_mm:890, pr:0.28,tr:0.42,cr:0.33,alerts:0},
  {id:'LON-FIN-006',name:'Canary Wharf Finance Hub', type:'Financial',   country:'UK',       cc:'GBR',lat:51.51, lon:-0.02,  value_mm:2100,pr:0.24,tr:0.38,cr:0.28,alerts:0},
  {id:'SHA-MFG-007',name:'Shanghai Industrial Zone', type:'Manufacturing',country:'China',   cc:'CHN',lat:31.23, lon:121.47, value_mm:640, pr:0.66,tr:0.48,cr:0.61,alerts:1},
  {id:'SAO-AGR-008',name:'São Paulo Agri Hub',       type:'Agriculture', country:'Brazil',   cc:'BRA',lat:-23.55,lon:-46.63, value_mm:190, pr:0.91,tr:0.35,cr:0.87,alerts:3},
];

let _assets=[], _showAdd=false;

export async function init(container) {
  container.innerHTML=`<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:10px"><span class="spinner"></span>&nbsp;Loading assets…</div>`;
  try {
    const live=await getAssets();
    _assets=Array.isArray(live)&&live.length>0?live:SIM;
    store.set('assets',_assets);
  } catch { _assets=store.get('assets')||SIM; }
  _render(container);
}

export function destroy(){ _showAdd=false; }

function _render(container){
  const sorted=[..._assets].sort((a,b)=>(b.cr||0)-(a.cr||0));
  const totalVal=_assets.reduce((s,a)=>s+(a.value_mm||0),0);

  container.innerHTML=`
    <div class="met-kpi-grid" style="margin-bottom:14px">
      <div class="met-kpi cobalt"><div class="met-kpi-label">Total Assets</div><div class="met-kpi-value">${_assets.length}</div><div class="met-kpi-sub">Registered</div></div>
      <div class="met-kpi cobalt"><div class="met-kpi-label">Total Exposure</div><div class="met-kpi-value">${fUsd(totalVal)}</div><div class="met-kpi-sub">Portfolio value</div></div>
      <div class="met-kpi red"><div class="met-kpi-label">Highest Risk</div><div class="met-kpi-value">${fPct(Math.max(..._assets.map(a=>a.cr||0)))}</div><div class="met-kpi-sub">Single asset</div></div>
      <div class="met-kpi amber"><div class="met-kpi-label">Active Alerts</div><div class="met-kpi-value">${_assets.reduce((s,a)=>s+(a.alerts||0),0)}</div><div class="met-kpi-sub">Across all assets</div></div>
    </div>
    <div class="panel">
      <div class="panel-head">
        <span class="panel-title">Asset Risk Registry · Sorted by Composite Risk</span>
        <div style="margin-left:auto;display:flex;gap:8px">
          <span class="tag tag-cobalt">LIVE SCORES</span>
          <button id="port-add-toggle" class="btn btn-ghost" style="padding:3px 12px;font-size:9px">+ Add Asset</button>
        </div>
      </div>
      <div id="port-add-form" style="display:none;padding:14px;border-bottom:1px solid var(--border);background:rgba(14,165,233,.03)">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px">
          ${[['port-name','Asset Name *','text','Mumbai Storage Depot'],['port-type','Type','select',''],['port-cc','Country Code','text','IND'],['port-country','Country','text','India'],['port-lat','Latitude','number','18.93'],['port-lon','Longitude','number','72.83'],['port-val','Value (USD M)','number','10']].map(([id,lbl,t,ph])=>
            t==='select'
              ? `<div><div class="form-label">${lbl}</div><select id="${id}" class="inp-field" style="font-size:12px;text-align:left"><option>Infrastructure</option><option>Energy</option><option>Manufacturing</option><option>Agriculture</option><option>Transport</option><option>Financial</option></select></div>`
              : `<div><div class="form-label">${lbl}</div><input id="${id}" type="${t}" placeholder="${ph}" class="inp-field" style="font-size:12px;text-align:left;letter-spacing:0"/></div>`
          ).join('')}
        </div>
        <div style="display:flex;gap:8px">
          <button id="port-submit" class="btn btn-primary" style="padding:7px 20px">Create Asset</button>
          <button id="port-cancel" class="btn btn-ghost" style="padding:7px 16px">Cancel</button>
        </div>
      </div>
      <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="background:rgba(0,0,0,.4)">
            ${['Asset ID','Name','Type','CC','Value','Composite','Physical','Transition','Alerts','Actions'].map(h=>`<th style="padding:7px 11px;text-align:left;font-size:7.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--text-muted);border-bottom:1px solid var(--border);white-space:nowrap">${h}</th>`).join('')}
          </tr></thead>
          <tbody id="port-tbody">${sorted.map(_row).join('')}</tbody>
        </table>
      </div>
    </div>`;

  // ── Toggle add form ───────────────────────────────────────────────────────
  const _toggle = () => {
    _showAdd = !_showAdd;
    const f = container.querySelector('#port-add-form');
    if (f) f.style.display = _showAdd ? 'block' : 'none';
  };
  container.querySelector('#port-add-toggle')?.addEventListener('click', _toggle);
  container.querySelector('#port-cancel')?.addEventListener('click', _toggle);

  // ── Submit new asset ──────────────────────────────────────────────────────
  container.querySelector('#port-submit')?.addEventListener('click', async () => {
    const name = container.querySelector('#port-name')?.value?.trim();
    if (!name) return;
    const type     = container.querySelector('#port-type')?.value;
    const cc       = (container.querySelector('#port-cc')?.value || '').toUpperCase();
    const country  = container.querySelector('#port-country')?.value || '';
    const lat      = parseFloat(container.querySelector('#port-lat')?.value || 0);
    const lon      = parseFloat(container.querySelector('#port-lon')?.value || 0);
    const value_mm = parseFloat(container.querySelector('#port-val')?.value || 10);
    try {
      const created = await createAsset({ name, type, lat, lon, value_mm, cc, country });
      _assets.push(created);
    } catch {
      _assets.push({
        id: `${cc||'AST'}-${type?.slice(0,3).toUpperCase()||'AST'}-${Date.now().toString().slice(-4)}`,
        name, type, lat, lon, value_mm, cc, country,
        pr: 0.5, tr: 0.4, cr: 0.45, alerts: 0,
      });
    }
    store.set('assets', _assets);
    _showAdd = false;
    _render(container);
  });

  // FIX: delegated delete listener — no asset ID injected into onclick attribute
  container.querySelector('#port-tbody')?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-delete-id]');
    if (!btn) return;
    e.stopPropagation();
    const id = btn.dataset.deleteId;
    if (!id || !confirm(`Delete ${id}?`)) return;
    try { await deleteAsset(id); } catch {}
    _assets = _assets.filter(a => a.id !== id);
    store.set('assets', _assets);
    _render(container);
  });
}

function _row(a) {
  const c = riskColor(a.cr || 0);
  // FIX: sanitizeHTML() on all asset fields before injecting into innerHTML
  const safeId      = sanitizeHTML(a.id   || '—');
  const safeName    = sanitizeHTML(a.name || '—');
  const safeType    = sanitizeHTML(a.type || '—');
  const safeCc      = sanitizeHTML(a.cc   || '—');

  return `<tr style="border-bottom:1px solid rgba(14,165,233,.07);transition:background .12s"
    onmouseover="this.style.background='rgba(14,165,233,.04)'" onmouseout="this.style.background='transparent'">
    <td style="padding:8px 11px;font-family:var(--font-data);font-size:10px;color:var(--cobalt)">${safeId}</td>
    <td style="padding:8px 11px;font-size:11px;color:var(--text-primary);font-weight:500">${safeName}</td>
    <td style="padding:8px 11px;font-size:9px;color:var(--text-secondary);text-transform:uppercase">${safeType}</td>
    <td style="padding:8px 11px;font-size:10px;color:var(--text-secondary)">${safeCc}</td>
    <td style="padding:8px 11px;font-family:var(--font-display);font-size:14px;color:var(--text-primary)">${fUsd(a.value_mm)}</td>
    <td style="padding:8px 11px"><div style="display:flex;align-items:center;gap:6px">
      <span style="font-family:var(--font-display);font-size:15px;color:${c}">${fPct(a.cr||0)}</span>
      <div style="width:50px"><div class="met-risk-bar"><div class="met-risk-fill" style="width:${(a.cr||0)*100}%;background:${c}"></div></div></div>
    </div></td>
    <td style="padding:8px 11px;font-family:var(--font-display);font-size:14px;color:var(--cobalt)">${fPct(a.pr||0)}</td>
    <td style="padding:8px 11px;font-family:var(--font-display);font-size:14px;color:var(--amber)">${fPct(a.tr||0)}</td>
    <td style="padding:8px 11px">${(a.alerts||0)>0
      ? `<span style="font-size:10px;color:var(--red);background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);padding:1px 7px;border-radius:2px">${a.alerts}</span>`
      : '<span style="color:var(--text-muted);font-size:10px">—</span>'
    }</td>
    <td style="padding:8px 11px"><div style="display:flex;gap:5px">
      <span class="tag tag-cobalt" style="cursor:pointer">SCORE</span>
      <span class="tag tag-red" style="cursor:pointer" data-delete-id="${safeId}">DEL</span>
    </div></td>
  </tr>`;
}
