/* OpenTicker: Settings. One sheet with everything you can change: looks, Tick, notifications, your phone, and the app itself.
   Uses globals from index.html (theme, applyTheme, me, api, notifyOn, randTopic) and ask.js (ASK, askProv, tickSide, ...). */
Object.assign(IC,{
  gear:'<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
});
let APP=null;
const SET_SECTIONS=[["look","Appearance"],["tick","Tick"],["notify","Notifications"],["phone","Your phone"],["data","Data"],["about","About"]];
let HEALTH=null;
async function loadHealth(){ try{ HEALTH=await (await fetch("/api/health")).json(); }catch(e){ HEALTH=null; } markGear(); return HEALTH; }
function markGear(){ const g=$("#gear"); if(!g) return; const bad=!!HEALTH&&!HEALTH.ok; g.classList.toggle("warn",bad);
  g.title=bad?"Some data is out of date. Open Settings to see what":"Settings (⌘,)"; }

function setRow(label,help,control,cls=""){ return `<div class="srow ${cls}"><div class="sl"><b>${label}</b>${help?`<small>${help}</small>`:""}</div><div class="sc">${control}</div></div>`; }
function setSeg(name,opts,cur){ return `<div class="seg sm" role="radiogroup" aria-label="${esc(name)}">${opts.map(([v,l])=>`<button type="button" role="radio" aria-pressed="${v===cur}" aria-checked="${v===cur}" data-set-${name}="${esc(v)}">${l}</button>`).join("")}</div>`; }
function setTgl(id,on,label){ return `<label class="tgl"><input type="checkbox" id="${id}" ${on?"checked":""} aria-label="${esc(label)}"><i></i></label>`; }

async function openSettings(section){
  closeSettings(true);
  const d=document.createElement("dialog"); d.className="sets"; d.id="sets"; d.setAttribute("aria-label","Settings");
  document.body.appendChild(d); renderSettings(); d.showModal();
  d.addEventListener("close",()=>d.remove());
  d.addEventListener("click",e=>{ if(e.target===d) d.close(); });   // a click on the dimmed backdrop closes it
  if(section) d.querySelector(`#set-${section}`)?.scrollIntoView({block:"start"});
  const h=loadHealth();
  try{ APP=await (await fetch("/api/app")).json(); }catch(e){ APP=APP||{}; }
  await h;
  if(!ASK.info) await askInfo().catch(()=>{});
  if(document.contains(d)) renderSettings();
}
function closeSettings(now){ const d=$("#sets"); if(d){ now?d.remove():d.close(); } }

function renderSettings(){
  const d=$("#sets"); if(!d) return; const keep=d.querySelector(".sbody")?.scrollTop||0;
  const P=ASK.info?.providers||[], cur=askProv(), st=me?.settings||{}, a=APP||{}, local=a.local??ASK.info?.local;
  const floatOn=load("tickFloatOff","")!=="1", openPref=load("tickOpen","");
  /* Tick's model choices for the agent in use, in plain words */
  let modelCtl="";
  if(cur){
    if(cur.id==="claude"){ const ch=askModelOf(cur), nm=id=>prettyModel(askResolve(cur,id))||prettyModel(id);
      modelCtl=`<select id="setModel" aria-label="Model">${[["","Claude Code's default"+(prettyModel(askResolve(cur,""))?` (${prettyModel(askResolve(cur,""))})`:"")],["opus",nm("opus")+", best"],["sonnet",nm("sonnet")+", faster"],["haiku",nm("haiku")+", fastest"]]
        .map(([v,l])=>`<option value="${v}" ${v===ch?"selected":""}>${esc(l)}</option>`).join("")}</select>`; }
    else if(cur.id==="ollama") modelCtl=`<select id="setModel" aria-label="Model">${(cur.choices||[]).map(c=>`<option value="${esc(c[0])}" ${c[0]===askModelOf(cur)?"selected":""}>${esc(prettyModel(c[0]))}</option>`).join("")}</select>`;
    else modelCtl=`<span class="sv">${esc(askModelName(cur)||"Its default")}</span>`;
  }
  const ef=cur&&cur.efforts?.length?askEffortOf(cur):null;
  const sec=(id,title,body)=>`<section class="ssec" id="set-${id}"><h3>${title}</h3><div class="scard">${body}</div></section>`;
  d.innerHTML=`<div class="shead"><h2>Settings</h2><button class="x" id="setClose" aria-label="Close settings">${ic("close",16)}</button><nav class="snav" aria-label="Settings sections">${SET_SECTIONS.map(([k,l])=>`<a href="#set-${k}" data-set-go="${k}">${l}</a>`).join("")}</nav></div>
  <div class="sbody">
  ${sec("look","Appearance",
     setRow("Theme","Auto follows your device's light or dark setting.",setSeg("theme",[["auto","Auto"],["light","Light"],["dark","Dark"]],theme)))}
  ${sec("tick","Tick",
     `<div class="srow col"><div class="sl"><b>Who Tick thinks with</b><small>An AI agent on your Mac, signed in with your own account.</small></div>
       <div class="sags">${P.map(p=>{ const on=cur?.id===p.id;
         return `<button type="button" class="sag${on?" on":""}" ${p.available?`data-set-agent="${p.id}"`:`data-set-setup="${p.id}"`} aria-pressed="${on}">${agentIcon(p.id,20)}<span><b>${esc(p.label)}</b><small>${esc(p.available?AG_SUB[p.id]||p.note:(ST[p.state]||["Not ready"])[0])}</small></span>${on?ic("check",15):p.available?"":`<em>Set up</em>`}</button>`; }).join("")}</div></div>`
     +(cur?setRow("Model",cur.id==="claude"?"Opus reads deepest. Sonnet and Haiku answer faster.":cur.id==="ollama"?"Models you've pulled into Ollama.":`Change it in ${esc(cur.label)}'s own settings.`,modelCtl):"")
     +(ef!=null?setRow("Effort","How long Tick thinks before answering. Higher is more thorough and slower.",setSeg("effort",[...(cur.effort?[]:[["","Default"]]),...cur.efforts.map(e=>[e,EFFORT[e]||e])],ef),"wide"):"")
     +setRow("Open Tick when OpenTicker starts",openPref===""?"Right now it opens on wide windows only.":"",setTgl("setOpen",openPref==="1"||(openPref===""&&innerWidth>=1280),"Open Tick at start"))
     +(innerWidth>760?setRow("Ask Tick button","The floating button in the corner when Tick's panel is closed.",setTgl("setFloat",floatOn,"Show the Ask Tick button"))
     +setRow("Side",`Or drag Tick's header across. Drag its inner edge to resize${ASK.w!==TICK_W0?`, or <button type="button" class="lnk" id="setW">reset the width</button>`:""}.`,setSeg("side",[["left","Left"],["right","Right"]],ASK.side)):""))}
  ${sec("notify","Notifications",
     setRow("Alerts on your phone",`Uses <a href="https://ntfy.sh" target="_blank" rel="noopener">ntfy</a>, a free push app. Install it, tap <b>+</b>, and subscribe to this topic. Anyone who knows the name can read it, so keep the random one.`,
       st.ntfyTopic?`<span class="on-pill">On</span>`:"","wrap")
     +`<form class="srow frm" id="setNt"><input id="setTopic" class="mono" value="${esc(st.ntfyTopic||randTopic())}" maxlength="64" aria-label="ntfy topic"><button class="btn">${st.ntfyTopic?"Save":"Turn on"}</button>${st.ntfyTopic?`<button class="btn ghost" type="button" id="setNtTest">Send test</button><button class="btn ghost" type="button" id="setNtOff">Turn off</button>`:""}<span class="err" id="setNtErr"></span></form>`
     +setRow("A note at the close","About 4:15 pm New York time on trading days: how your stocks did, what moved them, and who reports next. It lands in Alerts, and on your phone if that's on above. <button type=\"button\" class=\"lnk\" id=\"setCnPrev\">See today's</button>",setTgl("setCn",st.closeNote!==false,"Send a note at the close"))
     +`<div class="srow col cnprev" id="setCnBox" hidden></div>`
     +setRow("Alerts in this window","Show a notification here when a rule triggers, while OpenTicker is open.",setTgl("setBr",notifyOn,"Notifications in this window"))
     +setRow("Alert rules","Price moves, levels and earnings for your stocks.",`<button type="button" class="btn ghost" id="setRules">Edit rules</button>`))}
  ${sec("phone","Your phone",
     !local?setRow("You're on another device","These settings live on the Mac that runs OpenTicker.",""):
     setRow("Open OpenTicker on your phone",a.phone?`On. Your phone can reach it on the same Wi-Fi.`:`Off. Only this Mac can open it.`+(a.mac?` Changing this restarts OpenTicker in a Terminal window.`:""),
       a.mac?setTgl("setPhone",!!a.phone,"Let your phone open OpenTicker"):`<span class="sv">${a.phone?"On":"Off"}</span>`)
     +(a.phone&&ASK.info?.pair?`<div class="srow col"><div class="sl"><b>Pair your phone</b><small>Scan the QR code with your phone's camera, or open this link on it. It also lets you ask Tick from there. Keep it to yourself.</small></div>${pairRow('id="setPair"')}</div>`:""))}
  ${sec("data","Data",
     !HEALTH?setRow("Checking…","",""):
     (HEALTH.problems.length?`<div class="srow col dprob"><div class="sl"><b>${HEALTH.problems.length===1?"One thing is off":`${HEALTH.problems.length} things are off`}</b>${HEALTH.problems.map(p=>`<small>${esc(p)}</small>`).join("")}</div></div>`
       :setRow("Everything is up to date","Prices, holdings, the earnings calendar and Yahoo's research are all coming through.",`<span class="on-pill">OK</span>`))
     +HEALTH.rows.map(r=>`<div class="srow drow"><div class="sl"><b><i class="hdot ${r.ok?"ok":"bad"}"></i>${esc(r.name)}</b></div><div class="sc"><span class="sv">${esc(r.detail)}</span></div></div>`).join(""))}
  ${sec("about","About",
     setRow("OpenTicker",`Version ${esc(a.version||"…")}. Free and open source.`,`<a class="btn ghost" href="https://github.com/bin01/openticker" target="_blank" rel="noopener">GitHub</a>${local&&a.mac?`<button type="button" class="btn" id="setUpd">Update</button>`:""}`)
     +(local&&a.mac?setRow("Change OpenTicker","Ask your AI agent for anything: another fund, a new page, a different look, how Tick talks. This opens Claude Code or Codex in OpenTicker's code, which explains itself to the agent.",`<button type="button" class="btn ghost" id="setEdit">Open in Terminal</button>`):"")
     +(a.data?setRow("Your data",`Watchlist, positions, alerts and Tick's conversations stay on this Mac in <span class="mono">${esc(a.data)}</span>.`,""):"")
     +setRow("Keyboard shortcuts","",`<dl class="keys"><dt><kbd>⌘</kbd><kbd>K</kbd></dt><dd>Search or run a command</dd><dt><kbd>A</kbd></dt><dd>Ask Tick</dd><dt><kbd>/</kbd></dt><dd>Search stocks</dd><dt><kbd>⌘</kbd><kbd>,</kbd></dt><dd>Settings</dd></dl>`,"col"))}
  </div>`;
  d.querySelector(".sbody").scrollTop=keep;
  bindSettings(d,{cur,st});
}

function bindSettings(d,{cur,st}){
  const on=(sel,ev,fn)=>d.querySelectorAll(sel).forEach(el=>el.addEventListener(ev,fn));
  $("#setClose").onclick=()=>d.close();
  on("[data-set-go]","click",e=>{ e.preventDefault(); d.querySelector("#set-"+e.currentTarget.dataset.setGo)?.scrollIntoView({behavior:"smooth",block:"start"}); });
  on("[data-set-theme]","click",e=>{ theme=e.currentTarget.dataset.setTheme; save("theme",theme); applyTheme(); renderSettings(); });
  on("[data-set-agent]","click",e=>{ ASK.prov=e.currentTarget.dataset.setAgent; save("askProv",ASK.prov); askRender(); renderSettings(); });
  on("[data-set-setup]","click",()=>{ d.close(); ASK.view="agents"; openAsk(); });
  $("#setModel")?.addEventListener("change",e=>{ const v=e.target.value; if(cur.id==="ollama"){ ASK.model=v; save("askModel",v); } else save("askModel."+cur.id,v); askRender(); });
  on("[data-set-effort]","click",e=>{ save("askEffort."+cur.id,e.currentTarget.dataset.setEffort); askRender(); renderSettings(); });
  $("#setOpen").onchange=e=>save("tickOpen",e.target.checked?"1":"0");
  $("#setFloat")&&($("#setFloat").onchange=e=>{ save("tickFloatOff",e.target.checked?"":"1"); applyFloatPref(); });
  on("[data-set-side]","click",e=>{ const s=e.currentTarget.dataset.setSide; if(ASK.open) tickSide(s); else { ASK.side=s; save("tickSide",s); applyDock(); } renderSettings(); });
  $("#setW")?.addEventListener("click",()=>{ setTickW(TICK_W0,true); dispatchEvent(new Event("resize")); renderSettings(); });
  $("#setNt").onsubmit=async e=>{ e.preventDefault(); try{ await api("/api/me/settings",{ntfyTopic:$("#setTopic").value.trim(),ntfyServer:st.ntfyServer}); renderSettings(); }catch(x){ $("#setNtErr").textContent=x.message; } };
  $("#setNtTest")?.addEventListener("click",async()=>{ const m=$("#setNtErr"); try{ await api("/api/me/test-push"); m.textContent="Sent. Check your phone."; m.className="ok"; }catch(x){ m.textContent=x.message; } });
  $("#setNtOff")?.addEventListener("click",async()=>{ await api("/api/me/settings",{ntfyTopic:"",ntfyServer:st.ntfyServer}).catch(()=>{}); renderSettings(); });
  $("#setCn").onchange=async e=>{ await api("/api/me/settings",{closeNote:e.target.checked}).catch(()=>{}); };
  $("#setCnPrev").onclick=async()=>{ const b=$("#setCnBox"); b.hidden=false; b.innerHTML=`<small>Writing it…</small>`;
    try{ const n=await (await fetch("/api/me/close-note",{headers:meHeaders()})).json();
      b.innerHTML=n.title?`<div class="cn"><b>${esc(n.title)}</b><p>${esc(n.body)}</p><small>${n.live?"With prices right now. The real one goes out after the close.":"From the last closing prices."}</small></div>`:`<small>There's no price data yet.</small>`; }
    catch(x){ b.innerHTML=`<small>Couldn't write it: ${esc(x.message)}</small>`; } };
  $("#setBr").onchange=async e=>{ if(e.target.checked&&"Notification" in window){ const p=await Notification.requestPermission(); if(p!=="granted"){ e.target.checked=false; return; } } notifyOn=e.target.checked; save("notify",notifyOn?"1":"0"); };
  $("#setRules").onclick=()=>{ d.close(); openAlerts(); };
  $("#setPhone")?.addEventListener("change",async e=>{ const r=await fetch("/api/app/terminal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step:e.target.checked?"phone-on":"phone-off"})}).catch(()=>null);
    e.target.closest(".srow").querySelector("small").textContent=r?.ok?"Restarting OpenTicker in Terminal. This page reconnects in about a minute.":"Couldn't open Terminal. Run openticker start --lan yourself."; });
  $("#setPair")?.addEventListener("click",e=>{ navigator.clipboard?.writeText(ASK.info.pair); e.currentTarget.innerHTML=ic("check",13)+"Copied"; });
  d.querySelector(".pairl [data-qr]")?.addEventListener("click",e=>qrToggle(e.currentTarget));
  $("#setEdit")?.addEventListener("click",async e=>{ const b=e.currentTarget; const r=await fetch("/api/app/terminal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step:"edit"})}).catch(()=>null);
    b.textContent=r?.ok?"Opened in Terminal":"Run openticker edit"; });
  $("#setUpd")?.addEventListener("click",async e=>{ const b=e.currentTarget; const r=await fetch("/api/app/terminal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step:"update"})}).catch(()=>null);
    b.textContent=r?.ok?"Updating in Terminal…":"Run openticker update"; b.disabled=true; });
}
function applyFloatPref(){ document.body.classList.toggle("no-tfloat",load("tickFloatOff","")==="1"); }
applyFloatPref();

/* the gear in the top bar, ⌘, (the Mac's usual shortcut), and the command menu */
(function(){
  const b=document.createElement("button"); b.className="theme iconbtn"; b.id="gear"; b.title="Settings (⌘,)"; b.setAttribute("aria-label","Settings"); b.innerHTML=ic("gear",17);
  b.onclick=()=>openSettings(); $("#theme")?.after(b);
  loadHealth(); setInterval(loadHealth,5*60e3);
  document.addEventListener("keydown",e=>{ if((e.metaKey||e.ctrlKey)&&e.key===","){ e.preventDefault(); $("#sets")?closeSettings():openSettings(); } });
  if(typeof COMMANDS!=="undefined") COMMANDS.push({cmd:"settings",label:"Settings",hint:"OpenTicker",icon:"gear",keys:"settings preferences options theme dark light tick model phone notifications update",run:()=>openSettings()});
})();
