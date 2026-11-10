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
