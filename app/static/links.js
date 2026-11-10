/* OpenTicker: linked accounts. Brokerages and finance apps (Monarch, Interactive Brokers, Robinhood, or any MCP server)
   that keep your portfolio in sync. Settings, Accounts lists them; connecting opens the provider's sign-in in your browser,
   then a review sheet shows what was found before anything is added. The server side is app/links.py.
   Uses globals from index.html (me, api, meHeaders, afterMe, esc, ic, money, toast, $) and settings.js (setRow, renderSettings). */
Object.assign(IC,{
  link:'<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
});
const LK={info:null,poll:null,want:null,confirm:null,err:{},busy:{},urls:{}};

async function linksLoad(){
  try{ const r=await fetch("/api/me/links",{headers:meHeaders()}); if(r.ok) LK.info=await r.json(); }catch(e){}
  return LK.info;
}
async function linkApi(action,body){
  const r=await fetch("/api/me/links/"+action,{method:"POST",headers:meHeaders({"Content-Type":"application/json"}),body:JSON.stringify(body||{})});
  const d=await r.json().catch(()=>({error:"OpenTicker didn't answer."}));
  if(!r.ok) throw new Error(d.error||"Something went wrong.");
  if(d.me){ me=d.me; afterMe(); if(LK.info) LK.info.links=me.links||[]; if(typeof refreshMine==="function") refreshMine(); }
  return d;
}
/* while a sign-in or a first read is under way, check every second and a half; open the review when it's ready */
function linksWatch(){
  clearTimeout(LK.poll);
  const busy=(LK.info?.links||[]).some(l=>l.status==="signin"||l.status==="fetching");
  if(!busy) return;
  LK.poll=setTimeout(async()=>{
    const before=JSON.stringify(LK.info?.links);
    await linksLoad();
    if(JSON.stringify(LK.info?.links)!==before){ if($("#sets")) renderSettings();
      const w=(LK.info?.links||[]).find(l=>l.id===LK.want&&l.status==="review");
      if(w){ LK.want=null; openLinkReview(w.id); } }
    linksWatch();
  },1500);
}

function linkWhen(ts){ if(!ts) return ""; const d=new Date(ts*1000), now=new Date();
  const t=d.toLocaleTimeString("en-US",{hour:"numeric",minute:"2-digit"}).toLowerCase();
  if(d.toDateString()===now.toDateString()) return `today at ${t}`;
  const y=new Date(now); y.setDate(now.getDate()-1); if(d.toDateString()===y.toDateString()) return `yesterday at ${t}`;
  return d.toLocaleDateString("en-US",{month:"short",day:"numeric"}); }

function linkStatus(l){
  const n=l.count, pos=`${n} position${n===1?"":"s"}`;
  switch(l.status){
    case "signin": return ["",`Waiting for you to sign in to ${l.name} in your browser…`];
    case "fetching": return ["","Reading your holdings…"];
    case "review": return ["",`Ready. Review what was found before it's added.`];
    case "auth": return ["bad",l.synced?`The sign-in expired. Showing positions from ${linkWhen(l.synced)}.`:"The sign-in didn't finish."];
    case "error": return ["bad",l.error||"Couldn't connect."];
    default: return l.error?["bad",`Couldn't sync: ${l.error} Showing positions from ${linkWhen(l.synced)}.`]:["",`${pos}, synced ${linkWhen(l.synced)}. Updates each trading day after the close.`];
  }
}

/* the Accounts section of Settings */
function linksSection(){
  const I=LK.info, L=I?.links||me?.links||[], local=I?.local;
  if(!I&&!L.length) return setRow("Checking…","","");
  const rows=L.map(l=>{
    const [tone,msg]=linkStatus(l), busy=LK.busy[l.id], conf=LK.confirm===l.id;
    let ctl="";
    if(conf) ctl=`<button type="button" class="btn ghost" data-lk-act="no" data-lk="${l.id}">Cancel</button>`;
    else if(busy) ctl=`<span class="sv">${esc(busy)}</span>`;
    else if(l.status==="review") ctl=`<button type="button" class="btn" data-lk-act="review" data-lk="${l.id}">Review</button>`;
    else if(l.status==="signin"||l.status==="fetching") ctl=local?`<button type="button" class="btn ghost" data-lk-act="cancel" data-lk="${l.id}">Cancel</button>`:"";
    else if(l.status==="auth") ctl=local?`<button type="button" class="btn" data-lk-act="reconnect" data-lk="${l.id}">Sign in again</button><button type="button" class="btn ghost" data-lk-act="${l.synced?"ask":"remove"}" data-lk="${l.id}">${l.synced?"Disconnect":"Remove"}</button>`:"";
    else if(l.status==="error") ctl=`<button type="button" class="btn" data-lk-act="retry" data-lk="${l.id}">Try again</button>${local?`<button type="button" class="btn ghost" data-lk-act="${l.synced?"ask":"remove"}" data-lk="${l.id}">Remove</button>`:""}`;
    else ctl=`<button type="button" class="btn ghost" data-lk-act="sync" data-lk="${l.id}">Sync now</button>${local?`<button type="button" class="btn ghost" data-lk-act="ask" data-lk="${l.id}">Disconnect</button>`:""}`;
    const wait=l.status==="signin"||l.status==="fetching";
    return `<div class="srow lkrow"><span class="lkic${l.status==="ok"&&!l.error?" on":""}">${ic("landmark",16)}</span><div class="sl"><b>${esc(l.name)}</b><small class="${tone}">${wait?`<i class="lkspin" aria-hidden="true"></i>`:""}${esc(msg)}</small>${LK.err[l.id]?`<small class="bad">${esc(LK.err[l.id])}</small>`:""}</div><div class="sc">${ctl}</div></div>`
      +(conf?`<div class="srow lkconf"><div class="sl"><small>Disconnecting signs OpenTicker out of ${esc(l.name)} and deletes its key from this Mac. Its ${l.count} position${l.count===1?"":"s"} can leave your portfolio or stay as your own, without syncing.</small></div>
        <div class="sc"><button type="button" class="btn ghost" data-lk-act="keep" data-lk="${l.id}">Keep them</button><button type="button" class="btn danger" data-lk-act="drop" data-lk="${l.id}">Remove them</button></div></div>`:"")
      +(l.status==="signin"&&LK.urls[l.id]?`<div class="srow lkconf"><div class="sl"><small>Nothing opened? <a href="${esc(LK.urls[l.id])}" target="_blank" rel="noopener">Open the sign-in page</a>.</small></div></div>`:"");
  }).join("");
  const have=new Set(L.map(l=>l.provider));
  const add=!local?setRow("Add an account","Connect accounts on the Mac that runs OpenTicker. The sign-in opens in its browser.",""):
    `<div class="srow col"><div class="sl"><b>${L.length?"Add another":"Keep your portfolio in sync"}</b><small>OpenTicker reads your positions and updates them every trading day. Monarch also brings in Fidelity, Schwab, Vanguard and anything else you track there. OpenTicker only reads, and your sign-in stays in this Mac's Keychain.</small></div>
     <div class="lkadd">${(I?.presets||[]).filter(p=>!have.has(p.id)).map(p=>`<button type="button" class="sag" data-lk-add="${p.id}">${ic("landmark",18)}<span><b>${esc(p.name)}</b><small title="${esc(p.blurb)}">${esc(p.blurb)}</small></span>${ic("plus",15)}</button>`).join("")}
       <button type="button" class="sag" data-lk-add="other" aria-expanded="${!!LK.other}">${ic("link",18)}<span><b>Another service</b><small>Any service with your positions</small></span>${ic("plus",15)}</button></div></div>
     ${LK.other?`<div class="srow lkconf"><div class="sl"><small>Paste the link address the service gives for apps like this. It may call it an MCP server address.</small></div></div><form class="srow frm" id="lkOther"><input id="lkUrl" placeholder="https://example.com/mcp" inputmode="url" autocomplete="off" spellcheck="false" aria-label="The service's link address" required><button class="btn">Connect</button></form>`:""}
     ${LK.err.add?`<div class="srow lkconf"><div class="sl"><small class="bad">${esc(LK.err.add)}</small></div></div>`:""}`;
  return rows+add;
}

function bindLinks(d){
  if(!LK.info) linksLoad().then(()=>{ if($("#sets")) renderSettings(); linksWatch(); });
  d.querySelectorAll("[data-lk-add]").forEach(b=>b.onclick=()=>{ const p=b.dataset.lkAdd;
    if(p==="other"){ LK.other=!LK.other; renderSettings(); $("#lkUrl")?.focus(); return; }
    linkConnect({provider:p},b); });
  $("#lkOther")&&($("#lkOther").onsubmit=e=>{ e.preventDefault(); linkConnect({provider:"other",url:$("#lkUrl").value.trim()},e.submitter); });
  d.querySelectorAll("[data-lk-act]").forEach(b=>b.onclick=()=>linkAct(b.dataset.lkAct,b.dataset.lk));
  linksWatch();
}

async function linkConnect(body,btn){
  LK.err.add=""; if(btn){ btn.disabled=true; const s=btn.querySelector("small"); if(s) s.textContent="Opening the sign-in…"; else btn.textContent="Connecting…"; }
  try{ const r=await linkApi(body.id?"reconnect":"connect",body);
    LK.want=r.id; LK.other=false;
    if(r.auth_url) LK.urls[r.id]=r.auth_url;
    await linksLoad();
    if(r.auth_url&&!r.opened) window.open(r.auth_url,"_blank","noopener");
  }catch(x){ if(body.id) LK.err[body.id]=x.message; else LK.err.add=x.message; }
  renderSettings();
}

async function linkAct(act,id){
  const l=(LK.info?.links||[]).find(x=>x.id===id); LK.err[id]="";
  if(act==="ask"){ LK.confirm=id; return renderSettings(); }
  if(act==="no"){ LK.confirm=null; return renderSettings(); }
  if(act==="review") return openLinkReview(id);
  if(act==="reconnect") return linkConnect({id});
  if(act==="retry"){ LK.want=id; try{ await linkApi("retry",{id}); }catch(x){ LK.err[id]=x.message; } await linksLoad(); renderSettings(); return linksWatch(); }
  LK.busy[id]={sync:"Syncing…",keep:"Disconnecting…",drop:"Disconnecting…",cancel:"Cancelling…",remove:"Removing…"}[act]||"…"; LK.confirm=null; renderSettings();
  try{
    if(act==="sync"){ const r=await linkApi("sync",{id}); toast(`Synced ${l?.name||"your account"}: ${r.count} position${r.count===1?"":"s"}`); }
    else if(act==="keep"||act==="drop"||act==="remove") await linkApi("disconnect",{id,keep:act==="keep"});
    else await linkApi("cancel",{id});
  }catch(x){ LK.err[id]=x.message; }
  delete LK.busy[id]; await linksLoad(); renderSettings();
}

/* the review sheet: which accounts, what's in them, and nothing counted twice */
async function openLinkReview(id){
  $("#lkrev")?.remove();
  const d=document.createElement("dialog"); d.className="sets imp lkrev"; d.id="lkrev"; d.setAttribute("aria-label","Review linked account");
  document.body.appendChild(d); d.addEventListener("close",()=>d.remove()); d.addEventListener("click",e=>{ if(e.target===d) d.close(); });
  d.innerHTML=`<div class="shead"><div><h2>Reading your holdings…</h2></div><button class="x" aria-label="Close">${ic("close",16)}</button></div><div class="sbody"></div>`;
  d.querySelector(".x").onclick=()=>d.close(); d.showModal();
  let P=null;
  try{ const r=await fetch("/api/me/links?preview="+encodeURIComponent(id),{headers:meHeaders()}); P=(await r.json()).preview; }catch(e){}
  if(!P){   // the holdings it found are gone (OpenTicker restarted): read them again and reopen the review when they're back
    let msg="Reading your holdings again. This opens again when they're ready.";
    try{ await linkApi("retry",{id}); LK.want=id; await linksLoad(); if($("#sets")) renderSettings(); linksWatch(); }catch(x){ msg=x.message; }
    d.querySelector(".sbody").innerHTML=`<p class="imsg">${esc(msg)}</p>`; return; }
  const L=P.link, accts=Object.entries(P.accounts).sort((a,b)=>b[1]-a[1]), off=new Set(P.off||[]), firstTime=!L.synced;
  const mine=new Set((me?.positions||[]).filter(p=>!p.source&&p.note!=="sample").map(p=>p.t));
  let dropMine=true, done=null;
  const draw=()=>{
    const rows=P.rows.filter(r=>!off.has(r.account)), n=rows.length, tick=new Set(rows.map(r=>r.t));
    const dup=[...tick].filter(t=>mine.has(t)).sort(), est=rows.filter(r=>r.estimated).length;
    const sk=P.skipped, parts=[sk.cash?"cash":"",sk.crypto?`${sk.crypto} crypto holding${sk.crypto===1?"":"s"}`:"",sk.options?`${sk.options} option${sk.options===1?"":"s"}`:"",
      sk.short?`${sk.short} short position${sk.short===1?"":"s"}`:"",sk.foreign?.length?`${sk.foreign.length} priced in another currency (${sk.foreign.slice(0,4).join(", ")}${sk.foreign.length>4?" and others":""})`:"",sk.other?.length?`${sk.other.length} with no prices on Yahoo (${sk.other.slice(0,4).join(", ")}${sk.other.length>4?" and others":""})`:""].filter(Boolean);
    const skipLine=parts.length?` Leaving out ${parts.length>1?parts.slice(0,-1).join(", ")+" and "+parts.at(-1):parts[0]}.`:"";
    const list=t=>t.length<=3?t.join(", "):`${t.slice(0,3).join(", ")} and ${t.length-3} more`;
    const byT=new Map(); rows.forEach(r=>{ const e=byT.get(r.t)||{t:r.t,shares:0,cost:0,accts:new Set(),est:false}; e.shares+=r.shares; e.cost+=r.shares*r.cost; e.accts.add(r.account); e.est=e.est||r.estimated; byT.set(r.t,e); });
    const agg=[...byT.values()].sort((a,b)=>b.cost-a.cost);
    const body=done?`<div class="idone">${ic("check",18)}<div><b>Added ${done} position${done===1?"":"s"} from ${esc(L.name)}.</b><small>They update every trading day after the close. To change what's included, use Sync now or Disconnect in Settings, Accounts.</small></div></div>`
      :!P.rows.length?`<p class="imsg">${esc(L.name)} didn't have any stock or fund positions OpenTicker can follow.${esc(skipLine)}</p>`
      :`<p class="imsg">Found ${P.rows.length} holding${P.rows.length===1?"":"s"} in ${accts.length} account${accts.length===1?"":"s"}.${esc(skipLine)}${est?` ${est===n?"No cost came with them":"Some came without a cost"}, so gains for those start from today's price.`:""}</p>
       ${accts.length>1?`<div class="lkaccts" role="group" aria-label="Accounts to include">${accts.map(([a,c])=>`<label class="lkacc"><input type="checkbox" data-acc="${esc(a)}" ${off.has(a)?"":"checked"}><span>${esc(a||"Account")}${(P.off||[]).includes(a)?`<small>Already linked directly</small>`:""}</span><em>${c}</em></label>`).join("")}</div>`:""}
       <div class="itbl"><table><thead><tr><th class="l">Ticker</th><th>Shares</th><th>Cost per share</th><th>Cost</th></tr></thead><tbody>${agg.map(r=>`<tr><td class="l tk">${esc(r.t)}${r.accts.size>1?`<small class="lkn">${r.accts.size} accounts</small>`:""}</td><td>${(+r.shares.toFixed(4)).toLocaleString("en-US")}</td><td>${r.est?"–":money(r.cost/r.shares)}</td><td>${r.est?"–":"$"+Math.round(r.cost).toLocaleString("en-US")}</td></tr>`).join("")||`<tr><td class="l" colspan="4">No accounts picked</td></tr>`}</tbody></table></div>
       ${dup.length?`<label class="lkdup"><input type="checkbox" id="lkDrop" ${dropMine?"checked":""}><span>Replace the ${esc(list(dup))} you entered yourself, so ${dup.length===1?"it isn't":"they aren't"} counted twice</span></label>`:""}
       ${L.full_access?`<p class="hint inote">${esc(L.name)}'s sign-in can't be limited to reading. OpenTicker only ever reads your positions, and you can disconnect any time.</p>`:`<p class="hint inote">OpenTicker can only read ${esc(L.name)}. It can't trade or move money.</p>`}`;
    d.innerHTML=`<div class="shead"><div><h2>${done?"Linked":`Add from ${esc(L.name)}`}</h2><small class="isub">${done?esc(L.name):"Check what was found. Nothing is added until you say so."}</small></div><button class="x" aria-label="Close">${ic("close",16)}</button></div>
      <div class="sbody">${body}</div>
      <div class="ifoot"><span class="err" id="lkErr"></span>${done||!P.rows.length?`<button class="btn" id="lkOk">${done?"Done":"Close"}</button>`:`<button class="btn ghost" id="lkNo">${firstTime?"Don't add":"Cancel"}</button><button class="btn" id="lkGo" ${n?"":"disabled"}>Add ${n} position${n===1?"":"s"}</button>`}</div>`;
    d.querySelector(".x").onclick=()=>d.close(); $("#lkOk")&&($("#lkOk").onclick=()=>d.close());
    $("#lkNo")&&($("#lkNo").onclick=async()=>{ d.close(); if(firstTime){ await linkApi("cancel",{id}).catch(()=>{}); await linksLoad(); if($("#sets")) renderSettings(); } });
    d.querySelectorAll("[data-acc]").forEach(c=>c.onchange=()=>{ c.checked?off.delete(c.dataset.acc):off.add(c.dataset.acc); draw(); });
    $("#lkDrop")&&($("#lkDrop").onchange=e=>{ dropMine=e.target.checked; });
    $("#lkGo")&&($("#lkGo").onclick=async()=>{ const b=$("#lkGo"); b.disabled=true; b.textContent="Adding…";
      try{ const r=await linkApi("apply",{id,off:[...off],drop_mine:dup.length>0&&dropMine}); done=r.count; draw(); await linksLoad(); if($("#sets")) renderSettings(); }
      catch(x){ b.disabled=false; b.textContent=`Add ${n} position${n===1?"":"s"}`; $("#lkErr").textContent=x.message; } });
  };
  draw();
}

/* the portfolio's line about where positions come from */
function linksLine(){
  const L=(me?.links||[]).filter(l=>l.synced); if(!L.length) return "";
  const bad=L.filter(l=>l.error||l.status==="auth"), last=Math.max(...L.map(l=>l.synced||0));
  const names=L.map(l=>l.name), nm=names.length>1?names.slice(0,-1).join(", ")+" and "+names.at(-1):names[0];
  return `<div class="lkline">${ic("link",13)}<span>${bad.length?`Couldn't reach ${esc(bad.map(l=>l.name).join(" or "))}. Showing positions from ${esc(linkWhen(Math.min(...bad.map(l=>l.synced))))}.`:`Synced from ${esc(nm)} ${esc(linkWhen(last))}.`}</span><button type="button" class="lnk" id="lkSync">Sync now</button><button type="button" class="lnk" id="lkSet">Accounts</button></div>`;
}
function bindLinksLine(){
  $("#lkSync")&&($("#lkSync").onclick=async e=>{ const b=e.currentTarget; b.disabled=true; b.textContent="Syncing…";
    try{ const r=await linkApi("sync",{}); toast(`Synced ${r.count} position${r.count===1?"":"s"}`); }catch(x){ toast(x.message); b.disabled=false; b.textContent="Sync now"; } });
  $("#lkSet")&&($("#lkSet").onclick=()=>openSettings("accounts"));
}
const linkName=id=>(me?.links||[]).find(l=>l.id===id)?.name||"a linked account";
if(typeof COMMANDS!=="undefined") COMMANDS.push({cmd:"accounts",label:"Link a brokerage",hint:"Monarch, IBKR, Robinhood",icon:"link",keys:"link account brokerage broker monarch ibkr interactive brokers robinhood sync import positions mcp",run:()=>openSettings("accounts")});
