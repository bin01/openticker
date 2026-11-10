/* OpenTicker: interaction layer. The header search doubles as a command bar (⌘K), recent stocks,
   the phone tab bar, and small touches. Icons (IC, ic) are defined at the top of index.html's script. */

/* ---------- command bar: pages, funds, actions and stocks in one box ---------- */
const COMMANDS=[
  ...PAGES.map(([k,l])=>({cmd:"page:"+k,label:l,hint:"Go to",icon:k,keys:l+" "+k,run:()=>goPage(k)})),
  ...FUND_LIST.map(f=>({cmd:"fund:"+f,label:`${f} dashboard`,hint:"Fund",icon:"funds",keys:f+" fund",fund:f,run:()=>pickFund(f)})),   // the fund's name joins the keys when matching: base isn't loaded yet here
  {cmd:"fund:Watchlist",label:"Your watchlist",hint:"My stocks",icon:"star",keys:"watchlist watch",run:()=>pickFund("Watchlist")},
  {cmd:"fund:Portfolio",label:"Your portfolio",hint:"My stocks",icon:"mine",keys:"portfolio positions holdings mine",run:()=>pickFund("Portfolio")},
  {cmd:"edit:watch",label:"Edit watchlist",hint:"My stocks",icon:"star",keys:"edit watchlist remove add tickers",run:()=>{ pickFund("Watchlist"); setTimeout(()=>{ $("#s-mine")?.scrollIntoView({behavior:"smooth"}); $("#wT")?.focus({preventScroll:true}); },120); }},
  {cmd:"edit:pos",label:"Edit positions",hint:"My stocks",icon:"mine",keys:"edit portfolio positions shares cost remove lots",run:()=>{ pickFund("Portfolio"); setTimeout(()=>$("#s-mine")?.scrollIntoView({behavior:"smooth"}),120); }},
  {cmd:"brief",label:"Your brief",hint:"My stocks",icon:"mine",keys:"brief news updates what changed",run:()=>{ pickFund(fundFor.mine); setTimeout(()=>$("#s-brief")?.scrollIntoView({behavior:"smooth"}),120); }},
  {cmd:"xray",label:"Portfolio X-ray",hint:"My stocks",icon:"mine",keys:"x-ray xray sector exposure beta risk overlap dividends income",run:()=>{ pickFund("Portfolio"); setTimeout(()=>$("#s-xray")?.scrollIntoView({behavior:"smooth"}),120); }},
  {cmd:"cal:earn",label:"Earnings calendar",hint:"Calendar",icon:"calendar",keys:"earnings reports",run:()=>{ calTab="earn"; save("calTab","earn"); goPage("calendar"); renderCalendar(); }},
  {cmd:"cal:econ",label:"Economic calendar",hint:"Calendar",icon:"calendar",keys:"economy economic cpi jobs fed data",run:()=>{ calTab="econ"; save("calTab","econ"); goPage("calendar"); renderCalendar(); }},
  {cmd:"cal:ipo",label:"IPO calendar",hint:"Calendar",icon:"calendar",keys:"ipo listings",run:()=>{ calTab="ipo"; save("calTab","ipo"); goPage("calendar"); renderCalendar(); }},
  {cmd:"scr:custom",label:"Build a stock screen",hint:"Screener",icon:"screener",keys:"screen filter find custom build",run:()=>{ scrSel="custom"; save("scr","custom"); goPage("screener"); renderScreener(); }},
  ...[["day_gainers","Today's biggest gainers"],["day_losers","Today's biggest losers"],["most_actives","Most active stocks"]].map(([k,l])=>({cmd:"scr:"+k,label:l,hint:"Screener",icon:"screener",keys:l+" movers",run:()=>{ scrSel=k; save("scr",k); goPage("screener"); renderScreener(); }})),
  {cmd:"levels",label:"Support and resistance",hint:"Levels",icon:"levels",keys:"levels support resistance chart technical pivot",run:()=>openLevels(drawerOpen?sel:null)},
  {cmd:"alerts",label:"Alerts",hint:"Open",icon:"bell",keys:"alerts notifications bell push",run:()=>openAlerts()},
  {cmd:"theme:light",label:"Light theme",hint:"Theme",icon:"sun",keys:"light theme appearance",run:()=>setTheme("light")},
  {cmd:"theme:dark",label:"Dark theme",hint:"Theme",icon:"moon",keys:"dark theme appearance night",run:()=>setTheme("dark")},
  {cmd:"theme:auto",label:"Match system theme",hint:"Theme",icon:"auto",keys:"auto system theme appearance",run:()=>setTheme("auto")},
];
function pickFund(k){ const p=PAGE_FUNDS.funds.includes(k)?"funds":"mine"; setFund(k); if(page!==p) goPage(p); else render(); }
function setTheme(t){ theme=t; save("theme",t); applyTheme(); }
function commandMatches(q){
  const Q=q.toLowerCase().trim(); if(!Q) return [];
  return COMMANDS.map(c=>{ const l=c.label.toLowerCase(), k=(c.keys+(c.fund?" "+(base?.funds?.[c.fund]?.name||"").replace(/[()]/g," "):"")).toLowerCase(); const s=l.startsWith(Q)?0:l.split(/\s+/).some(w=>w.startsWith(Q))?1:k.split(/\s+/).some(w=>w.startsWith(Q))?2:l.includes(Q)?3:9; return [s,c]; })
    .filter(x=>x[0]<9).sort((a,b)=>a[0]-b[0]).slice(0,Q.length<=2?2:4).map(x=>x[1]);
}
let recent=[]; try{ recent=JSON.parse(load("recent","[]")).filter(t=>typeof t==="string").slice(0,6); }catch(e){}
function pushRecent(t){ recent=[t,...recent.filter(x=>x!==t)].slice(0,6); save("recent",JSON.stringify(recent)); }
function quickItems(){
  const r=recent.map(t=>({t,n:base?nameOf(t):t,funds:[],exch:"Recent"}));
  return [...r,...COMMANDS.filter(c=>c.cmd.startsWith("page:")&&c.cmd!=="page:"+page)];
}
function runCmd(c){ $("#ts").value=""; sItems=[]; showResults(); $("#ts").blur(); c.run(); }
document.addEventListener("click",e=>{ const b=e.target.closest("[data-cmd]"); if(!b) return; e.preventDefault(); e.stopPropagation(); const c=COMMANDS.find(x=>x.cmd===b.dataset.cmd); if(c) runCmd(c); },true);
document.addEventListener("keydown",e=>{
  if((e.metaKey||e.ctrlKey)&&(e.key==="k"||e.key==="K")){ e.preventDefault(); const i=$("#ts"); i.focus(); i.select(); }
});
{ const k=$(".skbd"); if(k) k.textContent=/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent)?"⌘K":"Ctrl K"; }

/* ---------- phone tab bar ----------
   Five slots, so labels fit and every target is wide enough for a thumb: the four pages you open every day,
   then More for Calendar, Screener, alerts and Settings. */
const TAB_PAGES=["market","mine","funds","levels"];
IC.more='<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>';
{
  const nav=document.createElement("nav"); nav.className="tabbar"; nav.id="tabbar"; nav.setAttribute("aria-label","Sections");
  nav.innerHTML=PAGES.filter(([k])=>TAB_PAGES.includes(k)).map(([k,l])=>`<a href="#${k}" data-page="${k}">${ic(k,21)}<span>${l}</span></a>`).join("")
    +`<button type="button" id="tbMore" aria-haspopup="menu" aria-expanded="false" aria-controls="tbMenu">${ic("more",21)}<span>More</span></button>`
    +`<div class="tbmenu" id="tbMenu" role="menu" hidden></div>`;
  document.body.appendChild(nav);
  const btn=$("#tbMore"), menu=$("#tbMenu");
  const close=()=>{ menu.hidden=true; btn.setAttribute("aria-expanded","false"); };
  btn.onclick=e=>{ e.stopPropagation(); if(!menu.hidden) return close();
    const rows=[...PAGES.filter(([k])=>!TAB_PAGES.includes(k)).map(([k,l])=>({k,l,icon:k,on:k===page})),
      {k:"alerts",l:"Alerts",icon:"bell"},{k:"settings",l:"Settings",icon:"gear"}];
    menu.innerHTML=rows.map(r=>`<button type="button" role="menuitem" data-tbm="${r.k}" class="${r.on?"on":""}"${r.on?' aria-current="page"':""}>${ic(r.icon,18)}<span>${r.l}</span></button>`).join("");
    menu.hidden=false; btn.setAttribute("aria-expanded","true"); menu.querySelector("button")?.focus(); };
  menu.onclick=e=>{ const b=e.target.closest("[data-tbm]"); if(!b) return; close(); const k=b.dataset.tbm;
    if(k==="alerts") openAlerts(); else if(k==="settings") openSettings(); else goPage(k); };
  document.addEventListener("click",e=>{ if(!menu.hidden&&!e.target.closest("#tbMenu")) close(); });
  document.addEventListener("keydown",e=>{ if(e.key==="Escape"&&!menu.hidden){ close(); btn.focus(); } });
}
function renderTabbar(){
  document.querySelectorAll("#tabbar a").forEach(a=>{ const on=a.dataset.page===page; a.classList.toggle("on",on); if(on) a.setAttribute("aria-current","page"); else a.removeAttribute("aria-current"); });
  $("#tbMore")?.classList.toggle("on",!TAB_PAGES.includes(page));   // Calendar and Screener light up More
}
renderTabbar();

/* ---------- keyboard: rows, tiles, chart bars and sort headers ----------
   What you can click to open a stock, you can reach and open from the keyboard. Each list (a table's rows, the
   market map, a chart's bars, a list of movers) is one stop in the Tab order, so a 500-row table doesn't bury the
   rest of the page: Tab lands on the row you were last on, ↑ ↓ move (← → too on the map and charts), Home and End
   jump, Enter or Space opens. Sort headers are ordinary stops. Buttons and links inside a row work on their own. */
const KB_ITEM="tr[data-sel],tr[data-sig-t],li[data-sel],.tile[data-sel],g[data-sel]";
const KB_HEAD="th[data-sort],th.sortable,th[data-sig-k]";
function kbPrep(){
  const groups=new Map();
  document.querySelectorAll(`#app :is(${KB_ITEM}),#drawer :is(${KB_ITEM})`).forEach(el=>{
    if(!el.hasAttribute("tabindex")) el.setAttribute("tabindex","-1");
    const g=el.parentElement, l=groups.get(g); if(l) l.push(el); else groups.set(g,[el]); });
  groups.forEach(l=>{ const on=l.filter(x=>x.getAttribute("tabindex")==="0"); if(on.length===1) return;
    const keep=on[0]||l[0]; l.forEach(x=>{ const v=x===keep?"0":"-1"; if(x.getAttribute("tabindex")!==v) x.setAttribute("tabindex",v); }); });
  document.querySelectorAll(`#app :is(${KB_HEAD}),#drawer :is(${KB_HEAD})`).forEach(th=>{ if(!th.hasAttribute("tabindex")) th.setAttribute("tabindex","0"); });
}
new MutationObserver(()=>{ cancelAnimationFrame(kbPrep.r); kbPrep.r=requestAnimationFrame(kbPrep); }).observe(document.body,{childList:true,subtree:true});
/* the row you were on stays the list's Tab stop */
document.addEventListener("focusin",e=>{ const el=e.target; if(!el.matches?.(KB_ITEM)||el.getAttribute("tabindex")==="0") return;
  [...el.parentElement.children].forEach(x=>{ if(x!==el&&x.getAttribute("tabindex")==="0") x.setAttribute("tabindex","-1"); }); el.setAttribute("tabindex","0"); });
/* a way back to the same row or header after a redraw replaced it */
function kbFind(el){ const k=["data-sel","data-sig-t","data-sort","data-sig-k","data-c"].find(a=>el.hasAttribute(a)); if(!k) return null;
  const root=el.closest("#drawer,#app")||document; const q=`${el.tagName.toLowerCase()}[${k}="${CSS.escape(el.getAttribute(k))}"]`; return ()=>root.querySelector(q); }
function kbActivate(el){
  const again=kbFind(el);
  el.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,view:window}));   // what a click does; SVG has no .click()
  if(el.isConnected||document.activeElement&&document.activeElement!==document.body) return;
  const n=again?.(); if(!n) return; if(!n.hasAttribute("tabindex")) n.setAttribute("tabindex",n.matches(KB_HEAD)?"0":"-1"); n.focus({preventScroll:true});
}
document.addEventListener("keydown",e=>{
  const el=e.target; if(!(el instanceof Element)||e.metaKey||e.ctrlKey||e.altKey) return;
  const item=el.matches(KB_ITEM), head=!item&&el.matches(KB_HEAD); if(!item&&!head) return;
  if(e.key==="Enter"||e.key===" "){ e.preventDefault(); e.stopPropagation(); kbActivate(el); return; }
  if(!item) return;
  const two=el.matches(".tile,g"), fwd=e.key==="ArrowDown"||two&&e.key==="ArrowRight", back=e.key==="ArrowUp"||two&&e.key==="ArrowLeft";
  if(!fwd&&!back&&e.key!=="Home"&&e.key!=="End") return;   // ← → on a table row still change the time range
  const l=[...el.parentElement.children].filter(x=>x.matches(KB_ITEM)), i=l.indexOf(el);
  const n=l[e.key==="Home"?0:e.key==="End"?l.length-1:fwd?Math.min(l.length-1,i+1):Math.max(0,i-1)];
  e.preventDefault(); e.stopPropagation(); if(n&&n!==el){ n.focus(); n.scrollIntoView?.({block:"nearest",inline:"nearest"}); }
},true);
/* the hover card a tile or bar shows for the mouse, shown for the keyboard too */
document.addEventListener("focusin",e=>{ const el=e.target; if(!el.matches?.("[data-tip]")||!el.matches(":focus-visible")) return;
  const r=el.getBoundingClientRect(); showTip({clientX:Math.min(r.right,innerWidth-20)-8,clientY:r.bottom-6},el.dataset.tip); });
document.addEventListener("focusout",e=>{ if(e.target.matches?.("[data-tip]")) hideTip(); });
