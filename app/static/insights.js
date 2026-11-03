/* OpenTicker: insight features that read across data sources.
   - Your brief: what changed across the stocks you own or watch (price action here, research from /api/brief)
   - Portfolio X-ray: sector mix vs the S&P 500 (looking through funds), concentration, overlap, risk, income
   - Event markers for the stock price chart
   Uses globals from index.html, pages.js and stock-tabs.js. */

let nextTab=null;                              // open the stock page on this tab (set before openDrawer)
function openStock(t,tab){ nextTab=tab&&tab!=="overview"?tab:null; if(drawerOpen&&sel===t){ if(nextTab){ setTab(nextTab); nextTab=null; } return; } openDrawer(t); }
const nyDate=ts=>new Date(ts*1000).toLocaleDateString("en-CA",{timeZone:"America/New_York"});
const mySyms=()=>[...new Set([...(me?.watch||[]),...(me?.positions||[]).map(p=>p.t)])];

/* ======================= Your brief ======================= */
let BRIEF=null, briefAt=0, briefAll=false;
async function loadBrief(force){
  if(!force&&Date.now()-briefAt<(BRIEF?.pending?8e3:90e3)) return;
  briefAt=Date.now();
  try{ BRIEF=await (await fetch("/api/brief")).json(); }catch(e){ return; }
  renderBrief(); if(page==="market") renderMarket();
}
function dailySd(a,n=60){ const r=[]; for(let k=a.length-1;k>0&&r.length<n;k--) if(a[k]!=null&&a[k-1]!=null) r.push(a[k]/a[k-1]-1); if(r.length<20) return null; const m=r.reduce((x,y)=>x+y,0)/r.length; return Math.sqrt(r.reduce((x,y)=>x+(y-m)**2,0)/(r.length-1)); }
function priceItems(){
  const out=[], today=nyToday();
  mySyms().forEach(t=>{
    const a=base?.px?.[t], F=facts(t); if(!a||!F||F.last==null) return;
    const sd=dailySd(a), c=F.chg;
    if(c!=null&&Math.abs(c)>=Math.max(0.03,sd?2*sd:0)) out.push({t,kind:"move",tone:cls(c),date:today,score:85+Math.min(10,Math.abs(c)*100),
      head:`${c>0?"Up":"Down"} ${pc(Math.abs(c),1)} today`,text:sd?`about ${(Math.abs(c)/sd).toFixed(1)}× its usual daily move`:"",tab:"overview",short:`${t} ${pct(c,1)}`});
    if(F.hi&&F.last>=F.hi*0.999&&F.lo<F.hi*0.9) out.push({t,kind:"high",tone:"up",date:today,score:65,head:"New 52-week high",text:`at ${money(F.last)}, ${pct(F.lo?F.last/F.lo-1:null,0)} above its low`,tab:"overview",short:`${t} at a 52-week high`});
    else if(F.lo&&F.last<=F.lo*1.001&&F.hi>F.lo*1.1) out.push({t,kind:"low",tone:"down",date:today,score:65,head:"New 52-week low",text:`at ${money(F.last)}, ${pc(1-F.last/F.hi,0)} below its high`,tab:"overview",short:`${t} at a 52-week low`});
    // 200-day cross in the last three sessions
    if(F.ma200){ for(let back=0;back<3;back++){ const k=a.length-1-back; if(a[k]==null||a[k-1]==null) continue;
      const ma=(j)=>{ let s=0,n=0; for(let i=j;i>j-200&&i>=0;i--) if(a[i]!=null){s+=a[i];n++;} return n>150?s/n:null; };
      const m0=ma(k-1), m1=ma(k); if(m0&&m1&&Math.sign(a[k]-m1)!==Math.sign(a[k-1]-m0)){ const up=a[k]>m1;
        out.push({t,kind:"ma",tone:up?"up":"down",date:base.dates[k],score:50,head:`Crossed ${up?"above":"below"} its 200-day average`,text:`a common line between an uptrend and a downtrend (${money(m1)})`,tab:"overview",short:`${t} ${up?"above":"below"} its 200-day`}); break; } } }
    const e=EARN[t];
    if(e&&e.reported!=null&&e.date>=shiftDays(today,-3)&&e.date<=today){ const rx=reaction(t,e.date,e.timing==="BMO"?9:16);
      out.push({t,kind:"reported",tone:cls(e.surprise),date:e.date,score:82,head:e.surprise==null?"Reported earnings":`${e.surprise>=0?"Beat":"Missed"} earnings estimates by ${pc(Math.abs(e.surprise)/100,0)}`,
        text:rx!=null?`and the stock moved ${pct(rx,1)} the next session`:"",tab:"overview",short:`${t} ${e.surprise==null?"reported":e.surprise>=0?"beat estimates":"missed estimates"}`}); }
    else if(e&&e.reported==null&&e.date>=today&&e.date<=shiftDays(today,7)) out.push({t,kind:"earnings",tone:"",date:e.date,future:true,score:60,
      head:`Earnings ${dayLabel(e.date)==="Today"?"today":dayLabel(e.date)}`,text:`${e.timing==="BMO"?"before the open":e.timing==="AMC"?"after the close":""}${e.epsEst!=null?`${e.timing==="BMO"||e.timing==="AMC"?", ":""}EPS expected $${e.epsEst.toFixed(2)}`:""}`,tab:"options",short:`${t} reports ${dayLabel(e.date)==="Today"?"today":dayLabel(e.date)}`});
  });
  return out;
}
function briefItems(){
  const px=priceItems(), server=(BRIEF?.items||[]).map(x=>({...x}));
  // the server's earnings item (with the options-implied move) replaces the plain one
  const withMove=new Set(server.filter(x=>x.kind==="earnings").map(x=>x.t));
  const all=[...px.filter(x=>!(x.kind==="earnings"&&withMove.has(x.t))),...server];
  all.forEach(x=>{ if(!x.short) x.short=`${x.t} ${x.head.charAt(0).toLowerCase()+x.head.slice(1)}`; });
  return all.sort((a,b)=>(b.score-a.score)||String(b.date).localeCompare(String(a.date)));
}
function whenLabel(x){ const today=nyToday(); if(x.future) return dayLabel(x.date); if(x.date===today) return "Today"; return dayLabel(x.date); }
function briefRows(items){
  return `<ul class="brief">${items.map(x=>`<li class="${x.tone||""}"><button class="bl" data-open="${esc(x.t)}" data-open-tab="${esc(x.tab||"")}"><i aria-hidden="true"></i><b class="btk">${esc(x.t)}</b><span class="bt"><b>${esc(x.head)}</b>${x.text?` <span>${esc(x.text)}</span>`:""}</span><span class="bw">${esc(whenLabel(x))}</span></button></li>`).join("")}</ul>`;
}
function renderBrief(){
  const el=$("#s-brief"); if(!el) return;
  const show=page==="mine"&&mySyms().length; el.hidden=!show; if(!show) return;
  const items=briefItems(), n=mySyms().length, pend=BRIEF?.pending||0;
  const top=items.slice(0,3).map(x=>`<b>${esc(x.short)}</b>`), joined=top.length>1?top.slice(0,-1).join(", ")+" and "+top[top.length-1]:top[0];
  const lead=items.length?`<p class="blead">${items.length} update${items.length===1?"":"s"} across your ${n} stocks. ${items.length>1?"Most notable":"The one to know"}: ${joined}.</p>`
    :`<p class="blead">${BRIEF?`Quiet: nothing notable across your ${n} stocks right now.`:"Gathering research for your stocks…"}</p>`;
  const list=briefAll?items:items.slice(0,7);
  el.innerHTML=`<div class="ph"><div><h2>Your brief</h2><div class="hint">Price moves, analyst actions, insider trades, options activity and earnings across everything you own or watch.${pend?` <span class="pend"><i class="dot on"></i>Still reading research for ${pend} more…</span>`:""}</div></div></div>
    ${lead}${typeof askRow==="function"?askRow(null,"portfolio"):""}${items.length?briefRows(list):""}${items.length>7?`<button class="lnk" data-brief-all>${briefAll?"Show fewer":`Show all ${items.length}`}</button>`:""}`;
}
document.addEventListener("click",e=>{
  const b=e.target.closest("[data-open],[data-brief-all]"); if(!b) return;
  if(b.dataset.briefAll!==undefined){ briefAll=!briefAll; renderBrief(); return; }
  e.stopPropagation(); openStock(b.dataset.open,b.dataset.openTab);
},true);
setInterval(()=>{ if(!document.hidden&&(page==="mine"||page==="market")&&me) loadBrief(); },4e3);

/* ======================= Portfolio X-ray ======================= */
function sectorOf(t){ return base.sectors?.[t]||detailCache[t]?.info?.sector||null; }
function fundSectorMix(f){ const m=new Map(); (base.funds[f]?.holdings||[]).forEach(h=>{ const s=sectorOf(h.t)||"Other"; m.set(s,(m.get(s)||0)+h.w/100); }); return m; }
/* your exposure, looking through any of the four funds you hold */
function lookThrough(weights){
  const sec=new Map(), names=new Map();
  weights.forEach((w,t)=>{
    const f=base.funds[t]&&!isPseudo(t)?t:null;
    if(f){ base.funds[f].holdings.forEach(h=>{ names.set(h.t,(names.get(h.t)||0)+w*h.w/100); const s=sectorOf(h.t)||"Other"; sec.set(s,(sec.get(s)||0)+w*h.w/100); }); return; }
    names.set(t,(names.get(t)||0)+w);
    const s=sectorOf(t)||(detailCache[t]?.info?.quoteType==="ETF"?"Other funds":"Unclassified"); sec.set(s,(sec.get(s)||0)+w);
  });
  return {sec,names};
}
function riskStats(a,b){
  const ra=[],rb=[]; const n=a.length;
  for(let k=Math.max(1,n-252);k<n;k++) if(a[k]!=null&&a[k-1]!=null&&b[k]!=null&&b[k-1]!=null){ ra.push(a[k]/a[k-1]-1); rb.push(b[k]/b[k-1]-1); }
  if(ra.length<40) return null;
  const m=x=>x.reduce((s,v)=>s+v,0)/x.length, ma=m(ra), mb=m(rb);
  let cov=0,vb=0,va=0; ra.forEach((v,i)=>{ cov+=(v-ma)*(rb[i]-mb); vb+=(rb[i]-mb)**2; va+=(v-ma)**2; });
  let peak=-Infinity, dd=0; for(let k=Math.max(0,n-252);k<n;k++){ const v=a[k]; if(v==null) continue; peak=Math.max(peak,v); dd=Math.min(dd,v/peak-1); }
  return {beta:cov/vb,vol:Math.sqrt(va/(ra.length-1)*252),volM:Math.sqrt(vb/(rb.length-1)*252),dd,days:ra.length};
}
let xrayLoading=false;
function renderXray(){
  const el=$("#s-xray"); if(!el) return;
  const f=base.funds[fund]; el.hidden=!(page==="mine"&&f?.holdings?.length>=1); if(el.hidden) return;
  const isP=fund==="Portfolio", W=new Map(f.holdings.map(h=>[h.t,h.w/100]));
  // sectors need company info for stocks outside the funds
  const missing=[...W.keys()].filter(t=>!sectorOf(t)&&!(base.funds[t]&&!isPseudo(t))&&!detailCache[t]);
  const needDiv=isP?[...W.keys()].filter(t=>!detailCache[t]):[];
  if((missing.length||needDiv.length)&&!xrayLoading){ xrayLoading=true; Promise.all([...new Set([...missing,...needDiv])].map(t=>loadDetail(t))).then(()=>{ xrayLoading=false; renderXray(); }); }
  const {sec,names}=lookThrough(W), spy=fundSectorMix("SPY");
  const rows=[...new Set([...sec.keys(),...spy.keys()])].map(s=>({s,me:sec.get(s)||0,m:spy.get(s)||0})).filter(r=>r.me>0.001||r.m>0.02).sort((a,b)=>b.me-a.me||b.m-a.m);
  const mx=Math.max(...rows.map(r=>Math.max(r.me,r.m)),0.01);
  const ws=[...W.values()].sort((a,b)=>b-a), top1=ws[0]||0, top3=ws.slice(0,3).reduce((a,b)=>a+b,0), effN=1/ws.reduce((a,w)=>a+w*w,0);
  const overlap=k=>{ const fw=new Map(base.funds[k].holdings.map(h=>[h.t,h.w/100])); let s=0; names.forEach((w,t)=>s+=Math.min(w,fw.get(t)||0)); return s; };
  const ov=["SPY","QQQ","SMH"].filter(k=>base.funds[k]).map(k=>({k,v:overlap(k)})).sort((a,b)=>b.v-a.v);
  const R=riskStats(base.px[fund]||[],base.px.SPY||[]);
  let income=null, val=0, payers=0;
  if(isP){ income=0; positionsAgg().forEach(p=>{ const last=lastValid(base.px[p.t]||[]); if(last==null) return; val+=last*p.shares; const i=detailCache[p.t]?.info||{}; const dr=i.dividendRate??(i.trailingAnnualDividendRate||0); if(dr){ income+=dr*p.shares; payers++; } }); }
  // takeaways
  const ins=[], over=rows.filter(r=>r.me-r.m>0.05&&!/Unclassified|Other/.test(r.s)).sort((a,b)=>(b.me-b.m)-(a.me-a.m))[0], under=rows.filter(r=>r.m-r.me>0.05).sort((a,b)=>(b.m-b.me)-(a.m-a.me))[0];
  const what=isP?"your portfolio":"your watchlist";
  if(over) ins.push({tone:"",html:`<b>Tilted toward ${esc(over.s.toLowerCase())}:</b> ${pc(over.me,0)} of ${what} versus ${pc(over.m,0)} of the S&amp;P 500${over.m>0.01?`, about ${(over.me/over.m).toFixed(1)}× the market's weight`:""}.${under?` Lightest versus the market in ${esc(under.s.toLowerCase())} (${pc(under.me,0)} vs ${pc(under.m,0)}).`:""}`});
  if(R) ins.push({tone:R.beta>1.3?"down":R.beta<0.8?"up":"",html:`<b>${R.beta>1.3?"More volatile than the market":R.beta<0.8?"Calmer than the market":"Moves with the market"}:</b> a beta of ${R.beta.toFixed(2)} means a 1% move in the S&amp;P 500 has come with about a ${R.beta.toFixed(1)}% move in ${what}. Its worst drop in the past year was ${pc(R.dd,0)}.`});
  if(ws.length<=4) ins.push({tone:top1>0.35?"down":"",html:`<b>${ws.length} positions</b>, the largest at ${pc(top1,0)}${isP?" of the value":""}. ${top1>0.35?"One stock drives much of your result, so its news matters most.":"Fairly even sizes."}`});
  else ins.push({tone:top3>0.6?"down":"",html:`<b>${top3>0.6?"Concentrated":top3>0.4?"Moderately concentrated":"Well spread"}:</b> the top three positions are ${pc(top3,0)}${isP?" of the value":""}, which behaves like ${effN.toFixed(1)} equal-sized holdings.`});
  if(ov[0]) ins.push({tone:"",html:`<b>${pc(ov[0].v,0)} overlaps with ${ov[0].k}</b>, counting the stocks inside any funds you hold.${ov[0].v>0.6?` Much of ${what} could be replicated with the fund.`:""}`});
  if(isP&&income!=null&&val) ins.push({tone:"",html:income?`<b>About ${money(income)} a year in dividends</b>, a ${pc(income/val,2)} yield, from ${payers} of ${positionsAgg().length} positions.`:"<b>No dividend income</b> from these positions."});
  const stat=(l,v,k,c="")=>`<div><div class="lbl">${l}</div><div class="v ${c}">${v}</div>${k?`<div class="ks">${k}</div>`:""}</div>`;
  el.innerHTML=`<div class="ph"><div><h2>${isP?"Portfolio":"Watchlist"} X-ray</h2><div class="hint">${isP?"Weighted by value.":"Equal weight."} Funds you hold are looked through to the stocks inside them. Risk uses the last year of daily prices against the S&amp;P 500.</div></div></div>
    <div class="xray"><div>${insightList(ins)}
      <div class="kf">${R?stat("Beta",R.beta.toFixed(2),"vs S&amp;P 500")+stat("Volatility",pc(R.vol,0),`a year; market ${pc(R.volM,0)}`)+stat("Worst drop",pc(R.dd,0),"past year","down"):""}${stat("Largest position",pc(top1,0),ws.length>3?`top 3: ${pc(top3,0)}`:`of ${ws.length} positions`)}${ov[0]?stat("Most overlap",`${pc(ov[0].v,0)}`,`with ${ov[0].k}${ov[1]?`; ${ov[1].k} ${pc(ov[1].v,0)}`:""}`):""}${isP&&income!=null?stat("Dividend income",income?money(income):"$0",val&&income?`${pc(income/val,2)} yield`:""):""}</div></div>
      <div><h4 class="h4">Sector mix vs the S&amp;P 500</h4><div class="xs">${rows.map(r=>{ const d=r.me-r.m; return `<div class="xr"><span class="xn">${esc(r.s)}</span><span class="xb"><i class="me" style="width:${(r.me/mx*100).toFixed(1)}%"></i><i class="mk" style="width:${(r.m/mx*100).toFixed(1)}%"></i></span><span class="num xv">${pc(r.me,0)}</span><span class="num xd ${Math.abs(d)<0.02?"":d>0?"up":"down"}">${Math.abs(d)<0.005?"=":(d>0?"+":"−")+Math.round(Math.abs(d)*100)}</span></div>`; }).join("")}</div>
      <div class="legend" style="margin-top:8px"><span><i class="sw" style="background:var(--accent)"></i>${isP?"Your portfolio":"Your watchlist"}</span><span><i class="sw" style="background:var(--ink-3);opacity:.5"></i>S&amp;P 500</span><span class="ks">right column: difference in points</span></div></div></div>`;
}

/* ======================= events on the price chart ======================= */
let showEv=load("ev","1")==="1";
function chartEvents(t){
  const ev=[], today=nyToday();
  (earnHist[t]?.rows||[]).filter(x=>x.eps!=null&&x.date<=today).forEach(x=>ev.push({date:x.date,kind:"E",tone:x.surprise==null?"":x.surprise>=0?"up":"down",
    text:`Earnings: ${x.surprise==null?"reported":`${x.surprise>=0?"beat":"missed"} by ${pc(Math.abs(x.surprise)/100,1)}`}${x.epsEst!=null?` (EPS $${x.eps.toFixed(2)} vs $${x.epsEst.toFixed(2)} expected)`:""}`}));
  const e=EARN[t]; if(e&&e.reported==null&&e.date>=today) ev.push({date:e.date,kind:"E",tone:"",future:true,text:`Next earnings ${dayLabel(e.date)}`});
  (xpeek("analysts",{t})?.data?.changes||[]).forEach(c=>{ const a=(c.action||"").toLowerCase(); if(a==="up"||a==="down") ev.push({date:c.date,kind:a==="up"?"▲":"▼",tone:a==="up"?"up":"down",text:`${a==="up"?"Upgrade":"Downgrade"}: ${c.firm} to ${c.to}${c.pt?`, target ${money(c.pt)}`:""}`}); });
  (xpeek("events",{t})?.data?.dividends||[]).forEach(d=>ev.push({date:d.date,kind:"D",tone:"",text:`Dividend ${money(d.amount)} (ex-date)`}));
  (xpeek("ownership",{t})?.data?.insiders||[]).filter(x=>x.kind==="buy").forEach(x=>ev.push({date:x.date,kind:"B",tone:"up",text:`Insider buy: ${String(x.insider||"").toLowerCase().replace(/\b[a-z]/g,c=>c.toUpperCase())}${x.value?` ${usdB(x.value)}`:""}`}));
  return ev.filter(x=>x.date);
}
/* place events on chart indexes; returns {byK: Map(k -> [events])} */
function placeEvents(t,P){
  if(!showEv||!P?.length) return null;
  const d0=nyDate(P[0][0]), dates=P.map(p=>nyDate(p[0])), byK=new Map();
  chartEvents(t).forEach(x=>{ if(x.date<d0||x.future) return; let k=dates.findIndex(d=>d>=x.date); if(k<0) return; if(!byK.has(k)) byK.set(k,[]); byK.get(k).push(x); });
  return byK.size?byK:null;
}
function eventLane(byK,X,y){
  let s="";
  byK.forEach((list,k)=>{ const kinds=[...new Map(list.map(x=>[x.kind+x.tone,x])).values()];
    kinds.forEach((x,j)=>{ const cx=X(k), cy=y-j*13, col=x.tone==="up"?"var(--up)":x.tone==="down"?"var(--down)":"var(--ink-3)";
      s+=x.kind==="▲"||x.kind==="▼"?`<path d="${x.kind==="▲"?`M${cx-5},${cy+4}L${cx+5},${cy+4}L${cx},${cy-5}Z`:`M${cx-5},${cy-4}L${cx+5},${cy-4}L${cx},${cy+5}Z`}" fill="${col}"/>`
        :`<circle cx="${cx}" cy="${cy}" r="6" fill="${x.kind==="E"?col:"var(--panel)"}" stroke="${col}" stroke-width="1.4"/><text x="${cx}" y="${cy+3.3}" font-size="8.5" font-weight="700" text-anchor="middle" fill="${x.kind==="E"?"var(--panel)":col}">${x.kind}</text>`; }); });
  return s;
}
