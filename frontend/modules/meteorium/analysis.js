/**
 * modules/meteorium/analysis.js
 * Prexus Intelligence — Risk Analysis Terminal
 * THE GREAT FILE · Phase 2
 */

import { store } from '../../js/store.js';
import { scoreAsset } from '../../js/api.js';
import { fPct, fUsd, riskColor, riskLabel } from '../../js/utils.js';

const SCENARIOS=[
  {id:'ssp119',   label:'SSP1-1.9', sub:'Paris 1.5°C',    mult:0.88},
  {id:'baseline', label:'SSP2-4.5', sub:'Baseline 2.7°C', mult:1.12},
  {id:'ssp370',   label:'SSP3-7.0', sub:'High 3.6°C',     mult:1.24},
  {id:'ssp585',   label:'SSP5-8.5', sub:'Failed 4.4°C',   mult:1.38},
];
const SIM_STRESS=[
  {label:'SSP1-1.9 · Paris (1.5°C)',    composite_risk:0.46, var_95:0.14, expected_loss_mm:28.4 },
  {label:'SSP2-4.5 · Baseline (2.7°C)', composite_risk:0.65, var_95:0.19, expected_loss_mm:48.2 },
  {label:'SSP3-7.0 · High (3.6°C)',     composite_risk:0.76, var_95:0.24, expected_loss_mm:68.1 },
  {label:'SSP5-8.5 · Failed (4.4°C)',   composite_risk:0.87, var_95:0.31, expected_loss_mm:102.4},
];
const SIM_HIST=[0.04,0.06,0.09,0.12,0.15,0.18,0.14,0.10,0.07,0.05,0.04,0.03,0.02,0.02,0.02,0.01,0.01,0.01,0.01,0.00];

let _running=false, _scenario='baseline', _horizon=365;

export function init(container) {
  const assets = store.get('assets') || [];
  container.innerHTML = `
    <div style="display:grid;grid-template-columns:320px 1fr;gap:12px">
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Scenario Builder</span></div>
          <div style="padding:14px;display:flex;flex-direction:column;gap:12px">
            <div>
              <div class="form-label">Target Asset</div>
              <select id="anl-asset" class="inp-field" style="font-size:12px;text-align:left;letter-spacing:0">
                <option value="">Select asset…</option>
                ${assets.map(a=>`<option value="${a.id}">${a.name||a.id}</option>`).join('')}
                <option value="SIM" selected>SAO-AGR-008 · São Paulo (simulation)</option>
              </select>
            </div>
            <div>
              <div class="form-label">Climate Scenario</div>
              <div style="display:flex;flex-direction:column;gap:6px">
                ${SCENARIOS.map(s=>`
                  <label style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:8px;border-radius:3px;
                    border:1px solid ${s.id===_scenario?'var(--cobalt-hi)':'var(--border)'};
                    background:${s.id===_scenario?'var(--cobalt-lo)':'transparent'};transition:all .15s" id="anl-scen-${s.id}">
                    <input type="radio" name="anl-scen" value="${s.id}" ${s.id===_scenario?'checked':''} style="accent-color:var(--cobalt)">
                    <div style="flex:1">
                      <div style="font-family:var(--font-display);font-size:13px;color:var(--text-primary);letter-spacing:.08em">${s.label}</div>
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
              <input type="range" id="anl-hor" min="30" max="3650" step="30" value="${_horizon}" style="width:100%;accent-color:var(--cobalt);margin-top:6px">
              <div style="display:flex;justify-content:space-between;font-size:8px;color:var(--text-muted);margin-top:2px">
                <span>30d</span><span>1yr</span><span>5yr</span><span>10yr</span>
              </div>
            </div>
            <button id="anl-run" class="btn btn-primary" style="width:100%" onclick="window._met_anl_run()">▶&nbsp;Run Analysis</button>
          </div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div id="anl-kpis" class="met-kpi-grid">
          ${['Composite Risk','VaR 95%','CVaR 95%','Expected Loss'].map(l=>`<div class="met-kpi cobalt"><div class="met-kpi-label">${l}</div><div class="met-kpi-value">—</div><div class="met-kpi-sub">Run analysis</div></div>`).join('')}
        </div>
        <div class="panel">
          <div class="panel-head">
            <span class="panel-title">Monte Carlo Loss Distribution · N=5,000</span>
            <div style="margin-left:auto"><span class="tag tag-amber" id="anl-eng-tag">PYTHON FALLBACK</span></div>
          </div>
          <div id="anl-hist" style="padding:16px">${_hist(SIM_HIST,'var(--cobalt)',0.65,0.87)}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><span class="panel-title">SSP Scenario Stress Test</span></div>
          <div id="anl-stress">${_stress(SIM_STRESS)}</div>
        </div>
      </div>
    </div>`;

  container.querySelectorAll('input[name="anl-scen"]').forEach(r=>{
    r.addEventListener('change', ()=>{
      _scenario=r.value;
      SCENARIOS.forEach(s=>{
        const el=document.getElementById(`anl-scen-${s.id}`);
        if(el){el.style.borderColor=s.id===_scenario?'var(--cobalt-hi)':'var(--border)';el.style.background=s.id===_scenario?'var(--cobalt-lo)':'transparent';}
      });
    });
  });

  const slider=document.getElementById('anl-hor');
  const lbl=document.getElementById('anl-hor-lbl');
  if(slider&&lbl) slider.addEventListener('input',()=>{_horizon=parseInt(slider.value);lbl.textContent=_horLabel(_horizon);});

  window._met_anl_run=async()=>{
    if(_running)return;_running=true;
    const btn=document.getElementById('anl-run');
    const kpis=document.getElementById('anl-kpis');
    if(btn)btn.disabled=true;
    if(kpis)kpis.innerHTML=`<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);font-size:10px;padding:10px"><span class="spinner"></span>&nbsp;Running Monte Carlo…</div>`;
    try{
      let r=null;
      const assetSel=document.getElementById('anl-asset')?.value;
      if(assetSel&&assetSel!=='SIM'){
        const a=(store.get('assets')||[]).find(x=>x.id===assetSel);
        if(a) r=await scoreAsset({assetId:a.id,lat:a.lat||0,lon:a.lon||0,countryCode:a.cc||'IND',valueMm:a.value_mm||10,assetType:a.type||'infrastructure',scenario:_scenario,horizonDays:_horizon});
      }
      const sc=SCENARIOS.find(s=>s.id===_scenario)||SCENARIOS[1];
      const sim={composite_risk:0.52*sc.mult,var_95:0.19*sc.mult,cvar_95:0.28*sc.mult,loss_expected_mm:48.2*sc.mult,engine:'python_mc_fallback'};
      const d=r||sim;
      if(kpis)kpis.innerHTML=`
        <div class="met-kpi ${d.composite_risk>=0.65?'amber':'cobalt'}"><div class="met-kpi-label">Composite Risk</div><div class="met-kpi-value">${fPct(d.composite_risk)}</div><div class="met-kpi-sub">${riskLabel(d.composite_risk)}</div></div>
        <div class="met-kpi amber"><div class="met-kpi-label">VaR 95%</div><div class="met-kpi-value">${fPct(d.var_95)}</div><div class="met-kpi-sub">${_horizon}d horizon</div></div>
        <div class="met-kpi red"><div class="met-kpi-label">CVaR 95%</div><div class="met-kpi-value">${fPct(d.cvar_95)}</div><div class="met-kpi-sub">Tail risk</div></div>
        <div class="met-kpi red"><div class="met-kpi-label">Expected Loss</div><div class="met-kpi-value">${fUsd(d.loss_expected_mm)}</div><div class="met-kpi-sub">Probability-weighted</div></div>`;
      const tag=document.getElementById('anl-eng-tag');
      if(tag){const rust=d.engine?.includes('rust');tag.textContent=rust?'RUST ENGINE':'PYTHON FALLBACK';tag.className=`tag ${rust?'tag-green':'tag-amber'}`;}
      const hist=document.getElementById('anl-hist');
      if(hist)hist.innerHTML=_hist(r?.histogram?.map(b=>b.frequency)||SIM_HIST,riskColor(d.composite_risk),d.var_95,d.cvar_95);
      const stressEl=document.getElementById('anl-stress');
      if(stressEl)stressEl.innerHTML=_stress(r?.stress_scenarios?.length?r.stress_scenarios:SIM_STRESS);
    }catch(err){
      if(kpis)kpis.innerHTML=`<div style="grid-column:1/-1;padding:10px;font-size:11px;color:var(--red);background:var(--red-lo);border:1px solid rgba(239,68,68,.3);border-radius:3px">⚠ ${err.message}</div>`;
    }finally{_running=false;if(btn){btn.disabled=false;btn.innerHTML='▶&nbsp;Run Analysis';}}
  };
}

export function destroy(){_running=false;_scenario='baseline';}

function _hist(freqs,fillC,var95,cvar95){
  const W=600,H=120,pad=40,max=Math.max(...freqs,0.001),n=freqs.length,bw=(W-pad*2)/n;
  const rawC=fillC.replace('var(--cobalt)','rgba(14,165,233,.6)').replace('var(--red)','rgba(239,68,68,.7)').replace('var(--amber)','rgba(245,158,11,.7)');
  const bars=freqs.map((f,i)=>{
    const h=(f/max)*(H-20),x=pad+i*bw,y=H-h;
    const isCVaR=i/n>=cvar95,isVar=i/n>=var95;
    const c=isCVaR?'rgba(239,68,68,.7)':isVar?'rgba(245,158,11,.7)':rawC;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw-1).toFixed(1)}" height="${h.toFixed(1)}" fill="${c}" rx="1"/>`;
  }).join('');
  const vx=(pad+var95*(W-pad*2)).toFixed(1),cx=(pad+cvar95*(W-pad*2)).toFixed(1);
  return `<div style="overflow-x:auto">
    <svg viewBox="0 0 ${W} ${H+24}" style="width:100%;max-width:${W}px;height:auto">
      ${bars}
      <line x1="${vx}" y1="0" x2="${vx}" y2="${H}" stroke="rgba(245,158,11,.8)" stroke-width="1.5" stroke-dasharray="4 3"/>
      <line x1="${cx}" y1="0" x2="${cx}" y2="${H}" stroke="rgba(239,68,68,.8)"  stroke-width="1.5" stroke-dasharray="4 3"/>
      <text x="${vx}" y="${H+16}" text-anchor="middle" fill="rgba(245,158,11,.8)" font-family="'Martian Mono',monospace" font-size="9">VaR 95%</text>
      <text x="${cx}" y="${H+16}" text-anchor="middle" fill="rgba(239,68,68,.8)"  font-family="'Martian Mono',monospace" font-size="9">CVaR 95%</text>
    </svg>
    <div style="display:flex;gap:16px;justify-content:center;margin-top:4px">
      <div style="display:flex;align-items:center;gap:4px;font-size:8px;color:var(--text-muted)"><div style="width:12px;height:3px;background:rgba(245,158,11,.8);border-radius:1px"></div>VaR 95% — ${fPct(var95)}</div>
      <div style="display:flex;align-items:center;gap:4px;font-size:8px;color:var(--text-muted)"><div style="width:12px;height:3px;background:rgba(239,68,68,.8);border-radius:1px"></div>CVaR 95% — ${fPct(cvar95)}</div>
    </div>
  </div>`;
}

function _stress(scenarios){
  return scenarios.map(s=>{
    const cr=s.composite_risk||0,v95=s.var_95||0,loss=s.expected_loss_mm||0,c=riskColor(cr);
    return `<div style="display:flex;align-items:center;gap:12px;padding:9px 14px;border-bottom:1px solid var(--border)">
      <div style="flex:2;font-family:var(--font-serif);font-size:11.5px;color:var(--text-secondary);font-style:italic">${s.label}</div>
      <div style="width:80px"><div class="met-risk-bar"><div class="met-risk-fill" style="width:${cr*100}%;background:${c}"></div></div></div>
      <div style="font-family:var(--font-display);font-size:16px;color:${c};min-width:50px;text-align:right">${fPct(cr)}</div>
      <div style="font-size:10px;color:var(--text-secondary);min-width:55px;text-align:right">VaR ${fPct(v95)}</div>
      <div style="font-size:10px;color:var(--text-secondary);min-width:60px;text-align:right">${fUsd(loss)}</div>
      <span class="tag tag-dim" style="min-width:55px;justify-content:center">${riskLabel(cr)}</span>
    </div>`;
  }).join('');
}

function _horLabel(d){return d<90?`${d}d`:d<730?`${Math.round(d/365*10)/10}yr`:`${Math.round(d/365)}yr`;}
function _sCol(m){return m>=1.3?'var(--red)':m>=1.1?'var(--amber)':m<=0.9?'var(--green)':'var(--cobalt)';}

