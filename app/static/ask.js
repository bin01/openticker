/* OpenTicker: Tick, the analyst who lives in the app.
   A chat column docked beside the dashboard (a sheet on phones). Tick follows what you're looking at, takes
   @stocks and /skills, keeps every conversation on your Mac, and answers through an agent you already pay for
   (Claude Code, Codex, OpenCode) or a free local Ollama model.
   Shares globals with index.html: $, esc, ic, IC, load, save, base, sel, drawerOpen, page, openStock, COMMANDS, me, EARN, ret, idx, nameOf. */

Object.assign(IC,{
  spark:'<path d="M12 3l1.8 4.9L18.7 9.7 13.8 11.5 12 16.4 10.2 11.5 5.3 9.7 10.2 7.9z"/><path d="M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z"/>',
  send:'<path d="M12 19V5M5 12l7-7 7 7"/>', stop:'<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  copy:'<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>', check:'<path d="M20 6 9 17l-5-5"/>',
  compose:'<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>', phone:'<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
  chev:'<path d="m6 9 6 6 6-6"/>', chevr:'<path d="m9 6 6 6-6 6"/>', clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  dock:'<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M15 4v16"/>', retry:'<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/>',
  trash:'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>', at:'<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
  eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  chart:'<path d="M3 17l5-5 4 3 8-8"/><path d="M15 7h5v5"/>', term:'<path d="m5 8 4 4-4 4M12 16h7"/>', news:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h6M7 13h10"/>'});

const TICK="Tick";
/* skills ship with the server; this copy lets things render before /api/ask/info answers */
const ASK_SKILLS_FALLBACK=[
  {name:"stock-snapshot",label:"Quick take",scope:"stock"},{name:"explain-move",label:"Why is it moving?",scope:"stock"},
  {name:"earnings-preview",label:"Earnings",scope:"stock"},{name:"technical-analysis",label:"Read the chart",scope:"stock"},
  {name:"insider-trades",label:"Insider trades",scope:"stock"},{name:"bull-bear",label:"Bull vs bear",scope:"stock"},
  {name:"analyst-pulse",label:"What analysts say",scope:"stock"},{name:"valuation-check",label:"Is it expensive?",scope:"stock"},
  {name:"portfolio-checkup",label:"Check up on my portfolio",scope:"portfolio"},{name:"week-ahead",label:"What to watch this week",scope:"portfolio"},
  {name:"market-recap",label:"Market recap",scope:"market"},{name:"sector-rotation",label:"Which sectors lead?",scope:"market"},{name:"macro-check",label:"Macro backdrop",scope:"market"}];
const ASK={info:null,infoAt:0,ctx:{scope:"market",t:null},pinned:false,also:[],conv:[],chat:load("tickChat",""),run:null,
  prov:load("askProv","claude"),model:load("askModel",""),open:false,view:null,menu:null,mi:0,mood:"idle"};
let askToken=load("askToken","");

/* pairing: the Mac shows a link like http://mac.local:8765/#pair=TOKEN; opening it on the phone stores the token */
{ const m=location.hash.match(/^#pair=([\w-]{10,64})$/); if(m){ askToken=m[1]; save("askToken",askToken); try{ history.replaceState(null,"","#"+page); }catch(e){} ASK.paired=true; } }

const askHeaders=()=>({"Content-Type":"application/json",...(askToken?{"X-Ask-Token":askToken}:{})});
const askGet=async u=>(await fetch(u,{headers:askToken?{"X-Ask-Token":askToken}:{}})).json();
async function askInfo(force){
  if(!force&&ASK.info&&Date.now()-ASK.infoAt<60e3) return ASK.info;
  try{ ASK.info=await askGet("/api/ask/info"+(force?"?refresh":"")); ASK.infoAt=Date.now();
    const o=ASK.info?.providers?.find(p=>p.id==="ollama"); if(o?.models?.length&&!o.models.includes(ASK.model)&&ASK.prov==="ollama") ASK.model=o.models[0]; }catch(e){}
  return ASK.info;
}
const askSkills=scope=>(ASK.info?.skills||ASK_SKILLS_FALLBACK).filter(s=>s.scope===scope);
const askSkill=name=>(ASK.info?.skills||ASK_SKILLS_FALLBACK).find(s=>s.name===name);
const askProv=()=>{ const P=ASK.info?.providers||[]; return P.find(p=>p.id===ASK.prov&&p.available)||P.find(p=>p.available)||null; };
/* which model each agent uses: "" means the agent's own default */
const askModelOf=p=>!p?"":p.id==="ollama"?(ASK.model||p.models?.[0]||""):load("askModel."+p.id,"");
function prettyModel(m){
  if(!m) return ""; m=String(m).replace(/:latest$/,"").replace(/\[.*\]$/,"");
  let x=m.match(/claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/i);
  if(x) return x[1][0].toUpperCase()+x[1].slice(1)+" "+x[2]+(x[3]?"."+x[3]:"");
  if(/^(opus|sonnet|haiku)$/i.test(m)) return m[0].toUpperCase()+m.slice(1).toLowerCase();
  x=m.match(/^(?:openai\/)?gpt-([\w.]+?)(-codex)?$/i); if(x) return "GPT-"+x[1]+(x[2]?" Codex":"");
  return m.split("/").pop();
}
/* the model a choice resolves to, as far as we know: what the agent last reported for it, or its settings */
function askResolve(p,id){ if(!p) return ""; const S=p.seen||{};
  return S[id]||(id===""?(S[p.configured]||p.configured):(id===p.configured?S[""]:null))||id||""; }
function askModelName(p){ return p?prettyModel(askResolve(p,askModelOf(p))):""; }
const askEffortOf=p=>!p?"":load("askEffort."+p.id,"")||p.effort||"";
const EFFORT={low:"Low",medium:"Medium",high:"High",xhigh:"Extra high",max:"Max"};
const AG_SUB={claude:"Your Claude plan",codex:"Your ChatGPT plan",opencode:"Free models, or your own",ollama:"Free, runs on this Mac"};
const askProvLabel=p=>!p?"No agent":p.label+(askModelName(p)?` · ${askModelName(p)}`:"");
/* small marks so each agent is recognizable at a glance */
function agentIcon(id,s=16){
  const svg=(b,extra="")=>`<svg class="agi" viewBox="0 0 16 16" width="${s}" height="${s}" aria-hidden="true" ${extra}>${b}</svg>`;
  if(id==="claude") return svg(`<g fill="#D97757"><rect x="3" y="3.5" width="10" height="6.5"/><rect x="1" y="5.5" width="2" height="2"/><rect x="13" y="5.5" width="2" height="2"/><rect x="4" y="10" width="1" height="2.5"/><rect x="6" y="10" width="1" height="2.5"/><rect x="9" y="10" width="1" height="2.5"/><rect x="11" y="10" width="1" height="2.5"/></g><g fill="#1b1b1b"><rect x="5" y="5.5" width="1" height="1.6"/><rect x="10" y="5.5" width="1" height="1.6"/></g>`,'shape-rendering="crispEdges"');
  if(id==="codex") return svg(`<rect x=".5" y=".5" width="15" height="15" rx="4" fill="#0f0f0f" stroke="rgba(255,255,255,.18)"/><path d="m4.5 5.5 2.5 2.5-2.5 2.5M8.5 10.5h3" fill="none" stroke="#fff" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`);
  if(id==="opencode") return svg(`<rect x=".5" y=".5" width="15" height="15" rx="4" fill="#1d1d1d" stroke="rgba(255,255,255,.18)"/><rect x="4.5" y="4.5" width="7" height="7" fill="none" stroke="#fff" stroke-width="1.5"/><rect x="6.75" y="6.75" width="2.5" height="2.5" fill="#fff"/>`);
  if(id==="ollama") return svg(`<rect x=".5" y=".5" width="15" height="15" rx="4" fill="#fff" stroke="rgba(0,0,0,.14)"/><path d="M5.2 7.2V4.4c0-.8.9-1 1.2-.3l.5 1.6M10.8 7.2V4.4c0-.8-.9-1-1.2-.3l-.5 1.6M4.6 11.6c-.4-2.6 1-4.6 3.4-4.6s3.8 2 3.4 4.6" fill="none" stroke="#111" stroke-width="1.1" stroke-linecap="round"/><circle cx="6.6" cy="9.2" r=".6" fill="#111"/><circle cx="9.4" cy="9.2" r=".6" fill="#111"/>`);
  return "";
}
const askAgentName=p=>!p?"":p.id==="ollama"?"Ollama":p.label;
const newChatId=()=>{ const a=crypto.getRandomValues(new Uint8Array(9)); return "c"+Date.now().toString(36)+[...a].map(x=>(x%36).toString(36)).join(""); };

/* Tick: a small candlestick with eyes. Moods: idle (blinks), think (the candle stretches as if price is moving
   and the eyes read), done (a small hop), err (goes red for a moment). */
function tickFace(size=24,mood){
  const glint=size>=20;
  return `<span class="tick ${mood?"tk-"+mood:""}" style="--s:${size}px" aria-hidden="true"><svg viewBox="0 0 32 32" width="${size}" height="${size}">
    <g class="tk-lean"><path class="tk-w" d="M16 1.4v5M16 25.6v4.8"/><g class="tk-b"><rect class="tk-bd" x="5.2" y="6" width="21.6" height="19.8" rx="8.4"/>${glint?`<rect class="tk-sh" x="8" y="8.8" width="2.8" height="5.4" rx="1.4"/>`:""}
    <g class="tk-look"><g class="tk-e"><ellipse cx="12.4" cy="15.4" rx="2.4" ry="2.9"/><ellipse cx="19.6" cy="15.4" rx="2.4" ry="2.9"/>${glint?`<circle cx="13.2" cy="14.3" r=".9"/><circle cx="20.4" cy="14.3" r=".9"/>`:""}</g>
    <path class="tk-m" d="M14.2 20.8q1.8 1.6 3.6 0"/></g></g></g></svg></span>`;
}
/* Tick says what he's doing in a small bubble beside him */
let sayT=0;
function say(text,kind,ms){ const b=$("#askSay"); if(!b) return; clearTimeout(sayT);
  if(!text){ b.classList.remove("on"); return; }
  b.textContent=text; b.classList.toggle("err",kind==="err"); b.classList.add("on");
  if(ms) sayT=setTimeout(()=>b.classList.remove("on"),ms); }
const QUIPS=["Still here.","Numbers before adjectives.","I don't do hype.","Type @ to bring in another stock.","Ask me why something moved.","I read the live numbers, not the headlines."];
let quip=0;
/* Tick watches the cursor: his eyes follow it, and the one on the composer leans toward it */
let lookXY=null, lookRaf=0, lookT=0;
function tickLook(){ lookRaf=0;
  document.querySelectorAll(".tick.live").forEach(t=>{ const r=t.getBoundingClientRect(); if(!r.width) return;
    if(!lookXY){ t.style.removeProperty("--lx"); t.style.removeProperty("--ly"); t.style.removeProperty("--lean"); return; }
    const dx=lookXY[0]-(r.left+r.width/2), dy=lookXY[1]-(r.top+r.height*.48), d=Math.hypot(dx,dy)||1, f=Math.min(1,d/40);
    t.style.setProperty("--lx",(dx/d*2.6*f).toFixed(2)+"px"); t.style.setProperty("--ly",(dy/d*2.1*f).toFixed(2)+"px");
    if(t.closest(".perch,.tfloat")) t.style.setProperty("--lean",Math.max(-10,Math.min(10,dx/30)).toFixed(1)+"deg"); });
}
addEventListener("pointermove",e=>{ if(e.pointerType==="touch") return; lookXY=[e.clientX,e.clientY]; if(!lookRaf) lookRaf=requestAnimationFrame(tickLook);
  clearTimeout(lookT); lookT=setTimeout(()=>{ lookXY=null; tickLook(); },6000); },{passive:true});
document.documentElement.addEventListener("pointerleave",()=>{ lookXY=null; tickLook(); });
function setMood(m){ ASK.mood=m; document.querySelectorAll(".tick.live").forEach(t=>{ t.className="tick live tk-"+m; }); }

/* entry points on the page ------------------------------------------------------------------------ */
function askRow(t,scope){
  scope=scope||(t?"stock":"market");
  const S=askSkills(scope).slice(0,scope==="stock"?4:3);
  return `<div class="askrow"><span class="askl">${tickFace(16)}Ask ${TICK}</span>${S.map(s=>`<button class="askchip" data-ask-skill="${esc(s.name)}" data-ask-scope="${scope}"${t?` data-ask-t="${esc(t)}"`:""}>${esc(s.label)}</button>`).join("")}</div>`;
}
function askCmd(q){ return {cmd:"ask:free",label:`Ask ${TICK} “${q.length>60?q.slice(0,58)+"…":q}”`,hint:TICK,icon:"spark",run:()=>openAsk({q,send:true})}; }
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
const ctxName=c=>c.scope==="stock"?(base?nameOf(c.t)||"":""):c.scope==="portfolio"?"Positions, watchlist and brief":"Funds, sectors, macro, movers";

/* layout: docked beside the page on wide screens, a sheet elsewhere ------------------------------------- */
const DOCK_MIN=1100, TICK_W0=392, TICK_GAP=10, DRAWER_W=600;
const canDock=()=>innerWidth>=DOCK_MIN;
ASK.side=load("tickSide","right")==="left"?"left":"right";
ASK.w=+load("tickW",0)||TICK_W0;
/* Tick's width: 340px up to whatever leaves the page at least 560px */
function setTickW(w,keep){
  const max=Math.max(340,Math.min(760,innerWidth-560)); ASK.w=Math.round(Math.max(340,Math.min(max,w)));
  document.documentElement.style.setProperty("--tick-w",ASK.w+"px"); if(keep) save("tickW",ASK.w);
  /* no room for the page, the stock panel and Tick: the stock panel takes the whole space beside Tick */
  document.body.classList.toggle("tick-tight",document.body.classList.contains("tick-docked")&&innerWidth-ASK.w-TICK_GAP-DRAWER_W<380);
}
function applyDock(){
  const docked=ASK.open&&canDock();
  document.body.classList.toggle("tick-docked",docked);
  document.body.classList.toggle("tick-left",docked&&ASK.side==="left");
  setTickW(+load("tickW",0)||TICK_W0);
  document.body.classList.toggle("asking",ASK.open);
  const el=$("#ask"); if(el){ el.classList.toggle("open",ASK.open); el.classList.toggle("docked",docked); el.classList.toggle("left",ASK.side==="left"); el.setAttribute("aria-hidden",ASK.open?"false":"true"); }
  const b=$("#askOpen"); if(b) b.setAttribute("aria-pressed",ASK.open?"true":"false");
}
addEventListener("resize",()=>applyDock());

function askShell(){
  if($("#ask")) return;
  const el=document.createElement("aside"); el.className="ask"; el.id="ask"; el.setAttribute("aria-label",TICK); el.setAttribute("aria-hidden","true");
  el.innerHTML=`<div class="ask-grip" role="separator" aria-orientation="vertical" aria-label="Resize ${TICK}" title="Drag to resize. Double-click to reset." tabindex="0"></div><div class="ask-h"><b class="ask-nm">${TICK}</b><button type="button" class="ask-prov ask-ag" id="askProv" aria-haspopup="menu" aria-expanded="false"></button><button type="button" class="ask-prov" id="askMod" aria-haspopup="menu" aria-expanded="false"></button>
    <div class="ask-hb"><button class="x" id="askHist" title="Conversations" aria-label="Conversations">${ic("clock",16)}</button><button class="x" id="askNew" title="New conversation" aria-label="New conversation">${ic("compose",16)}</button><button class="x" id="askClose" aria-label="Hide ${TICK}" title="Hide ${TICK}">${ic(innerWidth<=760?"close":"dock",16)}</button></div></div>
  <div class="ask-menu provm" id="askMenu" role="menu" hidden></div>
  <div class="ask-b" id="askB"></div>
  <form class="ask-f" id="askF">
    <div class="perch">${tickFace(38,"idle")}<span class="say" id="askSay" role="status" aria-live="polite"></span></div>
    <div class="ask-in"><textarea id="askQ" rows="2" placeholder="Message ${TICK}" aria-label="Message ${TICK}" aria-autocomplete="list" aria-controls="askPop"></textarea>
      <div class="ask-row"><div class="ask-ctxr" id="askCtxR"></div><button class="ask-send" id="askSend" aria-label="Send">${ic("send",16)}</button></div></div>
    <div class="ask-menu pop" id="askPop" role="listbox" hidden></div>
    <div class="ask-menu ctxm" id="askCtxM" role="menu" hidden></div></form>`;
  document.body.appendChild(el);
  const me_=el.querySelector(".perch .tick"); me_.classList.add("live");
  me_.addEventListener("click",()=>{ if(ASK.run) return; setMood("happy"); say(QUIPS[quip++%QUIPS.length],null,2200); setTimeout(()=>{ if(!ASK.run) setMood("idle"); },1200); });
  const Q=$("#askQ");
  const grow=()=>{ Q.style.height="auto"; Q.style.height=Math.min(Q.scrollHeight,180)+"px"; };
  Q.addEventListener("input",()=>{ grow(); askPopUpdate(); paintSend(); });
  Q.addEventListener("keydown",e=>{
    if(!$("#askPop").hidden){
      const items=[...$("#askPop").querySelectorAll("[data-pi]")];
      if(e.key==="ArrowDown"||e.key==="ArrowUp"){ e.preventDefault(); ASK.mi=(ASK.mi+(e.key==="ArrowDown"?1:-1)+items.length)%items.length; markPop(); return; }
      if((e.key==="Enter"||e.key==="Tab")&&items[ASK.mi]){ e.preventDefault(); items[ASK.mi].click(); return; }
      if(e.key==="Escape"){ e.preventDefault(); e.stopPropagation(); hidePop(); return; }
    }
    if(e.key==="Backspace"&&!Q.value&&ASK.also.length){ ASK.also.pop(); renderCtx(); return; }
    if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){ e.preventDefault(); $("#askF").requestSubmit(); }
  });
  $("#askF").onsubmit=async e=>{ e.preventDefault(); const q=Q.value.trim();
    if(ASK.run){ askStop(); if(!q) return; await new Promise(r=>setTimeout(r,80)); }   // Enter while Tick works steers: stop, then go again with the new words
    if(!q) return; Q.value=""; grow(); hidePop(); askSend({q}); };
  $("#askClose").onclick=closeAsk;
  $("#askNew").onclick=()=>newChat();
  $("#askHist").onclick=()=>{ ASK.view=ASK.view==="history"?null:"history"; askRender(); };
  for(const [id,kind] of [["askProv","agent"],["askMod","model"]]) $("#"+id).onclick=e=>{ e.stopPropagation(); const m=$("#askMenu"), was=!m.hidden&&m.dataset.kind===kind;
    hideMenus(); if(was) return; m.dataset.kind=kind; m.hidden=false;
    m.style.left=Math.max(10,e.currentTarget.getBoundingClientRect().left-el.getBoundingClientRect().left-6)+"px"; e.currentTarget.setAttribute("aria-expanded","true"); kind==="agent"?askProvMenu():askModelMenu(); };
  el.addEventListener("click",e=>{ if(!e.target.closest(".ask-menu,#askProv,#askMod,.ctxchip")) hideMenus(); });
  tickGrip(el.querySelector(".ask-grip")); tickMove(el,el.querySelector(".ask-h"));
  $("#askB").addEventListener("scroll",e=>el.querySelector(".ask-h").classList.toggle("lined",e.target.scrollTop>4),{passive:true});
}
function tickGrip(g){
  g.addEventListener("pointerdown",e=>{ if(e.button!==0) return; e.preventDefault(); g.setPointerCapture(e.pointerId); document.body.classList.add("tick-resizing");
    const mv=ev=>setTickW(ASK.side==="left"?ev.clientX-TICK_GAP:innerWidth-ev.clientX-TICK_GAP);
    const up=()=>{ g.removeEventListener("pointermove",mv); g.removeEventListener("pointerup",up); g.removeEventListener("pointercancel",up);
      document.body.classList.remove("tick-resizing"); setTickW(ASK.w,true); dispatchEvent(new Event("resize")); };
    g.addEventListener("pointermove",mv); g.addEventListener("pointerup",up); g.addEventListener("pointercancel",up); });
  g.addEventListener("dblclick",()=>{ setTickW(TICK_W0,true); dispatchEvent(new Event("resize")); });
  g.addEventListener("keydown",e=>{ if(e.key!=="ArrowLeft"&&e.key!=="ArrowRight") return; e.preventDefault();
    const wider=(e.key==="ArrowLeft")===(ASK.side!=="left"); setTickW(ASK.w+(wider?24:-24),true); dispatchEvent(new Event("resize")); });
}
/* move: drag the header; Tick snaps to the nearer side of the window */
function tickSide(side,el){
  el=el||$("#ask"); if(!el||side===ASK.side){ return; }
  const r0=el.getBoundingClientRect();
  ASK.side=side; save("tickSide",side); el.style.transition="none"; el.style.transform=""; applyDock();
  const r1=el.getBoundingClientRect(); el.style.transform=`translateX(${r0.left-r1.left}px)`; void el.offsetWidth;
  el.style.transition="transform .34s cubic-bezier(.2,.8,.2,1)"; el.style.transform=""; setTimeout(()=>{ el.style.transition=""; },380);
  dispatchEvent(new Event("resize"));
}
function tickMove(el,H){
  H.addEventListener("pointerdown",e=>{
    if(e.button!==0||!el.classList.contains("docked")||e.target.closest("button,a,.ask-menu")) return;
    const x0=e.clientX; let moving=false, drop=null, side=ASK.side;
    H.setPointerCapture(e.pointerId);
    const mv=ev=>{ const dx=ev.clientX-x0;
      if(!moving){ if(Math.abs(dx)<6) return; moving=true; hideMenus(); el.classList.add("moving"); document.body.classList.add("tick-moving");
        drop=document.createElement("div"); drop.className="tick-drop"; document.body.appendChild(drop); }
      el.style.transform=`translateX(${dx}px)`; side=ev.clientX<innerWidth/2?"left":"right";
      drop.style.left=side==="left"?TICK_GAP+"px":"auto"; drop.style.right=side==="right"?TICK_GAP+"px":"auto"; };
    const up=()=>{ H.removeEventListener("pointermove",mv); H.removeEventListener("pointerup",up); H.removeEventListener("pointercancel",up);
      if(!moving) return; drop.remove(); document.body.classList.remove("tick-moving"); el.classList.remove("moving");
      if(side!==ASK.side) return tickSide(side,el);
      el.style.transition="transform .3s cubic-bezier(.2,.8,.2,1)"; el.style.transform=""; setTimeout(()=>{ el.style.transition=""; },320); };
    H.addEventListener("pointermove",mv); H.addEventListener("pointerup",up); H.addEventListener("pointercancel",up);
  });
}
function hideMenus(keep){ ["askMenu","askCtxM","askPop"].forEach(id=>{ if(id!==keep&&$("#"+id)) $("#"+id).hidden=true; }); if(keep!=="askMenu") ["#askProv","#askMod"].forEach(s=>$(s)?.setAttribute("aria-expanded","false")); }
function paintSend(){ const s=$("#askSend"), typing=!!$("#askQ").value.trim(), stop=!!ASK.run&&!typing;
  s.innerHTML=stop?ic("stop",13):ic("send",16); s.setAttribute("aria-label",stop?"Stop":"Send"); s.classList.toggle("stop",stop); s.classList.toggle("ready",typing&&!stop); }

async function openAsk(o={}){
  askShell();
  if(o.scope){ ASK.ctx={scope:o.scope,t:o.t||null}; ASK.pinned=true; } else if(!ASK.pinned) ASK.ctx=askDefaultCtx();
  ASK.open=true; save("tickOpen","1"); applyDock();
  if(ASK.view==="history"&&(o.skill||o.q)) ASK.view=null;
  askRender(); await askInfo(); await restoreChat(); askRender();
  if(o.skill||o.q&&o.send) askSend({skill:o.skill,q:o.q});
  else{ if(o.q) $("#askQ").value=o.q; if(innerWidth>760&&o.focus!==false) setTimeout(()=>$("#askQ").focus(),60); }
}
function closeAsk(){ ASK.open=false; save("tickOpen","0"); hideMenus(); applyDock(); setTimeout(tickLook,50); }

/* conversations ------------------------------------------------------------------------------------ */
async function restoreChat(){
  if(ASK.restored||!ASK.info?.allowed) return; ASK.restored=true;
  if(!ASK.chat) return;
  try{ const c=await askGet("/api/ask/chat?id="+encodeURIComponent(ASK.chat)); if(c&&c.messages&&!ASK.conv.length) ASK.conv=c.messages.map(m=>({...m,done:true})); }catch(e){}
}
function newChat(){ askStop(); ASK.conv=[]; ASK.chat=""; save("tickChat",""); ASK.view=null; ASK.also=[]; ASK.pinned=false; ASK.ctx=askDefaultCtx(); askRender(); $("#askQ").focus(); }
async function openChat(id){
  askStop();
  try{ const c=await askGet("/api/ask/chat?id="+encodeURIComponent(id)); if(!c.messages) return;
    ASK.chat=id; save("tickChat",id); ASK.conv=c.messages.map(m=>({...m,done:true})); ASK.view=null; ASK.stick=true;
    const lastU=[...ASK.conv].reverse().find(m=>m.role==="user"&&m.ctx); if(lastU){ ASK.ctx=lastU.ctx; ASK.pinned=true; }
    askRender(); }catch(e){}
}
function relTime(s){ const m=(Date.now()/1000-s)/60; if(m<1) return "Just now"; if(m<60) return Math.round(m)+" min ago"; if(m<1440) return Math.round(m/60)+" h ago";
  const d=new Date(s*1000); return m<10080?d.toLocaleDateString("en-US",{weekday:"long"}):d.toLocaleDateString("en-US",{month:"short",day:"numeric"}); }
async function historyView(){
  const B=$("#askB"); B.innerHTML=`<div class="hist"><h3>Conversations</h3><p class="hint">Loading…</p></div>`;
  let L=[]; try{ L=await askGet("/api/ask/chats"); }catch(e){}
  if(ASK.view!=="history") return;
  B.innerHTML=`<div class="hist"><div class="hist-h"><h3>Conversations</h3><button class="btn ghost" data-hist-new>${ic("compose",14)}New</button></div>
    ${L.length?`<ul>${L.map(c=>`<li class="${c.id===ASK.chat?"on":""}"><button class="hist-o" data-hist="${esc(c.id)}"><b>${esc(c.title)}</b><small>${relTime(c.updated)} · ${Math.ceil(c.n/2)} ${c.n>2?"questions":"question"}</small></button><button class="x" data-hist-del="${esc(c.id)}" aria-label="Delete conversation" title="Delete">${ic("trash",15)}</button></li>`).join("")}</ul>`
      :`<p class="hint">Nothing yet. Everything you ask ${TICK} is kept here, on your Mac.</p>`}</div>`;
}
document.addEventListener("click",async e=>{
  const b=e.target.closest("[data-hist],[data-hist-del],[data-hist-new]"); if(!b) return;
  if(b.dataset.hist) return openChat(b.dataset.hist);
  if(b.hasAttribute("data-hist-new")) return newChat();
  const id=b.dataset.histDel; const li=b.closest("li"); li.classList.add("gone");
  await fetch("/api/ask/chat/delete",{method:"POST",headers:askHeaders(),body:JSON.stringify({id})}).catch(()=>{});
  if(id===ASK.chat){ ASK.chat=""; save("tickChat",""); ASK.conv=[]; }
  setTimeout(()=>historyView(),180);
});

/* the context row: what Tick is looking at, plus any @stocks ------------------------------------------- */
function renderCtx(){
  const c=ASK.ctx, R=$("#askCtxR"); if(!R) return;
  R.innerHTML=`<button type="button" class="ctxchip main" aria-haspopup="menu" title="${ASK.pinned?"Pinned. Choose what Tick looks at":"Follows what you're looking at"}">${ic(ASK.pinned?"at":"eye",13)}<b>${esc(ctxLabel(c))}</b>${c.scope==="stock"&&ctxName(c)&&ctxName(c)!==c.t&&!ASK.also.length?`<small>${esc(trunc(ctxName(c),18))}</small>`:""}${ic("chev",12)}</button>`
    +ASK.also.map((t,i)=>`<span class="ctxchip"><b>${esc(t)}</b><button type="button" data-also-x="${i}" aria-label="Remove ${esc(t)}">×</button></span>`).join("");
  R.querySelector(".main").onclick=e=>{ e.stopPropagation(); hideMenus("askCtxM"); const m=$("#askCtxM"); m.hidden=!m.hidden; if(!m.hidden) askCtxMenu(); };
  R.querySelectorAll("[data-also-x]").forEach(x=>x.onclick=()=>{ ASK.also.splice(+x.dataset.alsoX,1); renderCtx(); });
}
function askCtxMenu(){
  const m=$("#askCtxM"), opts=[], here=askDefaultCtx();
  opts.push({...here,follow:true});
  if(ASK.ctx.scope==="stock"&&ASK.ctx.t&&ASK.ctx.t!==here.t) opts.push({scope:"stock",t:ASK.ctx.t});
  for(const o of [{scope:"portfolio",t:null},{scope:"market",t:null}]) if(!(here.scope===o.scope)) opts.push(o);
  m.innerHTML=`<div class="mh">${TICK} is looking at</div>`+opts.map((o,i)=>`<button role="menuitemradio" aria-checked="${o.follow?!ASK.pinned:ASK.pinned&&o.scope===ASK.ctx.scope&&o.t===ASK.ctx.t}" data-co="${i}"><b>${o.follow?`Whatever you're viewing`:esc(ctxLabel(o))}</b><small>${o.follow?`Now: ${esc(ctxLabel(o))}`:esc(ctxName(o))}</small></button>`).join("")
    +`<div class="mh">Tip</div><p class="mtip">Type <b>@</b> and a ticker to bring more stocks into the conversation.</p>`;
  m.querySelectorAll("[data-co]").forEach(b=>b.onclick=()=>{ const o=opts[+b.dataset.co]; ASK.pinned=!o.follow; ASK.ctx={scope:o.scope,t:o.t}; m.hidden=true; renderCtx(); renderPlaceholder(); if(!ASK.conv.length) askRender(); });
}
/* follow the page: when you open a stock or switch pages, Tick looks there too (unless pinned) */
setInterval(()=>{ if(!ASK.open) return;
  if(!ASK.conv.length&&!ASK.view&&!ASK.run&&noticings(ASK.ctx).length!==(ASK.notes||[]).length) askRender();   // the data arrived after Tick opened
  if(ASK.pinned) return; const c=askDefaultCtx(); if(c.scope!==ASK.ctx.scope||c.t!==ASK.ctx.t){ ASK.ctx=c; renderCtx(); renderPlaceholder(); if(!ASK.conv.length&&!ASK.view) askRender(); } },350);
function renderPlaceholder(){ const p=askProv(), c=ASK.ctx; const Q=$("#askQ"); if(!Q) return;
  Q.placeholder=ASK.conv.length?`Reply to ${TICK}`:`${c.scope==="stock"?`Ask ${TICK} about ${c.t}`:c.scope==="portfolio"?`Ask ${TICK} about your stocks`:`Ask ${TICK} about the market`}. Type @ to add a stock, / for a playbook.`; }

/* @ and / menus --------------------------------------------------------------------------------------- */
function popToken(){ const Q=$("#askQ"), v=Q.value.slice(0,Q.selectionStart);
  const at=v.match(/(^|\s)@([\w.^-]{0,12})$/); if(at) return {kind:"@",q:at[2],start:v.length-at[2].length-1};
  const sl=v.match(/^\/([\w-]{0,30})$/); if(sl) return {kind:"/",q:sl[1],start:0}; return null; }
function askPopUpdate(){
  const tk=popToken(), P=$("#askPop"); if(!tk){ hidePop(); return; }
  let items=[];
  if(tk.kind==="@"){
    const q=tk.q.toUpperCase(), ql=tk.q.toLowerCase(), mine=[...(me?.watch||[]),...(me?.positions||[]).map(p=>p.t)];
    const pool=[...new Set([...mine,...Object.keys(base?.px||{})])].filter(t=>/^[A-Z][A-Z.-]{0,5}$/.test(t));
    const scored=[]; for(const t of pool){ const n=(nameOf(t)||"").toLowerCase(); let s=!q?(mine.includes(t)?1:9):t===q?0:t.startsWith(q)?1+(t.length-q.length)*.01:ql.length>=2&&n.includes(ql)?3:null; if(s==null) continue; if(mine.includes(t)) s-=.5; scored.push([s,t]); }
    scored.sort((a,b)=>a[0]-b[0]);
    items=scored.slice(0,6).map(([,t])=>({k:"stock",t,label:t,sub:nameOf(t)||"",g:mine.includes(t)?"Your stocks":"Stocks"})).sort((a,b)=>(a.g==="Stocks")-(b.g==="Stocks"));
    if(!q||"my stocks portfolio".includes(ql)) items.push({k:"portfolio",label:"My stocks",sub:"Positions, watchlist and brief",g:"Bigger picture"});
    if(!q||"market".includes(ql)) items.push({k:"market",label:"The market",sub:"Funds, sectors, macro, movers",g:"Bigger picture"});
  }else{
    const ql=tk.q.toLowerCase(), sk=(ASK.info?.skills||ASK_SKILLS_FALLBACK);
    const order={[ASK.ctx.scope]:0}; const all=[...sk].sort((a,b)=>(order[a.scope]??1)-(order[b.scope]??1));
    const gn={stock:ASK.ctx.scope==="stock"?`Playbooks for ${ASK.ctx.t}`:"Playbooks for a stock",portfolio:"Playbooks for your stocks",market:"Playbooks for the market"};
    items=all.filter(s=>!ql||s.name.includes(ql)||s.label.toLowerCase().includes(ql)).slice(0,8).map(s=>({k:"skill",name:s.name,label:s.label,sub:s.blurb||(s.scope==="stock"&&ASK.ctx.scope!=="stock"?"Open a stock or type @ first":""),g:gn[s.scope],dis:s.scope==="stock"&&ASK.ctx.scope!=="stock"}));
    if("new".startsWith(ql)) items.push({k:"new",label:"New conversation",sub:"Start fresh. This one stays in history",g:"Conversation"});
  }
  if(!items.length){ hidePop(); return; }
  ASK.popItems=items; ASK.popTok=tk; ASK.mi=Math.min(ASK.mi,items.length-1); if(ASK.mi<0) ASK.mi=0;
  let g=null;
  P.innerHTML=items.map((it,i)=>`${it.g!==g?`<div class="mh">${esc(g=it.g)}</div>`:""}<button type="button" role="option" data-pi="${i}" ${it.dis?"aria-disabled=\"true\"":""}>${it.k==="stock"?`<span class="pk">${esc(it.label)}</span>`:`<b>${esc(it.label)}</b>`}<small>${esc(trunc(it.sub,48))}</small></button>`).join("")
    +`<div class="pf"><span><kbd>↑</kbd> <kbd>↓</kbd> choose</span><span><kbd>↵</kbd> ${tk.kind==="@"?"add":"run"}</span><span><kbd>esc</kbd> close</span></div>`;
  P.hidden=false; markPop();
  P.querySelectorAll("[data-pi]").forEach(b=>b.onmousedown=e=>{ e.preventDefault(); pickPop(+b.dataset.pi); });
  P.querySelectorAll("[data-pi]").forEach(b=>b.onclick=e=>{ e.preventDefault(); pickPop(+b.dataset.pi); });
}
function markPop(){ $("#askPop").querySelectorAll("[data-pi]").forEach((b,i)=>{ b.classList.toggle("on",i===ASK.mi); if(i===ASK.mi) b.scrollIntoView({block:"nearest"}); }); }
function hidePop(){ const P=$("#askPop"); if(P) P.hidden=true; ASK.mi=0; }
function pickPop(i){
  const it=ASK.popItems?.[i], tk=ASK.popTok, Q=$("#askQ"); if(!it||it.dis) return;
  const cut=()=>{ const end=Q.selectionStart; Q.value=(Q.value.slice(0,tk.start)+Q.value.slice(end)).replace(/^\s+/,""); };
  if(it.k==="stock"){ cut(); if(ASK.ctx.scope!=="stock"){ ASK.ctx={scope:"stock",t:it.t}; ASK.pinned=true; } else if(it.t!==ASK.ctx.t&&!ASK.also.includes(it.t)&&ASK.also.length<4) ASK.also.push(it.t); }
  else if(it.k==="portfolio"||it.k==="market"){ cut(); ASK.ctx={scope:it.k,t:null}; ASK.pinned=true; }
  else if(it.k==="skill"){ Q.value=""; hidePop(); return askSend({skill:it.name}); }
  else if(it.k==="new"){ Q.value=""; hidePop(); return newChat(); }
  hidePop(); renderCtx(); renderPlaceholder(); Q.focus(); if(!ASK.conv.length) askRender();
}

/* what Tick notices: a few lines from the live data, so a new conversation starts somewhere useful ---------- */
function noticings(c){
  const out=[]; if(!base?.px) return out;
  const r1=t=>{ try{ return ret(base.px[t],idx("1D")).r; }catch(e){ return null; } };
  const today=new Date().toISOString().slice(0,10), soon=new Date(Date.now()+8*864e5).toISOString().slice(0,10);
  const day=d=>d===today?"today":"on "+new Date(d+"T12:00:00Z").toLocaleDateString("en-US",{weekday:"long",timeZone:"UTC"});
  if(c&&c.scope==="stock"){
    const t=c.t, r=r1(t), spy=r1("SPY");
    if(r!=null){ const vs=spy==null?"":Math.sign(r)!==Math.sign(spy)?`, while SPY went the other way`:Math.abs(r)>Math.abs(spy)*2&&Math.abs(r)>.01?`, well beyond SPY's ${pct(Math.abs(spy),1).replace(/^[+−]/,"")}`:", about in line with the market";
      out.push({dir:cls(r),text:`<b>${esc(t)}</b> is ${r>=0?"up":"down"} <b class="${cls(r)}">${pct(r,1).replace(/^[+−]/,"")}</b> today${vs}.`,act:"Why is it moving?",go:{scope:"stock",t,skill:"explain-move"}}); }
    const e=EARN?.[t]; if(e&&e.date&&e.reported==null&&e.date>=today&&e.date<=soon) out.push({dir:"ev",text:`Reports earnings ${day(e.date)}.`,act:"Preview it",go:{scope:"stock",t,skill:"earnings-preview"}});
    return out;
  }
  const mine=[...new Set([...(me?.positions||[]).map(p=>p.t),...(me?.watch||[])])];
  const movers=mine.map(t=>({t,r:r1(t)})).filter(x=>x.r!=null&&Math.abs(x.r)>=.015).sort((a,b)=>Math.abs(b.r)-Math.abs(a.r));
  if(movers[0]){ const m=movers[0]; out.push({dir:cls(m.r),text:`<b>${esc(m.t)}</b> is ${m.r>0?"up":"down"} <b class="${cls(m.r)}">${pct(m.r,1).replace(/^[+−]/,"")}</b> today${movers[1]?`, the biggest move in your stocks`:""}.`,act:"Want the why?",go:{scope:"stock",t:m.t,skill:"explain-move"}}); }
  const spy=r1("SPY"); if(spy!=null){
    const hold=base.funds?.SPY?.holdings||[]; let up=0,n=0; for(const h of hold){ const r=r1(h.t); if(r!=null){ n++; if(r>0) up++; } }
    const breadth=n?up/n:null, narrow=breadth!=null&&((spy>0&&breadth<.45)||(spy<0&&breadth>.55));
    out.push({dir:cls(spy),text:`SPY is ${spy>=0?"up":"down"} <b class="${cls(spy)}">${pct(spy,2).replace(/^[+−]/,"")}</b>${breadth!=null?narrow?`, but only ${Math.round(breadth*100)}% of S&amp;P 500 stocks ${spy>=0?"rose":"fell"}. A narrow day.`:`, and ${Math.round(breadth*100)}% of S&amp;P 500 stocks rose.`:"."}`,act:"Recap the day",go:{scope:"market",skill:"market-recap"}});
  }
  const er=mine.map(t=>({t,...(EARN?.[t]||{})})).filter(e=>e.date&&e.reported==null&&e.date>=today&&e.date<=soon).sort((a,b)=>a.date<b.date?-1:1)[0];
  if(er){ out.push({dir:"ev",text:`<b>${esc(er.t)}</b> reports earnings ${day(er.date)}.`,act:"Preview it",go:{scope:"stock",t:er.t,skill:"earnings-preview"}}); }
  return out.slice(0,3);
}
function greeting(){ const h=new Date().getHours(); return h<5?"Up late.":h<12?"Good morning.":h<17?"Good afternoon.":"Good evening."; }

/* rendering ------------------------------------------------------------------------------------------ */
function stepIcon(t){ return /^Searching/.test(t)?"search":/web page/.test(t)?"globe":/news/.test(t)?"news":/^Checking/.test(t)?"chart":"term"; }
const stepRow=(t,now)=>`<div class="stp${now?" now":""}"><i class="sb">${now?"":ic(stepIcon(t),12)}</i><span>${esc(t)}</span></div>`;
const dur=s=>s<60?s+"s":Math.floor(s/60)+"m "+(s%60)+"s";
function askRender(){
  if(!$("#ask")) return;
  const c=ASK.ctx, info=ASK.info, p=askProv();
  renderCtx(); renderPlaceholder();
  const pv=$("#askProv"); let mn=askModelName(p);
  pv.innerHTML=p?`${agentIcon(p.id,16)}${ic("chev",12)}`:`<i class="pdot"></i><span>${info?"Choose an agent":"Connecting"}</span>${ic("chev",12)}`;
  pv.title=p?`${TICK} thinks with ${p.label}. ${p.note}.`:""; pv.setAttribute("aria-label",p?`Agent: ${p.label}`:"Choose an agent");
  const md=$("#askMod"); md.hidden=!p;
  if(p){ mn=mn||"Default model"; const ef=p.efforts?.length&&askEffortOf(p); md.innerHTML=`<span>${esc(mn)}</span>${ic("chev",12)}`;
    md.title=`Model: ${mn}${ef?`, ${EFFORT[ef]||ef} effort`:""}`; md.setAttribute("aria-label",md.title); }
  $("#askHist").classList.toggle("on",ASK.view==="history");
  paintSend();
  if(ASK.run) say((ASK.conv[ASK.conv.length-1]?.status||"Thinking")+"…");
  const B=$("#askB");
  if(info&&!info.allowed){ B.innerHTML=`<div class="tk-hi"><p class="tk-greet">${TICK} lives on your Mac.</p><p class="tk-sub">${TICK} answers with the AI agents signed in on your Mac, such as Claude Code or Codex, so they use your own plan. To talk to ${TICK} from this phone, open OpenTicker on the Mac, click the agent name at the top of this panel, then <b>Use on your phone</b>.</p></div>`; $("#askF").classList.add("off"); return; }
  $("#askF").classList.toggle("off",!!info&&!p);
  if(ASK.view==="history") return void historyView();
  if(info&&(!p||ASK.view==="agents")){ B.innerHTML=askAgentsView(); return; }
  if(!ASK.conv.length){
    const S=askSkills(c.scope), N=noticings(c);
    const head=c.scope==="stock"?`Let's look at ${esc(c.t)}.`:c.scope==="portfolio"?"Let's look at your stocks.":N.length?"Here's what I'm noticing.":"Where shall we start?";
    B.innerHTML=`<div class="tk-hi"><p class="tk-greet">${greeting()} ${head}</p>
      <p class="tk-sub">I read OpenTicker's live numbers and think with ${p?esc(askAgentName(p)):"your own AI agent"}. Ask anything, or start here.</p>
      ${N.length?`<div class="notes">${N.map((n,i)=>`<button class="nt" data-nt="${i}"><i class="${n.dir||""}"></i><span>${n.text}</span><em>${esc(n.act)}${ic("chevr",12)}</em></button>`).join("")}</div>`:""}
      <div class="tk-lab">${c.scope==="stock"?`Playbooks for ${esc(c.t)}`:c.scope==="portfolio"?"Playbooks for your stocks":"Playbooks for the market"}</div>
      <div class="pbs">${S.map(s=>`<button class="pb" data-ask-skill="${esc(s.name)}" title="${esc(s.blurb||"")}">${esc(s.label)}</button>`).join("")}</div></div>`;
    ASK.notes=N; return;
  }
  let lastCtx=null;
  B.innerHTML=ASK.conv.map((m,i)=>{
    if(m.role==="user"){ const k=m.ctx?ctxLabel(m.ctx):null, show=k&&k!==lastCtx; lastCtx=k||lastCtx;
      return `${show?`<div class="ctxsep"><span>${esc(k)}</span></div>`:""}<div class="am u"><p>${esc(m.text)}</p></div>`; }
    const live=!m.done, steps=(m.steps||[]).filter(Boolean);
    return `<div class="am a${live?" live":""}" data-i="${i}">
      ${live&&!m.text?`<div class="log">${steps.slice(-5).map((s,k,a)=>stepRow(s,k===a.length-1)).join("")||stepRow(m.status||"Thinking",true)}</div>`
        :steps.length?`<details class="how"><summary>How I got there${ic("chevr",13)}</summary><div class="log">${steps.map(s=>stepRow(s)).join("")}</div></details>`:""}
      <div class="md">${mdToHtml(m.text,m)}${live&&m.text?`<span class="caret"></span>`:""}</div>
      ${m.error?`<div class="aerr">${esc(m.error)}</div>`:""}
      ${m.done?`<div class="af">${m.text?`<button class="ib" data-ask-copy="${i}" title="Copy" aria-label="Copy">${ic("copy",14)}</button>`:""}${i===ASK.conv.length-1?`<button class="ib" data-ask-retry title="Ask again" aria-label="Ask again">${ic("retry",14)}</button>`:""}<span>${m.secs!=null?`Worked for <b>${dur(m.secs)}</b>`:""}${m.by?` · ${esc(m.by.split(" · ").map((x,j)=>j?prettyModel(x):x).join(" · "))}`:""}</span></div>`:""}</div>`;
  }).join("");
  drawCharts(B);
  if(ASK.stick!==false) B.scrollTop=B.scrollHeight;
}
document.addEventListener("click",e=>{ const b=e.target.closest("[data-nt]"); if(!b) return; const n=ASK.notes?.[+b.dataset.nt]; if(!n) return; ASK.ctx={scope:n.go.scope,t:n.go.t||null}; ASK.pinned=n.go.scope==="stock"; askSend({skill:n.go.skill}); });

const ST={ready:["Ready","ok"],signin:["Not signed in","warn"],off:["Not running","warn"],missing:["Not installed",""]};
function askAgentsView(){
  const P=ASK.info?.providers||[], local=ASK.info?.local, cur=askProv();
  return `<div class="ask-agents">${cur?"":tickFace(48,"idle")}<h3>${cur?`Who answers as ${TICK}`:`Give ${TICK} a brain`}</h3>
    <p>${TICK} thinks with an AI agent on your Mac, signed in with your own account. Each answer bills that agent's plan, or costs nothing with OpenCode's free models or Ollama.</p>
    <ul class="agl">${P.map(p=>{ const [lab,cls]=ST[p.state]||["",""]; const act=p.state==="ready"?`<button class="btn ${cur?.id===p.id?"":"ghost"}" data-ag-use="${p.id}">${cur?.id===p.id?"In use":"Use"}</button>`
        :local?`<button class="btn ghost" data-ag-act="${p.state==="missing"?"install":"login"}" data-ag="${p.id}">${p.state==="missing"?"Install":p.id==="ollama"?(p.state==="off"?"Start":"Get a model"):"Sign in"}</button>`:"";
      return `<li><div><b>${esc(p.label)}</b><small>${esc(p.state==="ready"?p.note:p.why||p.note)}</small></div><span class="st ${cls}">${lab}</span>${act}</li>`; }).join("")}</ul>
    <div class="agcmd" id="agCmd" hidden></div>
    ${cur?`<button class="lnk" data-ag-done>Back to the conversation</button>`:`<button class="lnk" data-ag-refresh>Check again</button>`}</div>`;
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
function askPair(m,info){
  const pb=m.querySelector("[data-ask-pair]"); if(pb) pb.onclick=e=>{ e.stopPropagation(); const box=$("#pairBox"); box.hidden=false;
    box.innerHTML=`<p>Open this link on your phone (same Wi-Fi). It pairs the phone so ${TICK} works there too.</p><div class="pairl"><code>${esc(info.pair)}</code><button class="btn ghost" id="pairCopy">${ic("copy",13)}Copy</button></div><p class="hint">Send it with AirDrop or Messages. Anyone with this link on your Wi-Fi can talk to ${TICK}, so keep it to yourself.</p>`;
    $("#pairCopy").onclick=ev=>{ ev.stopPropagation(); navigator.clipboard?.writeText(info.pair); $("#pairCopy").innerHTML=ic("check",13)+"Copied"; }; };
}
/* the agent menu: who Tick thinks with */
function askProvMenu(){
  const info=ASK.info||{providers:[]}, m=$("#askMenu"), cur=askProv();
  m.className="ask-menu provm agm";
  m.innerHTML=info.providers.map(p=>{ const on=cur?.id===p.id, ok=p.available;
    return `<button role="menuitemradio" class="agrow${on?" on":""}" aria-checked="${on}" ${ok?`data-agent="${p.id}"`:`data-agent-setup="${p.id}"`}>
      <span class="agic">${agentIcon(p.id,20)}</span><span class="agt"><b>${esc(p.label)}</b><small>${esc(ok?AG_SUB[p.id]||p.note:(ST[p.state]||["Not ready"])[0])}</small></span>
      ${on?`<span class="agk">${ic("check",15)}</span>`:ok?"":`<span class="agk"><i class="ring"></i>${ic("chevr",14)}</span>`}</button>`; }).join("")
    +`<hr><button class="mi" data-ask-agents>${ic("spark",15)}<b>Manage agents</b></button>${info.pair?`<button class="mi" data-ask-pair>${ic("phone",15)}<b>Use on your phone</b></button><div class="pairbox" id="pairBox" hidden></div>`:""}`;
  m.querySelectorAll("[data-ask-agents],[data-agent-setup]").forEach(b=>b.onclick=e=>{ e.stopPropagation(); hideMenus(); ASK.view="agents"; askRender(); });
  m.querySelectorAll("[data-agent]").forEach(b=>b.onclick=()=>{ ASK.prov=b.dataset.agent; save("askProv",ASK.prov); hideMenus(); askRender(); });
  askPair(m,info);
}
/* the model menu: which model, and how hard it thinks */
function askModelMenu(more){
  const p=askProv(), m=$("#askMenu"); if(!p) return;
  m.className="ask-menu provm mdm";
  const ch=askModelOf(p), row=(id,name,tag,on)=>`<button role="menuitemradio" class="mrow" aria-checked="${on}" data-model="${esc(id)}"><b>${esc(name)}</b>${tag?`<small>${esc(tag)}</small>`:""}${on?`<i class="mdot"></i>`:""}</button>`;
  let h="";
  if(p.id==="claude"){
    const fam=x=>(String(x||"").toLowerCase().match(/opus|sonnet|haiku|fable/)||[""])[0];
    const active=ch||fam(p.configured)||fam(askResolve(p,""));
    const C=(p.choices||[]).filter(c=>c[0]), TAG={opus:"Best",sonnet:"Faster",haiku:"Fastest"};
    const nm=id=>prettyModel(askResolve(p,id))||prettyModel(id);
    const [top,...rest]=C, open=more||rest.some(c=>c[0]===active);
    if(!active) h+=row("","Claude Code's default","",true);   // until it tells us which model that is
    h+=row(top[0],nm(top[0]),TAG[top[0]],active===top[0]);
    h+=`<button class="mmore" data-more aria-expanded="${open}"><b>More models</b>${ic("chev",12)}</button>`;
    if(open) h+=rest.map(c=>row(c[0],nm(c[0]),TAG[c[0]],active===c[0])).join("");
  } else if(p.id==="ollama"){
    h+=(p.choices||[]).map(c=>row(c[0],prettyModel(c[0]),"",ch===c[0])).join("");
  } else {
    h+=row("",askModelName(p)||"Default",`Set in ${p.label}`,true);
  }
  if(p.efforts?.length){ const ef=askEffortOf(p);
    h+=`<div class="mh">Effort</div>`+p.efforts.map(e=>`<button role="menuitemradio" class="mrow" aria-checked="${ef===e}" data-effort="${e}"><b>${EFFORT[e]||e}</b>${ef===e?`<i class="mdot"></i>`:""}</button>`).join(""); }
  m.innerHTML=h;
  m.querySelector("[data-more]")?.addEventListener("click",e=>{ e.stopPropagation(); askModelMenu(e.currentTarget.getAttribute("aria-expanded")!=="true"); });
  m.querySelectorAll("[data-model]").forEach(b=>b.onclick=e=>{ e.stopPropagation(); const mod=b.dataset.model;
    if(p.id==="ollama"){ ASK.model=mod; save("askModel",mod); } else if(p.id==="claude") save("askModel."+p.id,mod);
    askRender(); askModelMenu(true); });
  m.querySelectorAll("[data-effort]").forEach(b=>b.onclick=e=>{ e.stopPropagation(); save("askEffort."+p.id,b.dataset.effort); askRender(); askModelMenu(); });
}

/* streaming ------------------------------------------------------------------------------------------ */
async function askSend({q,skill,retry}){
  if(ASK.run) return;
  if(!askProv()){ await askInfo(true); askRender(); if(!askProv()) return; }
  if(!ASK.chat){ ASK.chat=newChatId(); save("tickChat",ASK.chat); }
  ASK.view=null;
  const prov=askProv(), c={...ASK.ctx}, also=[...ASK.also], sk=skill?askSkill(skill):null;
  if(sk&&sk.scope!==c.scope&&sk.scope!=="stock"){ c.scope=sk.scope; c.t=null; }
  const shown=q||(sk?(sk.prompt||sk.label).replace("{t}",c.t||"this stock"):"");
  const full=q&&also.length?`${q}\n\n(Also bring in: ${also.join(", ")}. Use openticker for their data.)`:q;
  const history=ASK.conv.filter(m=>m.text&&!m.error).map(m=>({role:m.role,text:m.text})).slice(-6);
  if(!retry) ASK.conv.push({role:"user",text:shown,ctx:c,skill:sk?.name||null});
  const msg={role:"assistant",text:"",status:"Gathering the data",steps:[],done:false,by:askProvLabel(prov)}; ASK.conv.push(msg); ASK.stick=true;
  ASK.also=[];
  const ctl=new AbortController(), t0=Date.now(); ASK.run=ctl; setMood("think"); askRender();
  let toolSince=false, raf=0, started=false; const paint=()=>{ if(!raf) raf=requestAnimationFrame(()=>{ raf=0; askRender(); }); };
  try{
    const r=await fetch("/api/ask",{method:"POST",headers:askHeaders(),signal:ctl.signal,body:JSON.stringify({provider:prov.id,model:askModelOf(prov)||undefined,effort:(prov.efforts?.length&&askEffortOf(prov))||undefined,scope:c.scope,t:c.t,
      skill:sk&&!q?sk.name:undefined,q:full||undefined,show:shown,history,chat:ASK.chat})});
    if(!r.ok){ const d=await r.json().catch(()=>({})); throw new Error(d.error||`${TICK} didn't answer.`); }
    const rd=r.body.getReader(), dec=new TextDecoder(); let buf="";
    for(;;){
      const {value,done}=await rd.read(); if(done) break;
      buf+=dec.decode(value,{stream:true}); let k;
      while((k=buf.indexOf("\n\n"))>=0){
        const block=buf.slice(0,k); buf=buf.slice(k+2);
        const ev=(block.match(/^event: (.*)$/m)||[])[1]||"message", data=JSON.parse((block.match(/^data: (.*)$/m)||[])[1]||"{}");
        if(ev==="text"){ msg.text+=data.text; toolSince=false; msg.status="Writing"; }
        else if(ev==="status"){ msg.status=data.text; if(started) msg.steps.push(data.text); else if(/^Asking /.test(data.text)){ started=true; msg.status="Reading the numbers"; } if(msg.text) toolSince=true; }
        else if(ev==="turn"){ if(toolSince){ msg.text=""; toolSince=false; } }   // drop "let me check…" narration once the agent has looked something up
        else if(ev==="meta"&&data.model){ msg.by=`${prov.label} · ${data.model}`; const k=askModelOf(prov); prov.seen={...(prov.seen||{}),[k]:data.model}; }
        else if(ev==="error") msg.error=data.message;
        paint();
      }
    }
  }catch(e){ if(e.name!=="AbortError") msg.error=e.message==="Failed to fetch"?"Couldn't reach OpenTicker on your Mac.":e.message; }
  msg.done=true; msg.status=""; msg.secs=Math.round((Date.now()-t0)/1000);
  if(!msg.text&&!msg.error) msg.error=ctl.signal.aborted?"Stopped.":"No answer came back. Try again, or pick another agent.";
  ASK.run=null; const bad=msg.error&&!msg.text; setMood(bad?"err":"done"); askRender();
  say(bad?(ctl.signal.aborted?"Stopped.":"I hit a snag."):`Done in ${dur(msg.secs)}.`,bad?"err":null,2400);
  setTimeout(()=>{ if(!ASK.run) setMood("idle"); },1600);
  if(!ASK.open||document.hidden) tickPing(msg);
}
function askStop(){ if(ASK.run){ ASK.run.abort(); ASK.run=null; } }
function askRetry(){ if(ASK.run) return; const i=ASK.conv.length-1; if(ASK.conv[i]?.role!=="assistant") return; ASK.conv.pop(); const u=ASK.conv[ASK.conv.length-1]; if(!u) return;
  ASK.ctx=u.ctx||ASK.ctx; askSend(u.skill?{skill:u.skill,retry:true}:{q:u.text,retry:true}); }
/* when an answer lands while Tick is hidden, the header button says so */
function tickPing(m){ if(ASK.open) return; const b=$("#askOpen"), t=m.error?`${TICK} hit a problem`:`${TICK} has an answer`;
  if(b){ b.classList.add("ping"); b.title=t; }
  const f=$("#tickFloat"); if(f){ f.classList.add("ping"); $("#tfSay").textContent=m.error?"I hit a snag.":"I have an answer."; } }

/* "Ask Tick about this": any insight or brief line gets a quiet button; A while hovering does the same */
let askHover=null;
function askAbout(li){
  const clone=li.cloneNode(true); clone.querySelectorAll("button.askthis,.lnk,a,.bw").forEach(x=>x.remove());
  const text=clone.textContent.replace(/\s+/g," ").trim(); if(!text) return;
  const tk=li.querySelector("[data-open]")?.dataset.open||(li.closest("#drawer")?sel:null);
  openAsk(tk?{scope:"stock",t:tk,q:`Explain this: "${text}". Why does it matter, and what would change the picture?`,send:true}:{scope:page==="mine"?"portfolio":"market",q:`Explain this: "${text}". Why does it matter?`,send:true});
}
const ASK_SPOTS=".ins li,.brief li";
new MutationObserver(()=>{ document.querySelectorAll(ASK_SPOTS).forEach(li=>{ if(li.querySelector(":scope>.askthis")||li.closest("#ask")) return;
  const b=document.createElement("button"); b.className="askthis"; b.type="button"; b.title=`Ask ${TICK} about this (A)`; b.setAttribute("aria-label",`Ask ${TICK} about this`); b.innerHTML=tickFace(16); li.appendChild(b); }); })
  .observe(document.body,{childList:true,subtree:true});
document.addEventListener("click",e=>{ const b=e.target.closest(".askthis"); if(!b) return; e.preventDefault(); e.stopPropagation(); askAbout(b.closest("li")); },true);
document.addEventListener("mouseover",e=>{ askHover=e.target.closest?.(ASK_SPOTS)||null; });

/* small, safe Markdown: escape first, then format; tickers become links ----------------------------------- */
const ASK_STOP=new Set("A I AI AM AN AND ARE AS AT BE BUT BY CEO CFO CPI DO EPS ETF EU FED FOR FY GDP GO HAS HE HOLD IF IN IPO IS IT ITS ME MY NO NOT NOW OF OK ON OR OUR PE PEG Q QOQ SO TO TTM UK UP US USA USD VS WE YOY YTD BUY SELL EV EBIT EBITDA ROE ROI SEC SMA RSI ATH API GPU CPU NEW ONE TWO ALL ANY CAN SEE".split(" "));
function mdInline(s){
  return s.replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>").replace(/(^|[\s(])\*([^*\s][^*]*)\*/g,"$1<i>$2</i>")
     .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}
function linkTickers(html,skip){
  if(!base?.px) return html;
  const seen=new Set(skip?[skip]:[]);   // link each ticker once, and never the one the answer is about
  return html.replace(/(<a\b[^>]*>.*?<\/a>|<code>.*?<\/code>|<th>.*?<\/th>|<[^>]+>)|\b([A-Z]{2,5})\b/g,(m,tag,t)=>{
    if(tag||!t||!base.px[t]||ASK_STOP.has(t)||seen.has(t)) return m; seen.add(t); return `<button class="tkl" data-ask-open="${t}" title="Open ${t}">${t}</button>`; });
}
function mdToHtml(src,msg){
  if(!src) return "";
  const L=esc(src).split("\n"), out=[]; let list=null, para=[];
  const flushP=()=>{ if(para.length){ out.push(`<p>${mdInline(para.join(" "))}</p>`); para=[]; } };
  const flushL=()=>{ if(list){ out.push(`<${list.t}>${list.items.map(x=>`<li>${mdInline(x)}</li>`).join("")}</${list.t}>`); list=null; } };
  for(let i=0;i<L.length;i++){
    const ln=L[i], tr=ln.trim();
    if(!tr){ flushP(); flushL(); continue; }
    let f;
    if((f=tr.match(/^```\s*([\w-]*)/))){ flushP(); flushL(); const lang=f[1].toLowerCase(), body=[]; let closed=false;
      for(i++;i<L.length;i++){ if(/^```\s*$/.test(L[i].trim())){ closed=true; break; } body.push(L[i]); }
      if(lang==="chart"){ const raw=body.join("\n").replace(/&quot;/g,'"').replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&amp;/g,"&");
        let spec=null; try{ spec=closed?JSON.parse(raw):null; }catch(e){}
        out.push(spec?`<figure class="tkc" data-c="${esc(encodeURIComponent(JSON.stringify(spec)))}"></figure>`:closed?"":`<figure class="tkc wait"><span>Drawing a chart…</span></figure>`); }
      else out.push(`<pre class="mdpre"><code>${body.join("\n")}</code></pre>`);
      continue; }
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
  const i=msg?ASK.conv.indexOf(msg):-1, u=i>0?ASK.conv[i-1]:null;
  return linkTickers(out.join(""),u?.ctx?.scope==="stock"?u.ctx.t:null);
}

/* charts Tick draws: a ```chart block of JSON becomes a small SVG line or bar chart --------------------------- */
const CH_COL=["var(--fund)","var(--accent)","var(--warn)","var(--c4)"];
const CH_SPECS=new WeakMap();
function chFmt(v,u,short){ if(v==null||!isFinite(v)) return "–"; const a=Math.abs(v);
  if(short&&Number.isInteger(v)){ const sg=v>0&&u!=="$"&&u!==""?"+":v<0?"−":""; return u==="$"?sg+"$"+a.toLocaleString("en-US"):sg+a.toLocaleString("en-US")+(u==="%"?"%":""); }
  if(u==="%") return (v>0?"+":v<0?"−":"")+a.toFixed(a<10&&!short?1:a<10?1:0)+"%";
  if(u==="$") return (v<0?"−":"")+"$"+(a>=1e12?(a/1e12).toFixed(1)+"T":a>=1e9?(a/1e9).toFixed(1)+"B":a>=1e6?(a/1e6).toFixed(1)+"M":a>=1000?Math.round(a).toLocaleString("en-US"):a.toFixed(2));
  if(u==="pts") return (v>0?"+":v<0?"−":"")+a.toFixed(a<1?2:1);
  return (v<0?"−":"")+(a>=1000?Math.round(a).toLocaleString("en-US"):+a.toFixed(2)); }
const chDate=x=>{ const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(x); return m?new Date(+m[1],m[2]-1,+m[3]).toLocaleDateString("en-US",{month:"short",day:"numeric"}):String(x); };
function chTicks(lo,hi,n=4){ if(lo===hi){ lo-=1; hi+=1; } const raw=(hi-lo)/n, p=10**Math.floor(Math.log10(raw)), st=[1,2,2.5,5,10].map(k=>k*p).find(k=>k>=raw)||raw;
  const out=[]; for(let v=Math.ceil(lo/st)*st;v<=hi+st*1e-9;v+=st) out.push(+v.toFixed(10)); return out; }
function chartSpec(c){
  if(!c||!Array.isArray(c.x)||!Array.isArray(c.series)) return null;
  const S=c.series.filter(s=>s&&Array.isArray(s.values)).slice(0,4).map(s=>({name:String(s.name||""),values:s.values.slice(0,120).map(v=>v==null||v===""?null:+v)}));
  if(!S.length||!c.x.length) return null;
  return {type:c.type==="bar"?"bar":"line",title:String(c.title||""),unit:["%","$","pts"].includes(c.unit)?c.unit:"",x:c.x.slice(0,120).map(String),series:S};
}
function chartSVG(c,W){
  const u=c.unit, n=c.x.length;
  if(c.type==="bar"){
    const S=c.series.slice(0,2), rowH=S.length>1?30:24, lab=Math.min(110,Math.max(44,...c.x.map(x=>x.length*7+8))), H=n*rowH+6;
    const all=S.flatMap(s=>s.values).filter(v=>v!=null), lo=Math.min(0,...all), hi=Math.max(0,...all), val=58, x0=lab+8+(lo<0?50:0), w=W-x0-val, sc=v=>x0+(v-lo)/((hi-lo)||1)*w, z=sc(0);
    const signed=S.length===1&&(u==="%"||u==="pts");
    let g=`<line x1="${z}" x2="${z}" y1="0" y2="${H}" class="ch-0"/>`;
    c.x.forEach((x,i)=>{ const y=i*rowH+3; g+=`<text x="${lab}" y="${y+rowH/2+4}" text-anchor="end" class="ch-l">${esc(x)}</text>`;
      S.forEach((s,k)=>{ const v=s.values[i]; if(v==null) return; const bh=S.length>1?(rowH-8)/2:rowH-8, by=y+2+k*bh, a=Math.min(sc(v),z), b=Math.max(sc(v),z);
        const col=signed?(v<0?"var(--down)":"var(--up)"):CH_COL[k+1];
        g+=`<rect x="${a}" y="${by}" width="${Math.max(1,b-a)}" height="${bh-1}" rx="2" fill="${col}"><title>${esc(x)}${S.length>1?" · "+esc(s.name):""}: ${chFmt(v,u)}</title></rect>`;
        g+=`<text x="${v<0&&lo<0?a-4:b+4}" y="${by+bh/2+3.5}" text-anchor="${v<0&&lo<0?"end":"start"}" class="ch-v">${chFmt(v,u)}</text>`; }); });
    const leg=S.length>1?`<div class="ch-leg">${S.map((s,k)=>`<span><i style="background:${CH_COL[k+1]}"></i>${esc(s.name)}</span>`).join("")}</div>`:"";
    return `${leg}<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(c.title)}">${g}</svg>`;
  }
  const H=190, S=c.series, all=S.flatMap(s=>s.values).filter(v=>v!=null); if(!all.length) return "";
  let lo=Math.min(...all), hi=Math.max(...all); const pad=(hi-lo)*.08||1; lo-=pad; hi+=pad;
  const ticks=chTicks(lo,hi,3), L=Math.max(30,...ticks.map(t=>chFmt(t,u,true).length*6.6+6)), R=Math.min(96,8+Math.max(...S.map(s=>(s.name.length+8)*6.4))), T=8, B=22;
  const X=i=>L+(n<2?0:i/(n-1)*(W-L-R)), Y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
  const single=S.length===1, f=S[0].values.find(v=>v!=null), l=[...S[0].values].reverse().find(v=>v!=null), dirCol=l>=f?"var(--up)":"var(--down)";
  let g=ticks.map(t=>`<line x1="${L}" x2="${W-R}" y1="${Y(t)}" y2="${Y(t)}" class="${t===0?"ch-0":"ch-g"}"/><text x="${L-6}" y="${Y(t)+3.5}" text-anchor="end" class="ch-a">${chFmt(t,u,true)}</text>`).join("");
  const xi=[...new Set([0,Math.round((n-1)/3),Math.round(2*(n-1)/3),n-1])].filter(i=>i>=0&&i<n);
  g+=xi.map((i,k)=>`<text x="${X(i)}" y="${H-6}" text-anchor="${k===0?"start":i===n-1?"end":"middle"}" class="ch-a">${esc(chDate(c.x[i]))}</text>`).join("");
  const ends=[];
  S.forEach((s,k)=>{ const col=single?dirCol:CH_COL[k]; let d="", pen=false;
    s.values.forEach((v,i)=>{ if(v==null){ pen=false; return; } d+=(pen?"L":"M")+X(i).toFixed(1)+" "+Y(v).toFixed(1); pen=true; });
    if(single){ const fi=s.values.findIndex(v=>v!=null), li=s.values.length-1-[...s.values].reverse().findIndex(v=>v!=null);
      g+=`<path d="${d}L${X(li).toFixed(1)} ${H-B}L${X(fi).toFixed(1)} ${H-B}Z" fill="${col}" opacity=".08"/>`; }
    g+=`<path d="${d}" fill="none" stroke="${col}" stroke-width="${k?1.6:2}" stroke-linejoin="round" stroke-linecap="round"/>`;
    const li=s.values.length-1-[...s.values].reverse().findIndex(v=>v!=null); if(li>=s.values.length) return;
    ends.push({y:Y(s.values[li]),x:X(li),col,txt:(single?"":s.name+" ")+chFmt(s.values[li],u)}); });
  ends.sort((a,b)=>a.y-b.y); for(let i=1;i<ends.length;i++) if(ends[i].y-ends[i-1].y<13) ends[i].y=ends[i-1].y+13;
  g+=ends.map(e=>`<circle cx="${e.x}" cy="${Math.min(H-B,Math.max(T,e.y))}" r="2.6" fill="${e.col}"/><text x="${e.x+6}" y="${e.y+3.5}" class="ch-e" fill="${e.col}">${esc(e.txt)}</text>`).join("");
  g+=`<g class="ch-hov" hidden><line class="ch-x" y1="${T}" y2="${H-B}"/></g>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(c.title)}" data-l="${L}" data-r="${R}">${g}</svg><div class="ch-tip" hidden></div>`;
}
function drawCharts(root){
  root.querySelectorAll("figure.tkc[data-c]").forEach(fg=>{
    let c=null; try{ c=chartSpec(JSON.parse(decodeURIComponent(fg.dataset.c))); }catch(e){}
    if(!c){ fg.remove(); return; }
    const W=Math.max(240,Math.round((fg.clientWidth||324)-24)); CH_SPECS.set(fg,c);
    fg.innerHTML=`${c.title?`<figcaption>${esc(c.title)}</figcaption>`:""}<div class="ch-box">${chartSVG(c,W)}</div>`;
  });
}
/* hover a line chart: a guide line and the values on that day */
document.addEventListener("pointermove",e=>{
  const svg=e.target.closest?.("figure.tkc svg[data-l]"); document.querySelectorAll("figure.tkc .ch-tip:not([hidden])").forEach(t=>{ if(!svg||!t.parentNode.contains(svg)){ t.hidden=true; t.parentNode.querySelector(".ch-hov")?.setAttribute("hidden",""); } });
  if(!svg) return; const fg=svg.closest("figure"), c=CH_SPECS.get(fg); if(!c) return;
  const r=svg.getBoundingClientRect(), W=+svg.viewBox.baseVal.width, L=+svg.dataset.l, R=+svg.dataset.r, n=c.x.length;
  const px=(e.clientX-r.left)*W/r.width, i=Math.max(0,Math.min(n-1,Math.round((px-L)/((W-L-R)||1)*(n-1)))), x=L+(n<2?0:i/(n-1)*(W-L-R));
  const h=svg.querySelector(".ch-hov"); h.removeAttribute("hidden"); const ln=h.querySelector("line"); ln.setAttribute("x1",x); ln.setAttribute("x2",x);
  const tip=fg.querySelector(".ch-tip"); tip.hidden=false;
  tip.innerHTML=`<b>${esc(chDate(c.x[i]))}</b>${c.series.map((s,k)=>`<span><i style="background:${c.series.length===1?"var(--ink-2)":CH_COL[k]}"></i>${c.series.length>1?esc(s.name)+" ":""}<em>${chFmt(s.values[i],c.unit)}</em></span>`).join("")}`;
  const left=x*r.width/W; tip.style.left=Math.min(r.width-tip.offsetWidth,Math.max(0,left-tip.offsetWidth/2))+"px";
},{passive:true});
let chRT=0; addEventListener("resize",()=>{ clearTimeout(chRT); chRT=setTimeout(()=>{ const B=$("#askB"); if(B) drawCharts(B); },150); });

/* wiring --------------------------------------------------------------------------------------------- */
document.addEventListener("click",e=>{
  const b=e.target.closest("[data-ask-skill],[data-ask-scope],[data-ask-open],[data-ask-copy],[data-ask-retry],#askOpen"); if(!b) return;
  if(b.id==="askOpen"){ b.classList.remove("ping"); return ASK.open?closeAsk():openAsk(); }
  if(b.dataset.askOpen){ e.preventDefault(); if(!canDock()&&innerWidth<=760) closeAsk(); return openStock(b.dataset.askOpen); }
  if(b.dataset.askCopy){ const m=ASK.conv[+b.dataset.askCopy]; navigator.clipboard?.writeText(m?.text||""); b.innerHTML=ic("check",14); b.title="Copied"; setTimeout(()=>{ b.innerHTML=ic("copy",14); b.title="Copy"; },1600); return; }
  if(b.hasAttribute("data-ask-retry")) return askRetry();
  if(b.closest("#ask")&&b.dataset.askSkill) return askSend({skill:b.dataset.askSkill});
  openAsk({scope:b.dataset.askScope,t:b.dataset.askT,skill:b.dataset.askSkill});
});
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"&&ASK.open){
    if(["askMenu","askCtxM","askPop"].some(id=>!$("#"+id).hidden)){ hideMenus(); }
    else if(ASK.view){ ASK.view=null; askRender(); }
    else if(canDock()){ if(document.activeElement?.closest("#ask")) document.activeElement.blur(); else return; }
    else closeAsk();
    e.stopImmediatePropagation(); e.preventDefault(); return;
  }
  if(e.target.matches("input,textarea,select")||e.metaKey||e.ctrlKey||e.altKey) return;
  if(e.key==="a"||e.key==="A"){ e.preventDefault(); if(askHover&&document.contains(askHover)&&!askHover.closest("#ask")) return askAbout(askHover); ASK.open?$("#askQ").focus():openAsk(); }
},true);
document.addEventListener("scroll",e=>{ const B=e.target; if(B.id==="askB") ASK.stick=B.scrollHeight-B.scrollTop-B.clientHeight<40; },true);

/* header button and command bar */
{ const bell=$("#bell"); if(bell&&!$("#askOpen")){ const b=document.createElement("button"); b.className="askbtn"; b.id="askOpen"; b.title=`${TICK}, your analyst (A)`; b.setAttribute("aria-label",`Show ${TICK}`); b.innerHTML=`${tickFace(20)}<span>${TICK}</span>`; b.querySelector(".tick").classList.add("live"); bell.before(b); } }
/* when the panel is closed, Tick floats in a corner: drag him anywhere, click him to open the panel */
function tickFloat(){
  if($("#tickFloat")) return;
  const f=document.createElement("button"); f.id="tickFloat"; f.className="tfloat"; f.type="button"; f.setAttribute("aria-label",`Open ${TICK} (A)`);
  f.innerHTML=`<span class="tf-say" id="tfSay"></span>${tickFace(36,"idle")}<span>Ask ${TICK}</span><kbd>A</kbd>`; f.querySelector(".tick").classList.add("live");
  document.body.appendChild(f);
  const place=(r,b)=>{ r=Math.max(8,Math.min(innerWidth-(f.offsetWidth||130)-8,r)); b=Math.max(8,Math.min(innerHeight-60,b)); f.style.setProperty("--tf-r",r+"px"); f.style.setProperty("--tf-b",b+"px");
    f.classList.toggle("tf-l",r>innerWidth/2); return [r,b]; };
  const saved=String(load("tickFloat","")).split(",").map(Number); let pos=place(...(saved.length===2&&saved.every(isFinite)?saved:[24,24]));
  addEventListener("resize",()=>{ pos=place(...pos); });
  let drag=null, moved=false;
  f.addEventListener("pointerdown",e=>{ if(e.button!==0) return; const r=f.getBoundingClientRect(); drag={x:e.clientX,y:e.clientY,r0:pos[0],b0:pos[1]}; moved=false; f.setPointerCapture(e.pointerId); });
  f.addEventListener("pointermove",e=>{ if(!drag) return; const dx=e.clientX-drag.x, dy=e.clientY-drag.y;
    if(!moved&&Math.hypot(dx,dy)<5) return; moved=true; f.classList.add("dragging"); pos=place(drag.r0-dx,drag.b0-dy); });
  const end=()=>{ if(!drag) return; drag=null; f.classList.remove("dragging"); if(moved) save("tickFloat",pos.join(",")); };
  f.addEventListener("pointerup",end); f.addEventListener("pointercancel",end);
  f.addEventListener("click",e=>{ if(moved){ moved=false; e.preventDefault(); return; } f.classList.remove("ping"); openAsk(); });
}
tickFloat();
if(typeof COMMANDS!=="undefined"){
  COMMANDS.push({cmd:"ask:free",label:`Ask ${TICK}…`,hint:TICK,icon:"spark",keys:"ask tick ai agent claude codex question chat",run:()=>openAsk({q:ASK.pendingQ,send:!!ASK.pendingQ})});
  COMMANDS.push({cmd:"tick:side",label:`Move ${TICK} to the other side`,hint:TICK,icon:"expand",keys:"move tick left right side dock panel",run:()=>{ if(!ASK.open) openAsk({focus:false}); tickSide(ASK.side==="left"?"right":"left"); }});
  COMMANDS.push({cmd:"tick:new",label:`New conversation with ${TICK}`,hint:TICK,icon:"compose",keys:"new chat conversation tick",run:()=>{ openAsk(); newChat(); }});
  for(const s of ASK_SKILLS_FALLBACK) COMMANDS.push({cmd:"skill:"+s.name,label:s.scope==="stock"?`${s.label} (open stock)`:s.label,hint:TICK,icon:"spark",keys:"ask tick "+s.label+" "+s.name.replace(/-/g," "),
    run:()=>{ if(s.scope==="stock"&&!(drawerOpen&&sel)) return openAsk({scope:"market"}); openAsk({scope:s.scope,t:s.scope==="stock"?sel:null,skill:s.name}); }});
}
askInfo().then(()=>{ const pref=new URLSearchParams(location.search).get("tick")==="0"?"0":load("tickOpen",""); if(ASK.paired) openAsk(); else if(pref==="1"||(pref===""&&innerWidth>=1280)) openAsk({focus:false}); });

/* ---- Mac app: let the native window match the page (title bar color, light/dark) ---- */
(function(){
  const h=window.webkit&&webkit.messageHandlers&&webkit.messageHandlers.ot; if(!h) return;
  document.documentElement.classList.add("in-mac-app");
  const mq=matchMedia("(prefers-color-scheme: dark)");
  const post=()=>{ const t=document.documentElement.dataset.theme; h.postMessage({bg:getComputedStyle(document.body).backgroundColor,dark:t?t==="dark":mq.matches}); };
  post(); mq.addEventListener("change",post);
  new MutationObserver(post).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
})();
