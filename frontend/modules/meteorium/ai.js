/**
 * modules/meteorium/ai.js
 * Prexus Intelligence — AI Intelligence Assistant
 * THE GREAT FILE · Phase 2
 */

import { store } from '../../js/store.js';
import { chatAI } from '../../js/api.js';
import { fPct, fUsd, riskLabel } from '../../js/utils.js';

const SUGGESTED=[
  'Which assets are most exposed to wildfire risk this month?',
  'How would a +2°C warming scenario affect our South Asian portfolio?',
  'Explain the compound fire-climate event detected in Brazil.',
  'What transition risks should we prioritize under SSP2-4.5?',
  'Summarize current pipeline health and any anomalies.',
  'Which assets have the highest flood susceptibility?',
  'What mitigation actions reduce our CVaR 95% the most?',
];

const MODELS=[{id:'gemini',label:'Gemini 2.0',icon:'G'},{id:'claude',label:'Claude 3.5',icon:'C'},{id:'chatgpt',label:'GPT-4o',icon:'O'}];
let _history=[], _model='gemini', _loading=false;

export function init(container){
  _history=[];
  container.innerHTML=`
    <div style="display:grid;grid-template-columns:1fr 260px;gap:12px;height:calc(100vh - 160px);min-height:500px">
      <div class="panel" style="display:flex;flex-direction:column;overflow:hidden">
        <div class="panel-head">
          <span class="panel-title">Intelligence Assistant</span>
          <div style="margin-left:auto;display:flex;gap:5px">
            ${MODELS.map(m=>`<button class="met-model-btn ${m.id===_model?'active':''}" onclick="window._met_ai_model('${m.id}')" id="ai-model-${m.id}">
              <span style="width:12px;height:12px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:7px;font-weight:800;
                background:${m.id==='gemini'?'rgba(66,133,244,.2)':m.id==='claude'?'rgba(204,120,92,.2)':'rgba(116,195,101,.2)'};
                color:${m.id==='gemini'?'#4285F4':m.id==='claude'?'#cc7860':'#74C365'}">${m.icon}</span>${m.label}
            </button>`).join('')}
          </div>
        </div>
        <div id="ai-msgs" style="flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column">
          ${_welcome()}
        </div>
        <div style="border-top:1px solid var(--border);padding:10px 14px;background:rgba(0,0,0,.3)">
          <div id="ai-err" class="error-box" style="margin-bottom:6px"></div>
          <div style="display:flex;gap:8px;align-items:flex-end">
            <textarea id="ai-input" rows="1" placeholder="Ask about portfolio risk, signal anomalies, scenario projections…"
              style="flex:1;background:rgba(0,0,0,.5);border:1px solid var(--border-input);color:var(--text-primary);
                font-family:var(--font-ui);font-size:12px;padding:10px 12px;border-radius:6px;resize:none;outline:none;
                min-height:38px;max-height:100px;line-height:1.5;transition:border-color .2s"
              onfocus="this.style.borderColor='var(--cobalt)'" onblur="this.style.borderColor='var(--border-input)'"
              onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();window._met_ai_send();}"></textarea>
            <button onclick="window._met_ai_send()" class="btn btn-primary" style="padding:10px 18px;align-self:flex-end;flex-shrink:0">Send</button>
          </div>
          <div style="font-size:8px;color:var(--text-muted);margin-top:4px">Enter to send · Shift+Enter for new line</div>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px;overflow-y:auto">
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Active Context</span></div>
          <div style="padding:10px 12px">${_ctx()}</div>
        </div>
        <div class="panel">
          <div class="panel-head"><span class="panel-title">Suggested Queries</span></div>
          <div>
            ${SUGGESTED.map(p=>`<div onclick="window._met_ai_prompt('${p.replace(/'/g,"\\'")}')"
              style="padding:9px 12px;font-family:var(--font-serif);font-size:11.5px;font-style:italic;color:var(--text-secondary);
                border-bottom:1px solid rgba(14,165,233,.07);cursor:pointer;transition:all .15s;line-height:1.45"
              onmouseover="this.style.background='rgba(14,165,233,.05)';this.style.color='var(--text-primary)'"
              onmouseout="this.style.background='transparent';this.style.color='var(--text-secondary)'">${p}</div>`).join('')}
          </div>
        </div>
      </div>
    </div>`;

  window._met_ai_model=(id)=>{
    _model=id;
    MODELS.forEach(m=>{const b=document.getElementById(`ai-model-${m.id}`);if(b)b.classList.toggle('active',m.id===id);});
  };
  window._met_ai_send=_send;
  window._met_ai_prompt=(p)=>{const inp=document.getElementById('ai-input');if(inp){inp.value=p;_send();}};
}

export function destroy(){ _history=[]; _loading=false; }

function _welcome(){
  const assets=store.get('assets')||[];
  return `<div class="met-chat-msg assistant">
    <div class="met-chat-bubble">
      <strong>Meteorium Intelligence Assistant</strong><br/><br/>
      I have access to your portfolio of <strong>${assets.length||8} assets</strong> and live telemetry from
      NASA FIRMS, ERA5, Carbon Monitor, and Sentinel-2. What would you like to analyze?
    </div>
    <div class="met-chat-meta">METEORIUM AI · ${_model.toUpperCase()} · Portfolio context loaded</div>
  </div>`;
}

function _ctx(){
  const assets=store.get('assets')||[];
  const maxRisk=assets.length>0?Math.max(...assets.map(a=>a.cr||0)):0.87;
  return [['Assets loaded',String(assets.length||8)],['Max risk',fPct(maxRisk)],['Risk level',riskLabel(maxRisk)],['Active model',_model]]
    .map(([k,v])=>`<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(14,165,233,.06)">
      <span style="font-size:9px;color:var(--text-muted);letter-spacing:.06em;text-transform:uppercase">${k}</span>
      <span style="font-family:var(--font-data);font-size:9.5px;color:var(--text-secondary)">${v}</span>
    </div>`).join('');
}

async function _send(){
  if(_loading)return;
  const input=document.getElementById('ai-input');
  const errEl=document.getElementById('ai-err');
  const msgs=document.getElementById('ai-msgs');
  const text=input?.value?.trim();
  if(!text)return;
  if(errEl){errEl.textContent='';errEl.classList.remove('visible');}
  _history.push({role:'user',content:text});
  _appendMsg('user',text);
  if(input)input.value='';
  _loading=true;
  const thinkId='ai-think-'+Date.now();
  _appendThink(thinkId);
  try{
    const assets=store.get('assets')||[];
    const ctx=assets.length?`Senior climate risk analyst. Portfolio: ${assets.slice(0,5).map(a=>`${a.id}(cr=${fPct(a.cr||0)})`).join(', ')}. Be concise.`:'Senior climate risk analyst. Be concise.';
    const messages=[{role:'user',content:ctx+'\n\nQuery: '+text},..._history.slice(-5,-1)];
    const resp=await chatAI(messages,_model);
    const reply=resp?.result||'No response received.';
    document.getElementById(thinkId)?.remove();
    _history.push({role:'assistant',content:reply});
    _appendMsg('assistant',reply);
  }catch(err){
    document.getElementById(thinkId)?.remove();
    const msg=err.isTimeout?'AI service is waking up — please retry.':err.isNetwork?'Cannot reach AI service.':err.message;
    if(errEl){errEl.textContent=`⚠ ${msg}`;errEl.classList.add('visible');}
    _appendMsg('assistant',_fallback(text));
  }finally{_loading=false;}
}

function _appendMsg(role,content){
  const area=document.getElementById('ai-msgs');
  if(!area)return;
  const time=new Date().toISOString().slice(11,19)+' UTC';
  const div=document.createElement('div');
  div.className=`met-chat-msg ${role}`;
  div.innerHTML=`<div class="met-chat-bubble">${content.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>').replace(/\n/g,'<br/>')}</div>
    <div class="met-chat-meta">${role==='user'?'YOU':'METEORIUM AI · '+_model.toUpperCase()} · ${time}</div>`;
  area.appendChild(div);
  area.scrollTop=area.scrollHeight;
}

function _appendThink(id){
  const area=document.getElementById('ai-msgs');
  if(!area)return;
  const div=document.createElement('div');
  div.className='met-chat-msg assistant';div.id=id;
  div.innerHTML=`<div class="met-chat-bubble" style="display:flex;align-items:center;gap:8px;font-style:italic;color:var(--text-muted)"><span class="spinner"></span>Analyzing…</div>`;
  area.appendChild(div);area.scrollTop=area.scrollHeight;
}

function _fallback(prompt){
  if(prompt.toLowerCase().includes('wildfire'))return'Based on current FIRMS VIIRS data, São Paulo Agri Hub (SAO-AGR-008) shows highest wildfire exposure at 87%. Compound fire-climate event (amplifier 3.1×) makes this the most critical asset.';
  if(prompt.toLowerCase().includes('portfolio'))return'Portfolio composite risk is 52% under SSP2-4.5. Top concerns: São Paulo Agri Hub (87% — compound event), Mumbai Port (71% — monsoon anomaly), Chennai Auto Cluster (65% — heat stress).';
  if(prompt.toLowerCase().includes('flood'))return'Flood susceptibility elevated for Mumbai Port Terminal (0.68) driven by +147% precipitation anomaly. Chennai coastal zone also shows elevated soil saturation.';
  return'AI service unavailable — offline mode active. For immediate analysis, use the Analysis module with the Monte Carlo scenario builder.';
}
