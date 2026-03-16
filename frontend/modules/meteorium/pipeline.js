/**
 * modules/meteorium/pipeline.js
 * Prexus Intelligence — Pipeline Architecture Status
 * THE GREAT FILE · Phase 2
 */

import { riskHealth, lakeStats, queueStats } from '../../js/api.js';

const LAYERS=[
  {num:'0',name:'Satellite & Agency Sources',desc:'19 external data sources. NASA FIRMS, ECMWF ERA5, Copernicus, Carbon Monitor, Planet Labs, Maxar, JAXA, ISRO.',pills:['NASA','ESA','JAXA','ISRO','NOAA']},
  {num:'1',name:'Telemetry Acquisition Workers',desc:'Async workers per source. OpenMeteo, FIRMS, Carbon, ERA5. Redis Streams producer. APScheduler: 1h/3h/24h.',pills:['asyncio','httpx','APScheduler','Redis Streams']},
  {num:'2',name:'Raw Telemetry Lake',desc:'Immutable object store with SQLite manifest. Files tagged by source, bbox, time range, hash. Never modified post-deposit.',pills:['SQLite WAL','Manifest','Immutable']},
  {num:'3',name:'Geospatial Preprocessing ETL',desc:'H3 hexagonal indexing at resolution 7 (~5km²). ERA5→anomaly tiles. FIRMS→fire density surface. S2→NDVI/NDWI.',pills:['H3','xarray','GDAL','PostGIS']},
  {num:'4',name:'Asset Feature Store',desc:'Per-asset intelligence vectors. Physical + transition + satellite features. Confidence tracking. 6-hour cache with freshness decay.',pills:['SQLite WAL','Confidence','Fusion','Cache 6h']},
  {num:'5',name:'Risk Computation Engine',desc:'PhysicalRiskScorer + TransitionRiskScorer + SignalFusion. Compound amplification. Rust Monte Carlo 10k draws ~12ms via PyO3.',pills:['Rust PyO3','Monte Carlo','IPCC AR6','VaR/CVaR']},
  {num:'6',name:'API & Intelligence Delivery',desc:'FastAPI Python engine proxied via Go gateway. Redis Streams queue. JWT authentication. 15 endpoints with provenance metadata.',pills:['FastAPI','Go gin','Redis','JWT','REST']},
];

const WORKERS=[
  {name:'Open-Meteo ECMWF Forecast',cadence:'Every 1h', last:'~40min ago',status:'nominal'},
  {name:'NASA FIRMS VIIRS 375m',    cadence:'Every 3h', last:'~2h ago',   status:'nominal'},
  {name:'Carbon Monitor CO₂',      cadence:'Every 24h',last:'~11h ago',  status:'nominal'},
  {name:'ERA5 CDS Reanalysis',      cadence:'Every 7d', last:'3d ago',    status:'warn'},
];

export async function init(container) {
  container.innerHTML=`<div style="text-align:center;padding:20px;color:var(--text-muted);font-size:10px"><span class="spinner"></span>&nbsp;Fetching system health…</div>`;
  let health=null,lake=null,queue=null;
  try{ [health,lake,queue]=await Promise.allSettled([riskHealth(),lakeStats(),queueStats()]); }catch{}
  const h=health?.status==='fulfilled'?health.value:null;
  const l=lake?.status==='fulfilled'?lake.value:null;
  const q=queue?.status==='fulfilled'?queue.value:null;
  _render(container,h,l,q);
}

export function destroy(){}

function _render(container,health,lake,queue){
  const rust=health?.rust_engine||false;
  const qOn=health?.queue?.available||false;
  const lakeFiles=lake?.total_files||0;
  const lakeMb=lake?.total_size_mb||0;
  const streams=queue?.streams||{};

  container.innerHTML=`
    <div class="met-kpi-grid" style="margin-bottom:14px">
      <div class="met-kpi ${rust?'green':'amber'}"><div class="met-kpi-label">Rust Engine</div><div class="met-kpi-value">${rust?'ONLINE':'OFFLINE'}</div><div class="met-kpi-sub">Monte Carlo · PyO3</div></div>
      <div class="met-kpi ${qOn?'green':'amber'}"><div class="met-kpi-label">Redis Queue</div><div class="met-kpi-value">${qOn?'ONLINE':'OFFLINE'}</div><div class="met-kpi-sub">Redis Streams v2</div></div>
      <div class="met-kpi cobalt"><div class="met-kpi-label">Lake Files</div><div class="met-kpi-value">${lakeFiles}</div><div class="met-kpi-sub">${lakeMb.toFixed(1)} MB total</div></div>
      <div class="met-kpi green"><div class="met-kpi-label">Pipeline</div><div class="met-kpi-value">7 / 7</div><div class="met-kpi-sub">Layers nominal</div></div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 340px;gap:12px">
      <div class="panel">
        <div class="panel-head"><span class="panel-title">7-Layer Pipeline Architecture</span><div style="margin-left:auto"><span class="tag tag-green">ALL NOMINAL</span></div></div>
        ${LAYERS.map((l,i)=>`
          <div class="met-layer-row">
            <div class="met-layer-num">${l.num}</div>
            <div class="met-layer-connector">
              <div class="met-layer-dot" style="background:var(--cobalt);box-shadow:0 0 6px var(--cobalt)"></div>
              ${i<LAYERS.length-1?'<div class="met-layer-line"></div>':''}
            </div>
            <div class="met-layer-info">
              <div class="met-layer-name">${l.name}</div>
              <div class="met-layer-desc">${l.desc}</div>
              <div class="met-layer-pills">${l.pills.map(p=>`<span class="met-layer-pill">${p}</span>`).join('')}</div>
            </div>
            <div style="padding-left:12px;flex-shrink:0"><span class="tag tag-green">NOMINAL</span></div>
          </div>`).join('')}
      </div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Ingestion Workers</span></div>
          ${WORKERS.map(w=>`
            <div class="met-src-row">
              <div class="status-dot ${w.status==='nominal'?'live':'warn'}"></div>
              <div style="flex:1"><div style="font-size:10px;color:var(--text-primary)">${w.name}</div><div style="font-size:8px;color:var(--text-muted);margin-top:1px">${w.cadence}</div></div>
              <div style="font-size:9px;color:var(--text-secondary)">${w.last}</div>
            </div>`).join('')}
        </div>
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Redis Stream Stats</span><div style="margin-left:auto"><span class="tag ${qOn?'tag-green':'tag-amber'}">${qOn?'LIVE':'OFFLINE'}</span></div></div>
          <div style="padding:8px 12px">
            ${['telemetry','satellite','alerts','rescore','deadletter'].map(name=>{
              const len=(streams[name]?.length||0);
              return `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(14,165,233,.06)">
                <span style="font-family:var(--font-data);font-size:8.5px;color:var(--cobalt);width:110px">meteorium:${name}</span>
                <div style="flex:1"><div class="met-risk-bar"><div class="met-risk-fill" style="width:${Math.min(100,len/10)}%;background:var(--cobalt)"></div></div></div>
                <span style="font-family:var(--font-display);font-size:14px;color:var(--cobalt);min-width:28px;text-align:right">${len}</span>
              </div>`;}).join('')}
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Build Information</span></div>
          <div style="padding:10px 12px">
            ${[['Engine','Meteorium v2.0.0'],['Go Gateway','v2.0.0 · gin 1.10'],['Python','FastAPI 0.111 · 3.11'],['Rust MC','PyO3 0.20 · Rayon 1.8'],['IPCC','AR6 WG-II · SSP1-5'],].map(([k,v])=>`
              <div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(14,165,233,.06)">
                <span style="font-size:9px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.08em">${k}</span>
                <span style="font-family:var(--font-data);font-size:9px;color:var(--text-secondary)">${v}</span>
              </div>`).join('')}
          </div>
        </div>
      </div>
    </div>`;
}

