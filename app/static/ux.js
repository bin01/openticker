/* OpenTicker: interaction layer. The header search doubles as a command bar (⌘K), recent stocks,
   the phone tab bar, and small touches. Icons (IC, ic) are defined at the top of index.html's script. */

/* ---------- command bar: pages, funds, actions and stocks in one box ---------- */
const COMMANDS=[
  ...PAGES.map(([k,l])=>({cmd:"page:"+k,label:l,hint:"Go to",icon:k,keys:l+" "+k,run:()=>goPage(k)})),
  ...FUND_LIST.map(f=>({cmd:"fund:"+f,label:`${f} dashboard`,hint:"Fund",icon:"funds",keys:f+" fund "+(base?.funds?.[f]?.name||""),run:()=>pickFund(f)})),
  {cmd:"fund:Watchlist",label:"Your watchlist",hint:"My stocks",icon:"star",keys:"watchlist watch",run:()=>pickFund("Watchlist")},
  {cmd:"fund:Portfolio",label:"Your portfolio",hint:"My stocks",icon:"mine",keys:"portfolio positions holdings mine",run:()=>pickFund("Portfolio")},
  {cmd:"edit:watch",label:"Edit watchlist",hint:"My stocks",icon:"star",keys:"edit watchlist remove add tickers",run:()=>openWatchEdit()},
  {cmd:"edit:pos",label:"Edit positions",hint:"My stocks",icon:"mine",keys:"edit portfolio positions shares cost remove lots",run:()=>openPosEdit()},
  {cmd:"brief",label:"Your brief",hint:"My stocks",icon:"mine",keys:"brief news updates what changed",run:()=>{ pickFund(fundFor.mine); setTimeout(()=>$("#s-brief")?.scrollIntoView({behavior:"smooth"}),120); }},
  {cmd:"xray",label:"Portfolio X-ray",hint:"My stocks",icon:"mine",keys:"x-ray xray sector exposure beta risk overlap dividends income",run:()=>{ pickFund("Portfolio"); setTimeout(()=>$("#s-xray")?.scrollIntoView({behavior:"smooth"}),120); }},
  {cmd:"cal:earn",label:"Earnings calendar",hint:"Calendar",icon:"calendar",keys:"earnings reports",run:()=>{ calTab="earn"; save("calTab","earn"); goPage("calendar"); renderCalendar(); }},
  {cmd:"cal:econ",label:"Economic calendar",hint:"Calendar",icon:"calendar",keys:"economy economic cpi jobs fed data",run:()=>{ calTab="econ"; save("calTab","econ"); goPage("calendar"); renderCalendar(); }},
  {cmd:"cal:ipo",label:"IPO calendar",hint:"Calendar",icon:"calendar",keys:"ipo listings",run:()=>{ calTab="ipo"; save("calTab","ipo"); goPage("calendar"); renderCalendar(); }},
  {cmd:"scr:custom",label:"Build a stock screen",hint:"Screener",icon:"screener",keys:"screen filter find custom build",run:()=>{ scrSel="custom"; save("scr","custom"); goPage("screener"); renderScreener(); }},
  ...[["day_gainers","Today's biggest gainers"],["day_losers","Today's biggest losers"],["most_actives","Most active stocks"]].map(([k,l])=>({cmd:"scr:"+k,label:l,hint:"Screener",icon:"screener",keys:l+" movers",run:()=>{ scrSel=k; save("scr",k); goPage("screener"); renderScreener(); }})),
  {cmd:"alerts",label:"Alerts",hint:"Open",icon:"bell",keys:"alerts notifications bell push",run:()=>openAlerts()},
  {cmd:"theme:light",label:"Light theme",hint:"Theme",icon:"sun",keys:"light theme appearance",run:()=>setTheme("light")},
  {cmd:"theme:dark",label:"Dark theme",hint:"Theme",icon:"moon",keys:"dark theme appearance night",run:()=>setTheme("dark")},
  {cmd:"theme:auto",label:"Match system theme",hint:"Theme",icon:"auto",keys:"auto system theme appearance",run:()=>setTheme("auto")},
];
function pickFund(k){ const p=PAGE_FUNDS.funds.includes(k)?"funds":"mine"; setFund(k); if(page!==p) goPage(p); else render(); }
function setTheme(t){ theme=t; save("theme",t); applyTheme(); }
function commandMatches(q){
  const Q=q.toLowerCase().trim(); if(!Q) return [];
  return COMMANDS.map(c=>{ const l=c.label.toLowerCase(), k=c.keys.toLowerCase(); const s=l.startsWith(Q)?0:l.split(/\s+/).some(w=>w.startsWith(Q))?1:k.split(/\s+/).some(w=>w.startsWith(Q))?2:l.includes(Q)?3:9; return [s,c]; })
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

/* ---------- phone tab bar ---------- */
{
  const nav=document.createElement("nav"); nav.className="tabbar"; nav.id="tabbar"; nav.setAttribute("aria-label","Sections");
  nav.innerHTML=PAGES.map(([k,l])=>`<a href="#${k}" data-page="${k}">${ic(k,21)}<span>${l}</span></a>`).join("");
  document.body.appendChild(nav);
}
function renderTabbar(){ document.querySelectorAll("#tabbar a").forEach(a=>{ const on=a.dataset.page===page; a.classList.toggle("on",on); if(on) a.setAttribute("aria-current","page"); else a.removeAttribute("aria-current"); }); }
renderTabbar();
