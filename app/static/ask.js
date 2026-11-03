/* OpenTicker: Ask. A side sheet where the user asks questions or runs a skill (a ready-made playbook)
   about a stock, their portfolio or the market. Answers stream from an agent on the user's own Mac
   (Claude Code, Codex, opencode, or a local Ollama model), so their existing subscription pays.
   Shares globals with index.html: $, esc, ic, IC, load, save, base, sel, drawerOpen, page, openStock, COMMANDS. */

Object.assign(IC,{
  spark:'<path d="M12 3l1.8 4.9L18.7 9.7 13.8 11.5 12 16.4 10.2 11.5 5.3 9.7 10.2 7.9z"/><path d="M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z"/>',
  send:'<path d="M12 19V5M5 12l7-7 7 7"/>', stop:'<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  copy:'<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>', check:'<path d="M20 6 9 17l-5-5"/>',
  compose:'<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>', phone:'<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
  chev:'<path d="m6 9 6 6 6-6"/>'});

/* skills ship with the server; this copy lets chips render before /api/ask/info answers */
const ASK_SKILLS_FALLBACK=[
  {name:"stock-snapshot",label:"Quick take",scope:"stock"},{name:"explain-move",label:"Why is it moving?",scope:"stock"},
  {name:"bull-bear",label:"Bull vs bear",scope:"stock"},{name:"earnings-preview",label:"Earnings preview",scope:"stock"},
  {name:"analyst-pulse",label:"What analysts say",scope:"stock"},{name:"valuation-check",label:"Is it expensive?",scope:"stock"},
  {name:"portfolio-checkup",label:"Check up on my portfolio",scope:"portfolio"},{name:"week-ahead",label:"What to watch this week",scope:"portfolio"},
  {name:"market-recap",label:"Market recap",scope:"market"},{name:"sector-rotation",label:"Which sectors lead?",scope:"market"},{name:"macro-check",label:"Macro backdrop",scope:"market"}];
const ASK={info:null,infoAt:0,ctx:{scope:"market",t:null},conv:[],run:null,prov:load("askProv","claude"),model:load("askModel",""),open:false};
let askToken=load("askToken","");

/* pairing: the Mac shows a link like http://mac.local:8765/#pair=TOKEN; opening it on the phone stores the token */
{ const m=location.hash.match(/^#pair=([\w-]{10,64})$/); if(m){ askToken=m[1]; save("askToken",askToken); try{ history.replaceState(null,"","#"+page); }catch(e){} ASK.paired=true; } }

const askHeaders=()=>({"Content-Type":"application/json",...(askToken?{"X-Ask-Token":askToken}:{})});
async function askInfo(force){
  if(!force&&ASK.info&&Date.now()-ASK.infoAt<60e3) return ASK.info;
  try{ ASK.info=await (await fetch("/api/ask/info"+(force?"?refresh":""),{headers:askToken?{"X-Ask-Token":askToken}:{}})).json(); ASK.infoAt=Date.now();
    const o=ASK.info?.providers?.find(p=>p.id==="ollama"); if(o?.models?.length&&!o.models.includes(ASK.model)&&ASK.prov==="ollama") ASK.model=o.models[0]; }catch(e){}
  return ASK.info;
}
const askSkills=scope=>(ASK.info?.skills||ASK_SKILLS_FALLBACK).filter(s=>s.scope===scope);
const askProv=()=>{ const P=ASK.info?.providers||[]; return P.find(p=>p.id===ASK.prov&&p.available)||P.find(p=>p.available)||null; };
const askProvLabel=p=>!p?"No agent":p.id==="ollama"?`Ollama · ${(ASK.model||p.models?.[0]||"").replace(/:latest$/,"")}`:p.label;
const askAgentName=p=>!p?"":p.id==="ollama"?"Ollama":p.label;

/* inline entry points ------------------------------------------------------------------------- */
function askRow(t,scope){
  scope=scope||(t?"stock":"market");
  const S=askSkills(scope).slice(0,scope==="stock"?4:3);
  return `<div class="askrow"><span class="askl">${ic("spark",14)}Ask</span>${S.map(s=>`<button class="askchip" data-ask-skill="${esc(s.name)}" data-ask-scope="${scope}"${t?` data-ask-t="${esc(t)}"`:""}>${esc(s.label)}</button>`).join("")}${scope==="stock"?"":`<button class="askchip more" data-ask-scope="${scope}" aria-label="Ask your own question">Your question…</button>`}</div>`;
}
function askCmd(q){ return {cmd:"ask:free",label:`Ask “${q.length>60?q.slice(0,58)+"…":q}”`,hint:"Ask",icon:"spark",run:()=>openAsk({q,send:true})}; }
function withAsk(items,q){
  items=items.filter(x=>x.cmd!=="ask:free"); q=(q||"").trim(); if(q.length<3) return items; ASK.pendingQ=q;
  const question=/\?$/.test(q)||q.split(/\s+/).length>=3;
  return question?[askCmd(q),...items]:[...items,askCmd(q)];
}
function askDefaultCtx(){
  if(drawerOpen&&sel) return {scope:"stock",t:sel};
  if(page==="mine") return {scope:"portfolio",t:null};
  return {scope:"market",t:null};
}
const ctxLabel=c=>c.scope==="stock"?c.t:c.scope==="portfolio"?"Your stocks":"The market";

/* the sheet ------------------------------------------------------------------------------------ */
function askShell(){
  if($("#ask")) return;
  const el=document.createElement("aside"); el.className="ask"; el.id="ask"; el.setAttribute("aria-label","Ask"); el.setAttribute("aria-hidden","true");
  el.innerHTML=`<div class="ask-h"><div class="ask-ti">${ic("spark",18)}<b>Ask</b><button class="ask-ctx" id="askCtx" aria-haspopup="menu"></button></div>
    <div class="ask-hb"><button class="x" id="askNew" title="New conversation" aria-label="New conversation">${ic("compose",17)}</button><button class="x" id="askClose" aria-label="Close" title="Close (Esc)">${ic("close",18)}</button></div>
    <div class="ask-menu ctxm" id="askCtxM" role="menu" hidden></div></div>
  <div class="ask-b" id="askB"></div>
  <form class="ask-f" id="askF"><div class="ask-in"><textarea id="askQ" rows="1" placeholder="Ask anything" aria-label="Your question"></textarea><button class="ask-send" id="askSend" aria-label="Send">${ic("send",17)}</button></div>
    <div class="ask-meta"><button type="button" class="ask-prov" id="askProv" aria-haspopup="menu"></button><span class="ask-note" id="askNote"></span></div>
    <div class="ask-menu provm" id="askMenu" role="menu" hidden></div></form>`;
  document.body.appendChild(el);
  const Q=$("#askQ");
  Q.addEventListener("input",()=>{ Q.style.height="auto"; Q.style.height=Math.min(Q.scrollHeight,160)+"px"; });
  Q.addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); $("#askF").requestSubmit(); } });
  $("#askF").onsubmit=async e=>{ e.preventDefault(); const q=Q.value.trim();
    if(ASK.run){ askStop(); if(!q) return; await new Promise(r=>setTimeout(r,60)); }   // typing while it works steers: stop, then ask again with the new words
    if(!q) return; Q.value=""; Q.style.height="auto"; askSend({q}); };
  Q.addEventListener("input",()=>{ if(ASK.run) $("#askSend").innerHTML=Q.value.trim()?ic("send",17):ic("stop",15); });
  $("#askClose").onclick=closeAsk;
  $("#askNew").onclick=()=>{ askStop(); ASK.conv=[]; askRender(); Q.focus(); };
  $("#askProv").onclick=e=>{ e.stopPropagation(); $("#askCtxM").hidden=true; const m=$("#askMenu"); m.hidden=!m.hidden; if(!m.hidden) askProvMenu(); };
  $("#askCtx").onclick=e=>{ e.stopPropagation(); $("#askMenu").hidden=true; const m=$("#askCtxM"); m.hidden=!m.hidden; if(!m.hidden) askCtxMenu(); };
  el.addEventListener("click",e=>{ if(!e.target.closest(".ask-menu,#askProv,#askCtx")){ $("#askMenu").hidden=true; $("#askCtxM").hidden=true; } });
}
async function openAsk(o={}){
  askShell();
  const ctx=o.scope?{scope:o.scope,t:o.t||null}:askDefaultCtx();
  if(ctx.scope!==ASK.ctx.scope||ctx.t!==ASK.ctx.t){ if(!ASK.run) ASK.conv=[]; ASK.ctx=ctx; }
  ASK.open=true; const el=$("#ask"); el.classList.add("open"); el.setAttribute("aria-hidden","false"); document.body.classList.add("asking");
  askRender(); await askInfo(); askRender();
  if(o.skill||o.q&&o.send) askSend({skill:o.skill,q:o.q});
  else{ if(o.q) $("#askQ").value=o.q; if(innerWidth>760) setTimeout(()=>$("#askQ").focus(),60); }
}
function closeAsk(){ const el=$("#ask"); if(!el) return; ASK.open=false; el.classList.remove("open"); el.setAttribute("aria-hidden","true"); document.body.classList.remove("asking"); }

function askRender(){
  if(!$("#ask")) return;
  const c=ASK.ctx, info=ASK.info, p=askProv();
  $("#askCtx").innerHTML=`${esc(ctxLabel(c))}${ic("chev",14)}`;
  const who=p?`Ask ${askAgentName(p)}`:"Ask"; $("#askQ").placeholder=c.scope==="stock"?`${who} about ${c.t}`:c.scope==="portfolio"?`${who} about your stocks`:`${who} about the market`;
  $("#askProv").innerHTML=`<i class="pdot ${p?"on":""}"></i>${esc(askProvLabel(p))}${ic("chev",13)}`;
  $("#askNote").textContent=p?p.note:"";
  $("#askSend").innerHTML=ASK.run?ic("stop",15):ic("send",17); $("#askSend").setAttribute("aria-label",ASK.run?"Stop":"Send"); $("#askSend").classList.toggle("stop",!!ASK.run);
  const B=$("#askB");
  if(info&&!info.allowed){ B.innerHTML=`<div class="ask-empty"><div class="ask-hero">${ic("phone",26)}</div><h3>Ask runs on your Mac</h3><p>Answers come from the AI agents signed in on your Mac, such as Claude Code or Codex, so they use your own plan. To ask from this phone, open Ask on the Mac, tap the agent name at the bottom, then <b>Use on your phone</b>.</p></div>`; $("#askF").classList.add("off"); return; }
  $("#askF").classList.toggle("off",!!info&&!p);
  if(info&&(!p||ASK.view==="agents")){ B.innerHTML=askAgentsView(); return; }
  if(!ASK.conv.length){
    const S=askSkills(c.scope);
    B.innerHTML=`<div class="ask-empty"><h3>${c.scope==="stock"?`What do you want to know about ${esc(c.t)}?`:c.scope==="portfolio"?"What do you want to know about your stocks?":"What do you want to know about the market?"}</h3>
      <p>${p?`<b>${esc(askProvLabel(p))}</b> answers using OpenTicker's live data${p.tools?", and can look up more as it goes":""}.`:"Checking which agents are on this Mac…"}</p>
      <div class="ask-sk">${S.map(s=>`<button class="ask-skb" data-ask-skill="${esc(s.name)}">${ic("spark",14)}<span><b>${esc(s.label)}</b>${s.blurb||s.description?`<small>${esc(s.blurb||s.description.split(/ - |\. /)[0])}</small>`:""}</span></button>`).join("")}</div></div>`;
    return;
  }
  B.innerHTML=ASK.conv.map((m,i)=>m.role==="user"?`<div class="am u"><p>${esc(m.text)}</p></div>`
    :`<div class="am a${m.done?"":" live"}" data-i="${i}">${!m.done&&m.status&&!m.text?`<div class="as"><i class="dot on"></i>${esc(m.status)}…</div>`:""}
       <div class="md">${mdToHtml(m.text)}${!m.done&&m.text?`<span class="caret"></span>`:""}</div>
       ${m.error?`<div class="aerr">${esc(m.error)}</div>`:""}
       ${!m.done&&m.text&&m.status?`<div class="as sm"><i class="dot on"></i>${esc(m.status)}…</div>`:""}
       ${m.done&&m.text?`<div class="af"><span>${esc(m.by||"")}${m.secs?` · ${m.secs}s`:""}</span><button class="lnk" data-ask-copy="${i}">${ic("copy",13)}Copy</button></div>`:""}</div>`).join("");
  if(ASK.stick!==false) B.scrollTop=B.scrollHeight;
}
const ST={ready:["Ready","ok"],signin:["Not signed in","warn"],off:["Not running","warn"],missing:["Not installed",""]};
function askAgentsView(){
  const P=ASK.info?.providers||[], local=ASK.info?.local, cur=askProv();
  return `<div class="ask-agents"><h3>${cur?"Your agents":"Connect an agent"}</h3>
    <p>Ask works with an AI agent on your Mac, signed in with your own account. Each run bills that agent's plan, or costs nothing with OpenCode's free models or Ollama.</p>
    <ul class="agl">${P.map(p=>{ const [lab,cls]=ST[p.state]||["",""]; const act=p.state==="ready"?`<button class="btn ${cur?.id===p.id?"":"ghost"}" data-ag-use="${p.id}">${cur?.id===p.id?"In use":"Use"}</button>`
        :local?`<button class="btn ghost" data-ag-act="${p.state==="missing"?"install":"login"}" data-ag="${p.id}">${p.state==="missing"?"Install":p.id==="ollama"?(p.state==="off"?"Start":"Get a model"):"Sign in"}</button>`:"";
      return `<li><div><b>${esc(p.label)}</b><small>${esc(p.state==="ready"?p.note:p.why||p.note)}</small></div><span class="st ${cls}">${lab}</span>${act}</li>`; }).join("")}</ul>
    <div class="agcmd" id="agCmd" hidden></div>
    ${cur?`<button class="lnk" data-ag-done>Back to your conversation</button>`:`<button class="lnk" data-ag-refresh>Check again</button>`}</div>`;
}
document.addEventListener("click",async e=>{
  const b=e.target.closest("[data-ag-use],[data-ag-act],[data-ag-refresh],[data-ag-done],[data-ag-copy]"); if(!b) return;
  if(b.dataset.agUse){ ASK.prov=b.dataset.agUse; save("askProv",ASK.prov); ASK.view=null; return askRender(); }
  if(b.hasAttribute("data-ag-done")){ ASK.view=null; return askRender(); }
  if(b.hasAttribute("data-ag-refresh")){ b.textContent="Checking…"; await askInfo(true); return askRender(); }
  if(b.dataset.agCopy){ navigator.clipboard?.writeText(b.dataset.agCopy); b.innerHTML=ic("check",13)+"Copied"; return; }
  const p=(ASK.info?.providers||[]).find(x=>x.id===b.dataset.ag), action=b.dataset.agAct, cmd=p&&(action==="install"?p.install:p.login);
  if(!cmd) return;
  fetch("/api/ask/terminal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({provider:p.id,action})}).catch(()=>{});
  const box=$("#agCmd"); box.hidden=false;
  box.innerHTML=`<p><b>Terminal opened</b> to ${action==="install"?`install ${esc(p.label)}`:`set up ${esc(p.label)}`}. Follow it there, then come back and choose <b>Check again</b>.</p>
    <div class="pairl"><code>${esc(cmd)}</code><button class="btn ghost" data-ag-copy="${esc(cmd)}">${ic("copy",13)}Copy</button></div>
    <button class="lnk" data-ag-refresh>Check again</button>`;
});
function askProvMenu(){
  const info=ASK.info||{providers:[]}, m=$("#askMenu"), cur=askProv();
  const rows=[];
  for(const p of info.providers){
    if(p.id==="ollama"&&p.available){ for(const mod of p.models) rows.push(`<button role="menuitemradio" aria-checked="${cur?.id==="ollama"&&ASK.model===mod}" data-prov="ollama" data-model="${esc(mod)}"><b>Ollama · ${esc(mod.replace(/:latest$/,""))}</b><small>Free and private, on this Mac</small></button>`); continue; }
    rows.push(`<button role="menuitemradio" aria-checked="${cur?.id===p.id}" data-prov="${p.id}" ${p.available?"":"disabled"}><b>${esc(p.label)}</b><small>${esc(p.available?p.note:(ST[p.state]||[""])[0])}</small></button>`);
  }
  m.innerHTML=`<div class="mh">Answer with</div>${rows.join("")}<hr><button data-ask-agents>${ic("spark",15)}<b>Manage agents</b></button>${info.pair?`<button data-ask-pair>${ic("phone",15)}<b>Use on your phone</b></button><div class="pairbox" id="pairBox" hidden></div>`:""}`;
  m.querySelector("[data-ask-agents]").onclick=e=>{ e.stopPropagation(); m.hidden=true; ASK.view="agents"; askRender(); };
  m.querySelectorAll("[data-prov]").forEach(b=>b.onclick=()=>{ ASK.prov=b.dataset.prov; ASK.model=b.dataset.model||""; save("askProv",ASK.prov); save("askModel",ASK.model); m.hidden=true; askRender(); });
  const pb=m.querySelector("[data-ask-pair]"); if(pb) pb.onclick=e=>{ e.stopPropagation(); const box=$("#pairBox"); box.hidden=false;
    box.innerHTML=`<p>Open this link on your phone (same Wi-Fi). It pairs the phone so Ask works there too.</p><div class="pairl"><code>${esc(info.pair)}</code><button class="btn ghost" id="pairCopy">${ic("copy",13)}Copy</button></div><p class="hint">Send it with AirDrop or Messages. Anyone with this link on your Wi-Fi can use Ask, so keep it to yourself.</p>`;
    $("#pairCopy").onclick=ev=>{ ev.stopPropagation(); navigator.clipboard?.writeText(info.pair); $("#pairCopy").innerHTML=ic("check",13)+"Copied"; }; };
}
function askCtxMenu(){
  const m=$("#askCtxM"), opts=[];
  if(drawerOpen&&sel) opts.push({scope:"stock",t:sel});
  if(ASK.ctx.scope==="stock"&&ASK.ctx.t&&ASK.ctx.t!==sel) opts.push({scope:"stock",t:ASK.ctx.t});
  opts.push({scope:"portfolio",t:null},{scope:"market",t:null});
  m.innerHTML=`<div class="mh">Ask about</div>`+opts.map(o=>`<button role="menuitemradio" aria-checked="${o.scope===ASK.ctx.scope&&o.t===ASK.ctx.t}" data-cs="${o.scope}" data-ct="${o.t||""}"><b>${esc(ctxLabel(o))}</b><small>${o.scope==="stock"?(base?esc(nameOf(o.t)):""):o.scope==="portfolio"?"Positions, watchlist and your brief":"Funds, macro and today's movers"}</small></button>`).join("");
  m.querySelectorAll("[data-cs]").forEach(b=>b.onclick=()=>{ const c={scope:b.dataset.cs,t:b.dataset.ct||null}; m.hidden=true; if(c.scope!==ASK.ctx.scope||c.t!==ASK.ctx.t){ askStop(); ASK.conv=[]; ASK.ctx=c; } askRender(); });
}

/* streaming ------------------------------------------------------------------------------------ */
async function askSend({q,skill}){
  if(ASK.run) return;
  const p=askProv(); if(!p){ await askInfo(true); askRender(); if(!askProv()) return; }
  const prov=askProv(), c=ASK.ctx, sk=skill?askSkills(c.scope).find(s=>s.name===skill)||(ASK.info?.skills||[]).find(s=>s.name===skill):null;
  const text=q||(sk?(sk.prompt||sk.label).replace("{t}",c.t||"this stock"):"");
  const history=ASK.conv.filter(m=>m.text&&!m.error).map(m=>({role:m.role,text:m.text}));
  ASK.conv.push({role:"user",text});
  const msg={role:"assistant",text:"",status:"Starting",done:false,by:askProvLabel(prov)}; ASK.conv.push(msg); ASK.stick=true;
  const ctl=new AbortController(), t0=Date.now(); ASK.run=ctl; askRender();
  let toolSince=false, raf=0; const paint=()=>{ if(!raf) raf=requestAnimationFrame(()=>{ raf=0; askRender(); }); };
  try{
    const r=await fetch("/api/ask",{method:"POST",headers:askHeaders(),signal:ctl.signal,body:JSON.stringify({provider:prov.id,model:prov.id==="ollama"?ASK.model:undefined,scope:c.scope,t:c.t,skill:sk&&!q?sk.name:skill||undefined,q:q||undefined,history})});
    if(!r.ok){ const d=await r.json().catch(()=>({})); throw new Error(d.error||"Ask didn't answer."); }
    const rd=r.body.getReader(), dec=new TextDecoder(); let buf="";
    for(;;){
      const {value,done}=await rd.read(); if(done) break;
      buf+=dec.decode(value,{stream:true}); let k;
      while((k=buf.indexOf("\n\n"))>=0){
        const block=buf.slice(0,k); buf=buf.slice(k+2);
        const ev=(block.match(/^event: (.*)$/m)||[])[1]||"message", data=JSON.parse((block.match(/^data: (.*)$/m)||[])[1]||"{}");
        if(ev==="text"){ msg.text+=data.text; toolSince=false; }
        else if(ev==="status"){ msg.status=data.text; if(msg.text) toolSince=true; }
        else if(ev==="turn"){ if(toolSince){ msg.text=""; toolSince=false; } }   // drop "let me check…" narration once the agent has looked something up
        else if(ev==="meta"&&data.model) msg.by=`${askProvLabel(prov).split(" · ")[0]} · ${data.model}`;
        else if(ev==="error") msg.error=data.message;
        paint();
      }
    }
  }catch(e){ if(e.name!=="AbortError") msg.error=e.message==="Failed to fetch"?"Couldn't reach OpenTicker on your Mac.":e.message; }
  msg.done=true; msg.status=""; msg.secs=Math.round((Date.now()-t0)/1000); if(!msg.text&&!msg.error) msg.error=ctl.signal.aborted?"Stopped.":"No answer came back. Try again, or pick another agent.";
  ASK.run=null; askRender();
}
function askStop(){ if(ASK.run){ ASK.run.abort(); ASK.run=null; } }
/* "Ask about this": any insight or brief line gets a quiet Ask button; A while hovering does the same */
let askHover=null;
function askAbout(li){
  const clone=li.cloneNode(true); clone.querySelectorAll("button.askthis,.lnk,a,.bw").forEach(x=>x.remove());
  const text=clone.textContent.replace(/\s+/g," ").trim(); if(!text) return;
  const tk=li.querySelector("[data-open]")?.dataset.open||(li.closest("#drawer")?sel:null);
  openAsk(tk?{scope:"stock",t:tk,q:`Explain this: "${text}". Why does it matter, and what would change the picture?`,send:true}:{scope:page==="mine"?"portfolio":"market",q:`Explain this: "${text}". Why does it matter?`,send:true});
}
const ASK_SPOTS=".ins li,.brief li";
new MutationObserver(()=>{ document.querySelectorAll(ASK_SPOTS).forEach(li=>{ if(li.querySelector(":scope>.askthis")||li.closest("#ask")) return;
  const b=document.createElement("button"); b.className="askthis"; b.type="button"; b.title="Ask about this (A)"; b.setAttribute("aria-label","Ask about this"); b.innerHTML=ic("spark",14); li.appendChild(b); }); })
  .observe(document.body,{childList:true,subtree:true});
document.addEventListener("click",e=>{ const b=e.target.closest(".askthis"); if(!b) return; e.preventDefault(); e.stopPropagation(); askAbout(b.closest("li")); },true);
document.addEventListener("mouseover",e=>{ askHover=e.target.closest?.(ASK_SPOTS)||null; });

/* small, safe Markdown: escape first, then format; tickers become links ------------------------- */
const ASK_STOP=new Set("A I AI AM AN AND ARE AS AT BE BUT BY CEO CFO CPI DO EPS ETF EU FED FOR FY GDP GO HAS HE HOLD IF IN IPO IS IT ITS ME MY NO NOT NOW OF OK ON OR OUR PE PEG Q QOQ SO TO TTM UK UP US USA USD VS WE YOY YTD BUY SELL EV EBIT EBITDA ROE ROI SEC SMA RSI ATH API GPU CPU NEW ONE TWO ALL ANY CAN SEE".split(" "));
function mdInline(s){
  s=s.replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>").replace(/(^|[\s(])\*([^*\s][^*]*)\*/g,"$1<i>$2</i>")
     .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s;
}
function linkTickers(html,skip){
  if(!base?.px) return html;
  const seen=new Set(skip?[skip]:[]);   // link each ticker once, and never the one the conversation is about
  return html.replace(/(<a\b[^>]*>.*?<\/a>|<code>.*?<\/code>|<th>.*?<\/th>|<[^>]+>)|\b([A-Z]{2,5})\b/g,(m,tag,t)=>{
    if(tag||!t||!base.px[t]||ASK_STOP.has(t)||seen.has(t)) return m; seen.add(t); return `<button class="tkl" data-ask-open="${t}" title="Open ${t}">${t}</button>`; });
}
function mdToHtml(src){
  if(!src) return "";
  const L=esc(src).split("\n"), out=[]; let list=null, para=[];
  const flushP=()=>{ if(para.length){ out.push(`<p>${mdInline(para.join(" "))}</p>`); para=[]; } };
  const flushL=()=>{ if(list){ out.push(`<${list.t}>${list.items.map(x=>`<li>${mdInline(x)}</li>`).join("")}</${list.t}>`); list=null; } };
  for(let i=0;i<L.length;i++){
    const ln=L[i], tr=ln.trim();
    if(!tr){ flushP(); flushL(); continue; }
    if(/^\|.*\|$/.test(tr)&&i+1<L.length&&/^\|[\s:|-]+\|$/.test(L[i+1].trim())){
      flushP(); flushL(); const cells=r=>r.trim().replace(/^\||\|$/g,"").split("|").map(c=>c.trim());
      const head=cells(tr); i+=2; const rows=[]; while(i<L.length&&/^\|.*\|$/.test(L[i].trim())) rows.push(cells(L[i++])); i--;
      out.push(`<div class="mdt"><table><thead><tr>${head.map(h=>`<th>${mdInline(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${mdInline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`); continue;
    }
    let m;
    if((m=tr.match(/^(#{1,4})\s+(.*)$/))){ flushP(); flushL(); out.push(`<h4>${mdInline(m[2])}</h4>`); continue; }
    if((m=tr.match(/^[-*•]\s+(.*)$/))){ flushP(); if(list?.t!=="ul"){ flushL(); list={t:"ul",items:[]}; } list.items.push(m[1]); continue; }
    if((m=tr.match(/^\d+[.)]\s+(.*)$/))){ flushP(); if(list?.t!=="ol"){ flushL(); list={t:"ol",items:[]}; } list.items.push(m[1]); continue; }
    if(/^(-{3,}|\*{3,})$/.test(tr)){ flushP(); flushL(); out.push("<hr>"); continue; }
    if(list&&/^\s{2,}/.test(ln)){ list.items[list.items.length-1]+=" "+tr; continue; }
    flushL(); para.push(tr);
  }
  flushP(); flushL();
  return linkTickers(out.join(""),ASK.ctx.scope==="stock"?ASK.ctx.t:null);
}

/* wiring ---------------------------------------------------------------------------------------- */
document.addEventListener("click",e=>{
  const b=e.target.closest("[data-ask-skill],[data-ask-scope],[data-ask-open],[data-ask-copy],#askOpen"); if(!b) return;
  if(b.id==="askOpen") return ASK.open?closeAsk():openAsk();
  if(b.dataset.askOpen){ e.preventDefault(); if(innerWidth<=760) closeAsk(); return openStock(b.dataset.askOpen); }
  if(b.dataset.askCopy){ const m=ASK.conv[+b.dataset.askCopy]; navigator.clipboard?.writeText(m?.text||""); b.innerHTML=ic("check",13)+"Copied"; return; }
  if(b.closest("#ask")&&b.dataset.askSkill) return askSend({skill:b.dataset.askSkill});
  openAsk({scope:b.dataset.askScope,t:b.dataset.askT,skill:b.dataset.askSkill});
});
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"&&ASK.open){ if(!$("#askMenu").hidden||!$("#askCtxM").hidden){ $("#askMenu").hidden=true; $("#askCtxM").hidden=true; } else closeAsk(); e.stopImmediatePropagation(); e.preventDefault(); return; }
  if(e.target.matches("input,textarea,select")||e.metaKey||e.ctrlKey||e.altKey) return;
  if(e.key==="a"||e.key==="A"){ e.preventDefault(); if(askHover&&document.contains(askHover)&&!askHover.closest("#ask")) return askAbout(askHover); ASK.open?$("#askQ").focus():openAsk(); }
},true);
document.addEventListener("scroll",e=>{ const B=e.target; if(B.id==="askB") ASK.stick=B.scrollHeight-B.scrollTop-B.clientHeight<40; },true);

/* header button and command bar */
{ const bell=$("#bell"); if(bell&&!$("#askOpen")){ const b=document.createElement("button"); b.className="askbtn"; b.id="askOpen"; b.title="Ask an AI agent (A)"; b.setAttribute("aria-label","Ask an AI agent"); b.innerHTML=`${ic("spark",16)}<span>Ask</span>`; bell.before(b); } }
if(typeof COMMANDS!=="undefined"){
  COMMANDS.push({cmd:"ask:free",label:"Ask…",hint:"Ask",icon:"spark",keys:"ask ai agent claude codex question",run:()=>openAsk({q:ASK.pendingQ,send:!!ASK.pendingQ})});
  for(const s of ASK_SKILLS_FALLBACK) COMMANDS.push({cmd:"skill:"+s.name,label:s.scope==="stock"?`${s.label} (open stock)`:s.label,hint:"Ask",icon:"spark",keys:"ask "+s.label+" "+s.name.replace(/-/g," "),
    run:()=>{ if(s.scope==="stock"&&!(drawerOpen&&sel)) return openAsk({scope:"market"}); openAsk({scope:s.scope,t:s.scope==="stock"?sel:null,skill:s.name}); }});
}
askInfo();
if(ASK.paired) setTimeout(()=>openAsk(),400);

/* ---- Mac app: let the native window match the page (title bar color, light/dark) ---- */
(function(){
  const h=window.webkit&&webkit.messageHandlers&&webkit.messageHandlers.ot; if(!h) return;
  document.documentElement.classList.add("in-mac-app");
  const mq=matchMedia("(prefers-color-scheme: dark)");
  const post=()=>{ const t=document.documentElement.dataset.theme; h.postMessage({bg:getComputedStyle(document.body).backgroundColor,dark:t?t==="dark":mq.matches}); };
  post(); mq.addEventListener("change",post);
  new MutationObserver(post).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
})();
