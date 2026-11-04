/* OpenTicker: pages beyond the fund dashboards (Market, Calendar, Screener) and the router.
   Shares globals with the main script in index.html: base, me, model, fund, hz, $, esc, pct, cls, money, big, etc. */

/* ======================= router ======================= */
const PAGES=[["market","Market"],["funds","Funds"],["mine","My stocks"],["calendar","Calendar"],["screener","Screener"]];
const PAGE_FUNDS={funds:FUND_LIST,mine:["Watchlist","Portfolio"]};
let page=load("page","market"); if(!PAGES.some(p=>p[0]===page)) page="market";
const fundFor={funds:PAGE_FUNDS.funds.includes(load("fund","SPY"))?load("fund","SPY"):"SPY",mine:["Watchlist","Portfolio"].includes(load("fundMine",""))?load("fundMine",""):"Portfolio"};
const isDash=()=>!!PAGE_FUNDS[page];
const pageFund=p=>PAGE_FUNDS[p]?fundFor[p]:fundFor.funds;   // pages without a fund compare stocks with the last fund you picked
const X={};                      // research cache: "name|key" -> {data, at, loading, error}

function setHash(push){
  const h="#"+page+(drawerOpen&&sel?"/"+encodeURIComponent(sel):"");
  try{ if(location.hash!==h) history[push?"pushState":"replaceState"](null,"",h); }catch(e){}
}
function readHash(){
  const h=decodeURIComponent(location.hash.slice(1)); if(!h) return null;
  const [p,t]=h.split("/");
  if(PAGES.some(x=>x[0]===p)){ page=p; save("page",p); return t||null; }
  if(/^[A-Z][A-Z0-9^=.-]{0,11}$/.test(p)) return p;          // old links like #NVDA
  return null;
}
const hashT=readHash(); fund=pageFund(page);
function goPage(p,fromHistory){
  if(p===page){ if(!fromHistory) window.scrollTo({top:0,behavior:"smooth"}); return; }
  page=p; save("page",p); fund=pageFund(p);
  $("#app").innerHTML=""; window.scrollTo({top:0});
  if(!fromHistory){ if(drawerOpen) closeDrawer(); setHash(true); }
  render();
}
addEventListener("popstate",()=>{
  const old=page, t=readHash(), np=page; if(np!==old){ page=old; goPage(np,true); }
  if(t){ if(t!==sel||!drawerOpen) openDrawer(t); } else if(drawerOpen) closeDrawer();
});
function renderNav(){
  $("#mainnav").innerHTML=PAGES.map(([k,l])=>`<a href="#${k}" data-page="${k}" class="${k===page?"on":""}" ${k===page?'aria-current="page"':""}>${l}</a>`).join("");
  $("#toolbar").hidden=!isDash(); $("#tape").hidden=!isDash()||$("#tape").dataset.empty==="1";
  if(typeof renderTabbar==="function") renderTabbar();
}
function setFund(k){ fund=k; if(PAGE_FUNDS.funds.includes(k)){ fundFor.funds=k; save("fund",k); } else { fundFor.mine=k; save("fundMine",k); } }

async function xget(name,params,force){
  const key=name+"|"+JSON.stringify(params||{}), c=X[key];
  if(c&&!force&&(c.loading||Date.now()-c.at<(c.error?20e3:5*60e3))) return c;
  X[key]={...(c||{}),loading:true};
  // Yahoo fails for a moment now and then: try again quietly before showing anything, and if it still fails,
  // keep trying in the background and fill the section in when it answers
  const once=async()=>{ try{ const r=await fetch(`/api/x/${name}?`+new URLSearchParams(params||{})); const d=await r.json();
      return r.ok?{data:d,at:Date.now()}:{error:d.error||"Not available.",at:Date.now(),soft:r.status>=500}; }
    catch(e){ return {error:"Couldn't reach OpenTicker on this Mac.",at:Date.now()}; } };
  let res=await once();
  if(res.soft){ await new Promise(f=>setTimeout(f,2500)); res=await once(); }
  if(res.soft&&!c?.data){ res.error="Yahoo Finance isn't answering right now. This fills in on its own when it does."; res.later=true; }
  X[key]=res.error&&c?.data?{...c,loading:false,at:Date.now()-4*60e3}:res;   // a failed refresh keeps what's on screen
  if(res.later&&!xRetrying.has(key)){ xRetrying.add(key); (async()=>{ for(const wait of [20e3,60e3,180e3]){ await new Promise(f=>setTimeout(f,wait)); const r=await once(); if(!r.error){ X[key]=r; xRetrying.delete(key); render(); return; } } xRetrying.delete(key); })(); }
  return X[key];
}
const xRetrying=new Set();
const xpeek=(name,params)=>X[name+"|"+JSON.stringify(params||{})];

function renderPage(){
  if(page==="market") return renderMarket();
  if(page==="calendar") return renderCalendar();
  if(page==="screener") return renderScreener();
}

/* ======================= shared bits ======================= */
const nyToday=()=>new Date().toLocaleDateString("en-CA",{timeZone:"America/New_York"});
function dayLabel(d,today=nyToday()){
  if(d===today) return "Today";
  if(d===shiftDays(today,1)) return "Tomorrow";
  if(d===shiftDays(today,-1)) return "Yesterday";
  return new Date(d+"T12:00:00Z").toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",timeZone:"UTC"});
}
const errBox=(msg,name,params)=>{ const later=name&&xRetrying.has(name+"|"+JSON.stringify(params||{}));
  return `<div class="errbox${later?" later":""}">${later?`<i class="spin" aria-hidden="true"></i>`:""}<span>${esc(msg)}</span>${name?`<button class="lnk" data-retry-x="${esc(name)}" data-retry-p="${esc(JSON.stringify(params||{}))}">Try now</button>`:""}</div>`; };
const sk=(h=120)=>`<div class="sk" style="height:${h}px"></div>`;
function miniSpark(arr,w=120,h=34,color){ const pts=(arr||[]).map((v,i)=>[i,v]).filter(p=>p[1]!=null); if(pts.length<2) return ""; const b=pts[0][1]; return spark(pts.map(p=>[p[0],p[1]/b-1]),w,h,color); }
function insightList(items){
  return `<ul class="ins">${items.map(i=>`<li class="${i.tone||""}"><i aria-hidden="true"></i><div>${i.html}${i.tab?` <button class="lnk" data-tab="${i.tab}">${i.tabLabel||"Details"} ›</button>`:""}</div></li>`).join("")}</ul>`;
}

/* ======================= MARKET ======================= */
let mktRange=load("mktRange","1D"), sectorOpen=null, industryOpen=null;
const MKT_RANGES=["1D","1W","1M","3M","YTD","1Y"];
async function loadMarket(force){
  const tasks=[xget("macro",{},force),xget("screen",{name:"day_gainers"}),xget("screen",{name:"day_losers"}),xget("screen",{name:"most_actives"}),xget("econ")];
  for(const t of tasks) t.then?.(()=>{ if(page==="market") renderMarket(); });
  await Promise.allSettled(tasks); if(page==="market") renderMarket();
}
function macroView(){
  const m=xpeek("macro")?.data; if(!m) return null;
  const d=m.daily, today=nyToday(), last=m.intraday?.last||{}, n=d.dates.length;
  const out={};
  for(const sym of Object.keys(d.px)){
    const a=d.px[sym]; let i=n-1; while(i>=0&&a[i]==null) i--; if(i<0) continue;
    // Yahoo can leave today's daily bar empty for a while, so the intraday last stands in for it. Before today's
    // first trade (after midnight, on weekends) the intraday bars are the last session's: then compare that
    // session with the day before, not with itself
    const todayRow=d.dates[i]===today, liveToday=m.intraday?.day?.[sym]?m.intraday.day[sym]===today:true;
    const lastPx=todayRow||liveToday?last[sym]??a[i]:a[i];
    let p=todayRow||!liveToday?i-1:i; while(p>=0&&a[p]==null) p--;
    const prev=p>=0?a[p]:null;
    const rets={"1D":prev?lastPx/prev-1:null};
    for(const h of ["1W","1M","3M","YTD","1Y"]){ const s=startIndex(d.dates,h), f=firstValid(a,s); rets[h]=f?lastPx/f.v-1:null; }
    const sp=m.intraday?.spark?.[sym];   // a session that has barely started has too few points to draw; use the last few weeks instead
    out[sym]={last:lastPx,prev,rets,spark:sp&&sp.filter(x=>x!=null).length>=8?sp:a.slice(-30)};
  }
  // outside market hours, index futures show their move since the 4 pm close
  const ov=m.overnight;
  if(ov?.q) for(const [sym,f] of Object.entries(ov.q)) if(out[sym]&&f.last!=null){ out[sym]={...out[sym],last:f.last,overnight:f.chg,spark:f.spark}; }
  return {q:out,names:m.names,sectors:m.sectors,status:m.status};
}
function rateVal(v){ return v==null?null:(v>20?v/10:v); }
function spyBreadth(){
  const f=base?.funds?.SPY; if(!f) return null;
  let up=0,n=0,sum=0; const contrib=[];
  f.holdings.forEach(h=>{ const F=facts(h.t); if(!F||F.chg==null) return; n++; sum+=F.chg; if(F.chg>0) up++; contrib.push({t:h.t,c:h.w*F.chg,chg:F.chg}); });
  contrib.sort((a,b)=>Math.abs(b.c)-Math.abs(a.c));
  return n?{up,n,ew:sum/n,top:contrib.slice(0,4)}:null;
}
function myToday(){
  if(!me) return null;
  const pos=positionsAgg(); let V=0,D=0,XD=null,xLab=null; const moves=[];
  pos.forEach(p=>{ const F=facts(p.t); const last=lastValid(base.px[p.t]||[]); if(last==null) return; V+=last*p.shares; if(F?.chg!=null){ const prev=last/(1+F.chg); D+=(last-prev)*p.shares; }
    const x=extOf(p.t); if(x){ XD=(XD||0)+(x.p-last)*p.shares; xLab=x.lab; } });
  const syms=[...new Set([...me.watch,...pos.map(p=>p.t)])];
  syms.forEach(t=>{ const F=facts(t); if(F?.chg!=null) moves.push({t,chg:F.chg,last:F.last,x:extOf(t)}); });
  moves.sort((a,b)=>Math.abs(b.chg)-Math.abs(a.chg));
  return {V,D,dayPct:V-D?D/(V-D):null,moves,hasPos:pos.length>0,count:syms.length,XD,xLab};
}
function overnightInsight(v){
  const ov=xpeek("macro")?.data?.overnight; if(!ov?.q||v.status?.status==="open") return null;
  const f=k=>ov.q[k]?.chg, es=f("ES=F"), nq=f("NQ=F"); if(es==null) return null;
  const lead=(es+(nq??es))/2, dir=lead>0.0015?"a higher open":lead<-0.0015?"a lower open":"a flat open";
  const since=new Date(ov.since), today=nyToday(), sinceDay=since.toLocaleDateString("en-CA",{timeZone:"America/New_York"});
  const when=sinceDay===today?"Since the 4 pm close":`Since ${since.toLocaleDateString("en-US",{weekday:"long",timeZone:"America/New_York"})}'s close`;
  const ud=x=>`${x>=0?"up":"down"} ${pct(Math.abs(x)).replace(/^\+/,"")}`;
  const rest=[["YM=F","the Dow"],["RTY=F","small caps"]].filter(([k])=>f(k)!=null).map(([k,n])=>`${n} ${pct(f(k))}`);
  return {tone:cls(lead),html:`<b>Futures point to ${dir}.</b> ${when}, S&amp;P 500 futures are ${ud(es)}${nq!=null?` and Nasdaq-100 futures ${ud(nq)}`:""}${rest.length?`; ${rest.join(", ")}`:""}.${ov.trading?"":" Futures are paused right now, so these are the last trades."}`};
}
function extInsight(){
  const spy=base?.funds?.SPY?.holdings; if(!spy) return null;
  const xs=spy.map(h=>({t:h.t,x:extOf(h.t)})).filter(o=>o.x&&Math.abs(o.x.chg)>=0.02).sort((a,b)=>Math.abs(b.x.chg)-Math.abs(a.x.chg));
  if(!xs.length) return null;
  const lab=xs[0].x.lab, top=xs.slice(0,5);
  return {tone:"",html:`<b>${lab}, the biggest S&amp;P 500 movers:</b> ${top.map(o=>`<a href="#" data-sel="${o.t}">${o.t}</a> ${pct(o.x.chg,1)}`).join(", ")}${xs.length>top.length?`, and ${xs.length-top.length} more moving 2% or more`:""}. These trades are thinner than the regular session, so moves can shift by the open.`};
}
function statusNote(st){   // "Opens in 9 h 20 min", worked out from the opening time so it doesn't go stale
  const ny={timeZone:"America/New_York"}, at=t=>t?new Date(t):null, o=at(st.open), c=at(st.close);
  if(st.status==="open") return c&&!isNaN(c)?`Closes at ${c.toLocaleTimeString("en-US",{...ny,hour:"numeric",minute:"2-digit"}).toLowerCase()}`:"";
  if(!o||isNaN(o)) return "";
  const m=Math.round((o-Date.now())/60000); if(m<=0) return "";
  if(m<18*60) return `Opens in ${m>=60?Math.floor(m/60)+"h ":""}${m%60}m`;
  return `Opens ${o.toLocaleDateString("en-US",{...ny,weekday:"long"})} at ${o.toLocaleTimeString("en-US",{...ny,hour:"numeric",minute:"2-digit"}).toLowerCase()}`;
}
function marketInsights(v){
  const q=v.q, ins=[], open=v.status?.status==="open", verb=open?"is":"was";
  const ovl=overnightInsight(v); if(ovl) ins.push(ovl);
  const exl=extInsight(); if(exl) ins.push(exl);
  const sp=q["^GSPC"], nd=q["^IXIC"], rt=q["^RUT"];
  if(sp){ const r=sp.rets["1D"]; const dir=r>0.002?"higher":r<-0.002?"lower":"little changed";
    ins.push({tone:cls(r),html:`<b>Stocks ${open?"are":"closed"} ${dir}.</b> The S&amp;P 500 ${verb} ${pct(r)}${nd?`, the Nasdaq ${pct(nd.rets["1D"])}`:""}${rt?` and small caps ${pct(rt.rets["1D"])}`:""}.`}); }
  const b=spyBreadth();
  if(b&&sp){ const share=b.up/b.n, gap=b.ew-sp.rets["1D"];
    const tone=share>0.6?"up":share<0.4?"down":"";
    const what=share>0.65?"Broad strength":share<0.35?"Broad weakness":Math.abs(gap)>0.004?(gap<0?"Narrow move, carried by the giants":"The average stock is doing better than the index"):"Mixed under the surface";
    ins.push({tone,html:`<b>${what}.</b> ${b.up} of ${b.n} S&amp;P 500 stocks are up; the average stock ${verb} ${pct(b.ew)}. Biggest swing factors: ${b.top.map(x=>`<a href="#" data-sel="${x.t}">${x.t}</a> ${pct(x.chg,1)}`).join(", ")}.`}); }
  const secs=(v.sectors||[]).map(([s,n])=>({s,n,r:q[s]?.rets["1D"]})).filter(x=>x.r!=null).sort((a,b)=>b.r-a.r);
  if(secs.length>2) ins.push({tone:"",html:`<b>${secs[0].n} leads</b> (${pct(secs[0].r,1)}) and <b>${secs[secs.length-1].n.toLowerCase()} lags</b> (${pct(secs[secs.length-1].r,1)}). ${secs.filter(x=>x.r>0).length} of ${secs.length} sectors are up.`});
  const vix=q["^VIX"], tnx=q["^TNX"];
  if(vix&&tnx){ const vl=vix.last, vd=vix.prev?vl-vix.prev:null, y=rateVal(tnx.last), yp=rateVal(tnx.prev);
    const mood=vl<15?"calm":vl<20?"normal":vl<28?"nervous":"fearful";
    ins.push({tone:vl>=20?"down":"",html:`<b>Volatility is ${mood}:</b> the VIX ${verb} ${vl.toFixed(1)}${vd!=null?` (${vd>=0?"+":"−"}${Math.abs(vd).toFixed(1)})`:""}. The 10-year Treasury yield ${verb} ${y.toFixed(2)}%${yp!=null?`, ${Math.round((y-yp)*100)>=0?"up":"down"} ${Math.abs(Math.round((y-yp)*100))} bp`:""}.`}); }
  const oil=q["CL=F"], gold=q["GC=F"], btc=q["BTC-USD"];
  if(oil&&gold) ins.push({tone:"",html:`Oil ${pct(oil.rets["1D"],1)}, gold ${pct(gold.rets["1D"],1)}${btc?`, bitcoin ${pct(btc.rets["1D"],1)}`:""}. The dollar index ${q["DX-Y.NYB"]?pct(q["DX-Y.NYB"].rets["1D"],1):"–"}.`});
  const my=myToday();
  if(my?.hasPos) ins.push({tone:cls(my.D),html:`<b>Your portfolio ${verb} ${pct(my.dayPct)} today</b> (${my.D>=0?"+":"−"}${money(Math.abs(my.D))})${my.moves[0]?`, with <a href="#" data-sel="${my.moves[0].t}">${my.moves[0].t}</a> moving most (${pct(my.moves[0].chg,1)})`:""}.`});
  // what's next
  const ev=xpeek("econ")?.data||[], today=nyToday();
  const nextEv=ev.filter(e=>e.date>=today&&e.actual==null&&MAJOR_EV.test(e.event)).slice(0,3);
  const mine=new Set([...(me?.watch||[]),...(me?.positions||[]).map(p=>p.t)]);
  const nextE=Object.entries(EARN).filter(([t,e])=>mine.has(t)&&e.date>=today&&e.reported==null).sort((a,b)=>a[1].date.localeCompare(b[1].date)).slice(0,3);
  const nb=x=>String(x).trim().replace(/ /g,"\u00a0");   // keep "Thu Nov 6 8:30 AM" on one line
  if(nextEv.length||nextE.length) ins.push({tone:"",html:`<b>Coming up:</b> ${[...nextE.map(([t,e])=>({k:e.date+" 99",h:`<a href="#" data-sel="${t}">${t}</a> earnings ${nb(dayLabel(e.date).toLowerCase()==="today"?"today":dayLabel(e.date))}`})),...nextEv.map(e=>({k:e.date+" "+(e.time||""),h:`${esc(econName(e.event))} ${nb((dayLabel(e.date)==="Today"?"today":dayLabel(e.date))+" "+(e.time||""))}`}))].sort((a,b)=>a.k.localeCompare(b.k)).map(x=>x.h).join(" · ")}.`});
  return ins;
}
const MAJOR_EV=/CPI|PPI|payroll|unemployment rate|GDP|FOMC|fed funds|retail sales|PCE|ISM (manufacturing|n-mfg|services) PMI|jobless claims|consumer confidence|sentiment|JOLTS|ADP|durable goods|housing starts/i;
const TILE_GROUPS=[["Stocks",["^GSPC","^IXIC","^DJI","^RUT","ES=F","NQ=F"]],["Rates, volatility and the dollar",["^TNX","^FVX","^IRX","^VIX","DX-Y.NYB"]],["Commodities and crypto",["CL=F","GC=F","BTC-USD"]]];
function tileValue(sym,v){
  const kind=v?.names?.[sym]?.[1], x=v.q[sym];
  if(kind==="rate"){ const y=rateVal(x.last), p=rateVal(x.prev); const bp=p!=null?Math.round((y-p)*100):null; return {val:y.toFixed(2)+"%",chg:bp==null?"":`${bp>=0?"+":"−"}${Math.abs(bp)} bp`,c:bp}; }
  if(kind==="vol") return {val:x.last.toFixed(2),chg:x.prev?`${x.last-x.prev>=0?"+":"−"}${Math.abs(x.last-x.prev).toFixed(2)}`:"",c:x.prev?-(x.last-x.prev):null};
  const dp=x.last>=1000?0:2, val=x.last.toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp});
  if(x.overnight!=null) return {val,chg:`${pct(x.overnight)} <small>since close</small>`,c:x.overnight};
  return {val,chg:pct(x.rets["1D"]),c:x.rets["1D"]};
}
function renderMarket(){
  const app=$("#app");
  if(!$("#mkt")){
    app.innerHTML=`<div id="mkt" class="page">
      <section class="hero mhero"><div><div class="eyebrow" id="mEyebrow">Market today</div><h1 class="ptitle" id="mTitle">Reading the tape…</h1><div id="mIns">${sk(150)}</div></div>
        <div class="mside"><div class="lbl">Your stocks today</div><div id="mMine">${sk(160)}</div></div></section>
      <section id="mTiles"></section>
      <section class="panel"><div class="ph"><div><h2>Sectors</h2><div class="hint">The 11 S&amp;P sector funds. Pick one to see its industries and biggest companies.</div></div><div class="seg sm" id="mRng"></div></div><div id="mSectors">${sk(260)}</div><div id="mSector"></div></section>
      <section class="row even"><div class="panel"><div class="ph"><div><h2>Movers</h2><div class="hint">US stocks with the biggest moves and the most trading today.</div></div><div class="seg sm" id="mMovSeg"></div></div><div id="mMovers">${sk(300)}</div></div>
        <div class="panel"><div class="ph"><div><h2>Economic calendar</h2><div class="hint">US data releases. Times are New York.</div></div><a class="lnk" href="#calendar" data-page="calendar" data-cal="econ">Full calendar ›</a></div><div id="mEcon">${sk(300)}</div></div></section></div>`;
    loadMarket();
  }
  const v=macroView(), err=xpeek("macro")?.error;
  if(err&&!v){ $("#mIns").innerHTML=errBox(err,"macro"); return; }
  if(!v) return;
  const st=v.status||{}, sp=v.q["^GSPC"];
  $("#mEyebrow").innerHTML=`<span>Market today</span><span>·</span><span class="chip ${st.status==="open"?"up":""}">${st.status==="open"?"● Open":"Closed"}</span>${statusNote(st)?`<span class="hint" style="margin:0">${esc(statusNote(st))}</span>`:""}`;
  if(sp){ const r=sp.rets["1D"]; $("#mTitle").innerHTML=`S&amp;P 500 <span class="${cls(r)}">${pct(r)}</span>`; }
  $("#mIns").innerHTML=insightList(marketInsights(v));
  // your stocks
  const my=myToday();
  $("#mMine").innerHTML=!my||!my.count?`<p class="hint">Add stocks to your watchlist or portfolio to see them here.</p><button class="btn ghost" data-page="mine">Go to My stocks</button>`:
    `${my.hasPos?`<div class="mval"><b>${money(my.V)}</b><span class="${cls(my.D)}">${my.D>=0?"+":"−"}${money(Math.abs(my.D))} · ${pct(my.dayPct)}</span></div>`:""}
     ${my.hasPos&&my.XD!=null?`<div class="mxh">${ic(my.xLab==="Pre-market"?"sun":"moon",12)}${my.xLab} <span class="num ${cls(my.XD)}">${my.XD>=0?"+":"−"}${money(Math.abs(my.XD))} · ${pct(my.V?my.XD/my.V:null)}</span></div>`:""}
     <ul class="mlist">${my.moves.slice(0,5).map(x=>`<li data-sel="${x.t}"><b class="mono">${x.t}</b><span class="num">${money(x.last)}</span><span class="num ${cls(x.chg)}">${pct(x.chg,1)}${x.x?`<span class="xh" title="${x.x.lab} ${money(x.x.p)} at ${extTime(x.x.ts)}">${ic(x.x.s==="pre"?"sun":"moon",10)} <span class="${cls(x.x.chg)}">${pct(x.x.chg,1)}</span></span>`:""}</span></li>`).join("")}</ul>
     ${(()=>{ const b=briefItems().filter(x=>x.kind!=="move"); return b.length?`<div class="lbl" style="margin-top:16px">From your brief</div>${briefRows(b.slice(0,3))}<a class="lnk" href="#mine" data-page="mine" style="margin-top:6px">Open your brief ›</a>`:""; })()}`;
  // tiles
  $("#mTiles").innerHTML=TILE_GROUPS.map(([g,syms])=>`<div class="tgrp" style="--n:${syms.filter(s=>v.q[s]).length}"><div class="lbl">${g}</div><div class="tiles">${syms.filter(s=>v.q[s]).map(s=>{ const t=tileValue(s,v), col=t.c==null?"var(--ink-3)":t.c>=0?"var(--up)":"var(--down)";
      return `<div class="mtile"><div class="tn">${esc(v.names[s]?.[0]||s)}</div><div class="tv num">${t.val}</div><div class="tc num ${t.c==null?"":t.c>=0?"up":"down"}">${t.chg}</div><div class="tsp">${miniSpark(v.q[s].spark,140,30,col)}</div></div>`; }).join("")}</div></div>`).join("");
  // sectors
  $("#mRng").innerHTML=MKT_RANGES.map(k=>`<button data-mr="${k}" aria-pressed="${k===mktRange}">${k}</button>`).join("");
  const secs=(v.sectors||[]).map(([s,n,key])=>({s,n,key,r:v.q[s]?.rets[mktRange],r1:v.q[s]?.rets["1D"]})).filter(x=>x.r!=null).sort((a,b)=>b.r-a.r);
  const spR=sp?.rets[mktRange], mx=Math.max(...secs.map(x=>Math.abs(x.r)),Math.abs(spR||0))||0.01;
  const spX=spR!=null?(50+spR/mx*50):null;
  $("#mSectors").innerHTML=`<div class="sbars">${spX!=null?`<div class="sbhead" aria-hidden="true"><span></span><span class="strk"><b style="left:${spX.toFixed(1)}%;transform:translateX(${spX<12?"-10%":spX>88?"-90%":"-50%"})">S&amp;P 500 ${pct(spR,1)}</b></span><span></span></div>`:""}${secs.map(x=>`<button class="sbar ${sectorOpen===x.key?"on":""}" data-sector="${x.key}" data-sname="${esc(x.n)}"><span class="sn">${esc(x.n)}<small class="mono">${x.s}</small></span><span class="strk"><span class="szero"></span><i style="${x.r>=0?"left:50%":"right:50%"};width:${(Math.abs(x.r)/mx*50).toFixed(1)}%;background:${x.r>=0?"var(--up)":"var(--down)"}"></i>${spX!=null?`<em style="left:${spX.toFixed(1)}%" title="S&amp;P 500 ${pct(spR)}"></em>`:""}</span><span class="num ${cls(x.r)}">${pct(x.r,1)}</span></button>`).join("")}</div>
    ${spR!=null?`<p class="hint" style="margin:8px 0 0">The blue line is the S&amp;P 500 ${mktRange==="1D"?"today":"over "+mktRange}. Sectors that end to its right did better than the market, to its left worse.</p>`:""}`;
  renderSectorDetail();
  // movers
  const ms=load("movers","day_gainers");
  $("#mMovSeg").innerHTML=[["day_gainers","Gainers"],["day_losers","Losers"],["most_actives","Active"]].map(([k,l])=>`<button data-mov="${k}" aria-pressed="${k===ms}">${l}</button>`).join("");
  const mv=xpeek("screen",{name:ms});
  $("#mMovers").innerHTML=!mv||mv.loading&&!mv.data?sk(300):mv.error?errBox(mv.error,"screen",{name:ms}):quoteTable(mv.data.slice(0,12),["t","price","chg","rvol","cap"]);
  // econ
  const ec=xpeek("econ");
  $("#mEcon").innerHTML=!ec||ec.loading&&!ec.data?sk(300):ec.error?errBox(ec.error,"econ"):econList(ec.data.filter(e=>e.date>=shiftDays(nyToday(),-1)).slice(0,14),true);
}
async function renderSectorDetail(){
  const el=$("#mSector"); if(!el) return;
  if(!sectorOpen){ el.innerHTML=""; return; }
  const c=xpeek("sector",{key:sectorOpen});
  if(!c||c.loading&&!c.data){ el.innerHTML=`<div class="sdet">${sk(200)}</div>`; xget("sector",{key:sectorOpen}).then(()=>page==="market"&&renderSectorDetail()); return; }
  if(c.error){ el.innerHTML=`<div class="sdet">${errBox(c.error,"sector",{key:sectorOpen})}</div>`; return; }
  const d=c.data, o=d.overview||{}, inds=d.industries||[], mxw=Math.max(...inds.map(i=>i.weight||0))||1;
  const ic=industryOpen?xpeek("industry",{key:industryOpen}):null;
  el.innerHTML=`<div class="sdet"><div class="sdh"><div><h3>${esc($(`[data-sector="${sectorOpen}"]`)?.dataset.sname||sectorOpen)}</h3><p class="hint" style="margin:4px 0 0;max-width:80ch">${esc(o.description||"")}</p></div><button class="x" data-sector-close aria-label="Close sector">${ic("close",16)}</button></div>
    <div class="kf"><div><div class="lbl">Market value</div><div class="v">${big(o.market_cap)}</div></div><div><div class="lbl">Share of US market</div><div class="v">${o.market_weight!=null?pc(o.market_weight):"–"}</div></div><div><div class="lbl">Companies</div><div class="v">${o.companies_count?.toLocaleString("en-US")||"–"}</div><div class="ks">${o.industries_count||"?"} industries</div></div></div>
    <div class="row even" style="margin-top:14px;gap:22px"><div><h4 class="h4">Industries by size</h4><div class="ibars">${inds.map(i=>`<button class="ibar ${industryOpen===i.key?"on":""}" data-industry="${esc(i.key)}"><span>${esc(i.name)}</span><i style="width:${((i.weight||0)/mxw*100).toFixed(1)}%"></i><b class="num">${i.weight!=null?pc(i.weight):""}</b></button>`).join("")}</div><p class="hint">Pick an industry for its best performers.</p></div>
      <div><h4 class="h4">${industryOpen&&ic?.data?esc(inds.find(i=>i.key===industryOpen)?.name||"")+": best this year":"Largest companies · share of the sector"}</h4>${industryOpen?industryHTML(ic):`<ul class="clist">${(d.companies||[]).slice(0,14).map(x=>`<li data-sel="${esc(x.t)}"><b class="mono">${esc(x.t)}</b><span>${esc(x.n)}</span><span class="ks">${esc(x.rating||"")}</span><span class="num">${x.weight!=null?pc(x.weight):""}</span></li>`).join("")}</ul>`}</div></div></div>`;
  if(industryOpen&&(!ic||ic.loading&&!ic.data)) xget("industry",{key:industryOpen}).then(()=>page==="market"&&renderSectorDetail());
}
function industryHTML(ic){
  if(!ic||ic.loading&&!ic.data) return sk(220);
  if(ic.error) return errBox(ic.error,"industry",{key:industryOpen});
  const p=ic.data.performers||[], g=ic.data.growth||[];
  return `<ul class="clist">${p.map(x=>`<li data-sel="${esc(x.t)}"><b class="mono">${esc(x.t)}</b><span>${esc(x.name||"")}</span><span class="num ${cls(x["ytd return"])}">${x["ytd return"]!=null?pct(x["ytd return"],0)+" YTD":""}</span><span class="num ks">${x["target price"]&&x["last price"]?`target ${pct(x["target price"]/x["last price"]-1,0)}`:""}</span></li>`).join("")}</ul>
   ${g.length?`<h4 class="h4" style="margin-top:12px">Fastest expected growth</h4><ul class="clist">${g.slice(0,6).map(x=>`<li data-sel="${esc(x.t)}"><b class="mono">${esc(x.t)}</b><span>${esc(x.name||"")}</span><span class="num up">${x["growth estimate"]!=null?pct(x["growth estimate"],0):""}</span><span></span></li>`).join("")}</ul>`:""}`;
}
function quoteTable(rows,cols,opts={}){
  if(!rows?.length) return `<p class="hint">Nothing matched.</p>`;
  const H={t:"Stock",price:"Price",chg:"Today",rvol:"Volume vs avg",cap:"Mkt cap",pe:"P/E (fwd)",yr:"1 year",rating:"Analysts",yield:"Yield",add:""};
  const C={t:q=>`<td class="l"><b class="mono">${esc(q.t)}</b><span class="qn" title="${esc(q.longName||q.shortName||"")}">${esc(niceName((q.shortName||"").length<28?q.shortName||q.longName||"":q.longName||q.shortName))}</span></td>`,
    price:q=>`<td class="num">${money(q.regularMarketPrice)}</td>`,
    chg:q=>`<td class="num ${cls(q.regularMarketChangePercent)}">${q.regularMarketChangePercent==null?"–":pct(q.regularMarketChangePercent/100,1)}</td>`,
    rvol:q=>`<td class="num">${q.regularMarketVolume&&q.averageDailyVolume3Month?(q.regularMarketVolume/q.averageDailyVolume3Month).toFixed(1)+"×":"–"}</td>`,
    cap:q=>`<td class="num">${big(q.marketCap)}</td>`,
    pe:q=>`<td class="num">${mult(q.forwardPE)}</td>`,
    yr:q=>`<td class="num ${cls(q.fiftyTwoWeekChangePercent)}">${q.fiftyTwoWeekChangePercent==null?"–":pct(q.fiftyTwoWeekChangePercent/100,0)}</td>`,
    rating:q=>`<td class="l ks">${esc((q.averageAnalystRating||"").replace(/^[\d.]+ - /,""))}</td>`,
    yield:q=>`<td class="num">${q.dividendYield>0?q.dividendYield.toFixed(2)+"%":"–"}</td>`,
    add:q=>{ const on=me?.watch?.includes(q.t); return `<td><button class="star ${on?"on":""}" data-star="${esc(q.t)}" aria-label="${on?"Remove from":"Add to"} watchlist" title="${on?"On your watchlist":"Add to watchlist"}">${ic("star",16,on)}</button></td>`; }};
  return `<div class="tbl-wrap"><table class="hold qt"><thead><tr>${cols.map(c=>`<th class="${c==="t"||c==="rating"?"l":""}" data-c="${c}">${H[c]}</th>`).join("")}</tr></thead><tbody>${rows.map(q=>`<tr data-sel="${esc(q.t)}">${cols.map(c=>C[c](q).replace(/^<td/,`<td data-c="${c}"`)).join("")}</tr>`).join("")}</tbody></table></div>`;
}
/* Yahoo's economic calendar uses wire-service shorthand; say it in words */
const ECON_NAMES={"ADP National Employment":"ADP private jobs","Non-Farm Payrolls":"Jobs added (payrolls)","Unemployment Rate":"Unemployment rate",
  "Initial Jobless Clm":"New jobless claims","Cont Jobless Clm":"Continuing jobless claims","Jobless Clm 4Wk Avg":"Jobless claims, 4-week average",
  "CPI MM, SA":"Inflation (CPI), monthly","CPI YY, NSA":"Inflation (CPI), yearly","Core CPI MM, SA":"Core inflation, monthly","Core CPI YY, NSA":"Core inflation, yearly",
  "CPI Index, NSA":"CPI index level","Core CPI Index, SA":"Core CPI index level","PPI Final Demand MM":"Producer prices, monthly","PPI Final Demand YY":"Producer prices, yearly",
  "PPI exFood/Energy MM":"Core producer prices, monthly","PPI exFood/Energy YY":"Core producer prices, yearly","PPI ex Food/Energy/Tr MM":"Producer prices excl. food, energy, trade, monthly","PPI ex Food/Energy/Tr YY":"Producer prices excl. food, energy, trade, yearly",
  "ISM Manufacturing PMI":"Factory activity (ISM)","ISM N-Mfg PMI":"Services activity (ISM)","ISM N-Mfg Bus Act":"Services business activity (ISM)","ISM Mfg Prices Paid":"Factory prices paid (ISM)",
  "ISM N-Mfg Price Paid Idx":"Services prices paid (ISM)","ISM Manuf New Orders Idx":"Factory new orders (ISM)","ISM N-Mfg New Orders Idx":"Services new orders (ISM)",
  "ISM Manuf Employment Idx":"Factory hiring (ISM)","ISM N-Mfg Employment Idx":"Services hiring (ISM)","Redbook YY":"Store sales (Redbook), yearly",
  "Durable Goods, R MM":"Durable goods orders, monthly","Durables Ex-Def, R MM":"Durable goods excl. defense, monthly","Durables Ex-Transpt R MM":"Durable goods excl. transport, monthly",
  "Nondef Cap Ex-Air R MM":"Business equipment orders, monthly","Retail Sales MM":"Retail sales, monthly","Retail Sales Ex-Autos MM":"Retail sales excl. autos, monthly",
  "Retail Ex Gas/Autos":"Retail sales excl. gas and autos","Retail Control":"Retail sales, control group","U Mich Sentiment Prelim":"Consumer sentiment (U. Michigan)",
  "U Mich 1Yr Inf Prelim":"Expected inflation, 1 year (U. Michigan)","U Mich 5-Yr Inf Prelim":"Expected inflation, 5 years (U. Michigan)",
  "U Mich Conditions Prelim":"Consumer view of conditions (U. Michigan)","U Mich Expectations Prelim":"Consumer expectations (U. Michigan)",
  "Exist. Home Sales % Chg":"Existing home sales, change","NAHB Housing Market Indx":"Homebuilder confidence","NFIB Business Optimism Idx":"Small-business optimism",
  "MBA 30-Yr Mortgage Rate":"30-year mortgage rate","International Trade $":"Trade balance","Federal Budget,$":"Federal budget",
  "Average Earnings MM":"Hourly earnings, monthly","Average Workweek Hrs":"Average workweek, hours","Wholesale Invt(y), R MM":"Wholesale inventories, monthly",
  "EIA Wkly Crude Stk":"Crude oil stockpiles","EIA Wkly Gsln Stk":"Gasoline stockpiles","EIA-Nat Gas Chg Bcf":"Natural gas storage change","Factory Orders MM":"Factory orders, monthly","Factory Ex-Transp MM":"Factory orders excl. transport, monthly",
  "Manuf Output MM":"Factory output, monthly","Industrial Production MM":"Industrial production, monthly","Capacity Utilization SA":"Factory capacity in use"};
function econName(n){ n=String(n||"").trim(); if(ECON_NAMES[n]) return ECON_NAMES[n];
  const per=/\bMM\b/.test(n)?", monthly":/\bYY\b/.test(n)?", yearly":/\bQQ\b/.test(n)?", quarterly":"";
  n=n.replace(/\b(MM|YY|QQ)\b/,"").replace(/,?\s*\bR\b\s*$/,"").replace(/\bEx-?\s?/g,"excl. ").replace(/\bMfg\b|\bManuf\b/g,"manufacturing").replace(/\bIdx\b|\bIndx\b/g,"index").replace(/[\s,]+$/,"").replace(/\s+/g," ").trim();
  return n.split(" ").map((w,i)=>i&&/^[A-Z][a-z]/.test(w)?w.toLowerCase():w).join(" ")+per; }
function econList(rows,compact){
  if(!rows.length) return `<p class="hint">No US releases in this window.</p>`;
  const today=nyToday(), by=new Map(); rows.forEach(e=>{ if(!by.has(e.date)) by.set(e.date,[]); by.get(e.date).push(e); });
  const fmt=v=>v==null?"–":(v<0?"−":"")+(Math.abs(v)>=1000?Math.abs(v).toLocaleString("en-US"):String(+Math.abs(+v).toFixed(2)));
  return [...by].map(([d,list])=>`<div class="eg"><div class="egh ${d===today?"today":""}">${dayLabel(d,today)}</div><table class="hz econ"><tbody>${list.map(e=>{ const surprise=e.actual!=null&&e.expected!=null?e.actual-e.expected:null;
    return `<tr class="${e.actual==null?"pending":""}"><td class="l mono ks" style="width:48px">${esc(e.time)}</td><td class="l" title="${esc(e.event)}">${esc(econName(e.event))}${e.for?` <span class="ks">${esc(String(e.for))}</span>`:""}</td><td class="num"><b>${fmt(e.actual)}</b></td>${compact?"":`<td class="num ks">${fmt(e.expected)}</td>`}<td class="num ks">${fmt(e.last)}</td>${surprise!=null&&!compact?`<td class="num sg ${surprise>0?"up":surprise<0?"down":""}">${surprise>0?"▲":surprise<0?"▼":"="}</td>`:compact?"":`<td class="num sg"></td>`}</tr>`; }).join("")}</tbody></table></div>`).join("")
   +`<p class="hint">${compact?"Bold is the actual figure, grey the previous one.":"Actual, then the forecast and the previous figure. ▲ ▼ show whether the actual came in above or below the forecast."}</p>`;
}

/* ======================= CALENDAR ======================= */
let calTab=load("calTab","earn"), calScope=load("calScope","mine");
const CAL_TABS=[["earn","Earnings"],["econ","Economy"],["ipo","IPOs"],["splits","Splits"]];
function renderCalendar(){
  if(!$("#cal")){
    $("#app").innerHTML=`<div id="cal" class="page"><div class="phead"><div><h1 class="ptitle">Calendar</h1><p class="hint" id="calSub"></p></div><div class="seg" id="calTabs"></div></div><div id="calBody"></div></div>`;
  }
  $("#calTabs").innerHTML=CAL_TABS.map(([k,l])=>`<button data-ct="${k}" aria-pressed="${k===calTab}">${l}</button>`).join("");
  const body=$("#calBody");
  if(calTab==="earn"){
    loadEarnings();
    const scopes=[["mine","My stocks"],...FUND_LIST.map(f=>[f,{SPY:"S&P 500",QQQ:"Nasdaq-100"}[f]||f])];
    let W;
    if(calScope==="mine"){ W=new Map(); const pos=positionsAgg(), tot=pos.reduce((a,p)=>a+p.shares*(lastValid(base.px[p.t]||[])||0),0);
      (me?.watch||[]).forEach(t=>W.set(t,null)); pos.forEach(p=>W.set(p.t,tot?p.shares*(lastValid(base.px[p.t]||[])||0)/tot*100:null)); }
    else W=new Map((base.funds[calScope]?.holdings||[]).map(h=>[h.t,h.w]));
    $("#calSub").textContent="Who reports, when, and how it went. Weights show how much each company matters to the group.";
    body.innerHTML=`<div class="seg sm" style="margin-bottom:14px">${scopes.map(([k,l])=>`<button data-cs="${k}" aria-pressed="${k===calScope}">${l}</button>`).join("")}</div>
      <section class="panel">${calScope==="mine"&&!W.size?`<p class="hint">Your watchlist and portfolio are empty, so there's nothing to show yet. Pick a fund above, or add stocks from any stock page.</p>`:earnGrid(W,calScope==="mine"?"your stocks":calScope,calScope==="mine")}</section>`;
    return;
  }
  const name=calTab, c=xpeek(name);
  if(!c||c.loading&&!c.data){ body.innerHTML=`<section class="panel">${sk(400)}</section>`; xget(name).then(()=>page==="calendar"&&calTab===name&&renderCalendar()); return; }
  if(c.error){ body.innerHTML=`<section class="panel">${errBox(c.error,name)}</section>`; return; }
  if(name==="econ"){ $("#calSub").textContent="US economic releases from a few days ago to two weeks out."; body.innerHTML=`<section class="panel">${econList(c.data,false)}</section>`; return; }
  if(name==="ipo"){ $("#calSub").textContent="Companies going public, from last week to a month out.";
    body.innerHTML=`<section class="panel">${c.data.length?`<div class="tbl-wrap"><table class="hold"><thead><tr><th class="l">Date</th><th class="l">Company</th><th class="l">Exchange</th><th>Price range</th><th>Priced</th><th>Shares</th><th class="l">Status</th></tr></thead><tbody>${c.data.map(r=>`<tr><td class="l">${r.date?dayLabel(r.date):"TBA"}</td><td class="l"><b class="mono">${esc(r.t)}</b> <span class="qn">${esc(r.company||"")}</span></td><td class="l ks">${esc(r.exchange||"")}</td><td class="num">${r.priceFrom?`$${r.priceFrom}–${r.priceTo}`:"–"}</td><td class="num">${r.price?money(r.price):"–"}</td><td class="num">${r.shares?(r.shares/1e6).toFixed(1)+"M":"–"}</td><td class="l ks">${esc(r.action||"")}</td></tr>`).join("")}</tbody></table></div>`:`<p class="hint">No IPOs scheduled in this window.</p>`}</section>`; return; }
  if(name==="splits"){ $("#calSub").textContent="Upcoming stock splits and reverse splits for US-listed companies.";
    body.innerHTML=`<section class="panel">${c.data.length?`<div class="tbl-wrap"><table class="hold"><thead><tr><th class="l">Date</th><th class="l">Company</th><th>Split</th><th class="l">Kind</th></tr></thead><tbody>${c.data.map(r=>`<tr data-sel="${esc(r.t)}"><td class="l">${r.date?dayLabel(r.date):"–"}</td><td class="l"><b class="mono">${esc(r.t)}</b> <span class="qn">${esc(r.company||"")}</span></td><td class="num">${r.new}-for-${r.old}</td><td class="l ks">${r.new>r.old?"Split":"Reverse split"}</td></tr>`).join("")}</tbody></table></div>`:`<p class="hint">No splits scheduled in this window.</p>`}</section>`; }
}
/* earnings grid: W maps ticker -> weight (or null when weights don't apply) */
function earnGrid(W,label,isMine){
  const today=nyToday();
  if(!Object.keys(EARN).length) return `<p class="hint" style="margin:0">${earnAt?"The earnings calendar isn't ready yet. The server fetches it a minute after starting, then every few hours.":"Loading the earnings calendar…"}</p>`;
  const items=[...W.keys()].filter(t=>EARN[t]).map(t=>({t,w:W.get(t),...EARN[t]})).filter(e=>e.date>=shiftDays(today,-7)&&e.date<=shiftDays(today,14));
  if(!items.length) return `<p class="hint" style="margin:0">None of ${esc(label)} report between last week and two weeks out.</p>`;
  const byDay=new Map(); items.sort((a,b)=>a.date.localeCompare(b.date)||(b.w??0)-(a.w??0)||a.t.localeCompare(b.t)).forEach(e=>{ if(!byDay.has(e.date)) byDay.set(e.date,[]); byDay.get(e.date).push(e); });
  const up=items.filter(e=>e.date>=today&&e.reported==null), upW=up.reduce((a,e)=>a+(e.w||0),0);
  const done=items.filter(e=>e.reported!=null&&e.surprise!=null), beats=done.filter(e=>e.surprise>0).length;
  const wtxt=(w)=>`<span class="ew">${w==null?"":w.toFixed(w<1?2:1)+"%"}</span>`;
  return `<p class="hint" style="margin:0 0 12px">${up.length} ${isMine?(up.length===1?"of your stocks reports":"of your stocks report"):(up.length===1?"holding reports":"holdings report")} in the next two weeks${upW?`, ${upW.toFixed(1)}% of ${esc(label)} by weight`:""}.${done.length?` So far ${beats} of ${done.length} beat estimates.`:""} ☀ before the open, ☾ after the close. Past reports show the earnings surprise, then the stock's move the next session.</p>
   <div class="ecal">${[...byDay].map(([d,list])=>{ const past=d<today||list.every(e=>e.reported!=null), tw=list.reduce((a,e)=>a+(e.w||0),0);
     return `<div class="eday ${d===today?"today":""} ${past?"past":""}"><div class="edh">${dayLabel(d,today)}${tw?`<span>${tw.toFixed(1)}%</span>`:""}</div>
     ${list.slice(0,10).map(e=>{ const rx=e.reported!=null?reaction(e.t,e.date,e.timing==="BMO"?9:16):null;
       return `<button class="eit" data-sel="${esc(e.t)}"><b class="mono">${esc(e.t)}</b><span class="et">${e.timing==="BMO"?"☀":e.timing==="AMC"?"☾":""}</span>${wtxt(e.w)}${e.reported!=null?`<span class="${cls(e.surprise)}">${e.surprise!=null?pct(e.surprise/100,0):""}</span><span class="num ${rx!=null?cls(rx):""}">${rx!=null?pct(rx,1):""}</span>`:`<span class="ks">${e.epsEst!=null?"est "+(e.epsEst<0?"−":"")+"$"+Math.abs(e.epsEst).toFixed(2):""}</span>`}</button>`; }).join("")}
     ${list.length>10?`<div class="ks" style="padding:4px 8px">+${list.length-10} more</div>`:""}</div>`; }).join("")}</div>`;
}

/* ======================= SCREENER ======================= */
let scrSel=load("scr","undervalued_growth_stocks"), scrSort={k:null,dir:-1};
let scrForm={capMin:"10",capMax:"",peMax:"",growthMin:"",yieldMin:"",yearMin:"",yearMax:"",sector:"",sort:"marketcap"};
try{ Object.assign(scrForm,JSON.parse(load("scrForm","{}"))); }catch(e){}
const SCR_DESC={day_gainers:"Up the most today, $2B+ companies",day_losers:"Down the most today",most_actives:"Most shares traded today",
  undervalued_growth_stocks:"Earnings growing 25%+ with a P/E under 20 on the past year's earnings",undervalued_large_caps:"Large companies with low P/E and PEG",
  growth_technology_stocks:"Tech with 25%+ revenue and earnings growth",aggressive_small_caps:"Small caps with fast earnings growth",
  small_cap_gainers:"Small caps up the most today",most_shorted_stocks:"Highest short interest",portfolio_anchors:"Low-cost, steady funds",
  solid_large_growth_funds:"Highly rated large-growth mutual funds",solid_midcap_growth_funds:"Highly rated mid-growth mutual funds",
  top_mutual_funds:"Best-performing mutual funds",conservative_foreign_funds:"Low-risk international funds",high_yield_bond:"High-yield bond funds",
  top_etfs_us:"Large, popular U.S. exchange-traded funds",top_performing_etfs:"ETFs with the best recent returns",technology_etfs:"Funds that hold tech stocks",bond_etfs:"Funds that hold bonds"};
const SECTORS=["Technology","Healthcare","Financial Services","Consumer Cyclical","Communication Services","Industrials","Consumer Defensive","Energy","Basic Materials","Real Estate","Utilities"];
function renderScreener(){
  if(!$("#scr")){
    $("#app").innerHTML=`<div id="scr" class="page"><div class="phead"><div><h1 class="ptitle">Screener</h1><p class="hint">Start from one of Yahoo's ready-made ideas, or build your own. Star anything worth following.</p></div></div>
      <div class="scr"><aside class="scr-list" id="scrList"></aside><section class="panel scr-main" id="scrMain"></section></div></div>`;
    xget("screens").then(()=>page==="screener"&&renderScreener());
  }
  const L=xpeek("screens")?.data||[];
  const isF=k=>/fund|bond|anchor|etf/.test(k), stocks=L.filter(s=>!isF(s.key)), funds=L.filter(s=>isF(s.key));
  const item=s=>`<button class="scr-it ${s.key===scrSel?"on":""}" data-scr="${s.key}"><b>${esc(s.name)}</b><span>${esc(SCR_DESC[s.key]||"")}</span></button>`;
  $("#scrList").innerHTML=`<button class="scr-it build ${scrSel==="custom"?"on":""}" data-scr="custom"><b>Build your own</b><span>Size, valuation, growth, yield, momentum, sector</span></button>
    <div class="lbl" style="margin:14px 4px 6px">Stock ideas</div>${stocks.map(item).join("")||sk(200)}${funds.length?`<div class="lbl" style="margin:14px 4px 6px">Fund ideas</div>${funds.map(item).join("")}`:""}`;
  const main=$("#scrMain");
  let c, head, rq=["screen",{name:scrSel}];
  if(scrSel==="custom"){
    const f=scrForm, inp=(k,ph,w=90)=>`<label><span>${ph}</span><input data-sf="${k}" value="${esc(f[k])}" type="number" step="any" style="width:${w}px"></label>`;
    head=`<form class="sform" id="sform">${inp("capMin","Market cap from ($B)")}${inp("capMax","to ($B)")}${inp("peMax","P/E at most")}${inp("growthMin","Revenue growth at least (%)")}${inp("yieldMin","Dividend yield at least (%)")}${inp("yearMin","1-year change from (%)")}${inp("yearMax","to (%)")}
      <label><span>Sector</span><select data-sf="sector"><option value="">Any</option>${SECTORS.map(s=>`<option value="${s}" ${f.sector===s?"selected":""}>${SECTOR_NAME[s]||s}</option>`).join("")}</select></label>
      <label><span>Sort by</span><select data-sf="sort">${[["marketcap","Size"],["change","Today's move"],["growth","Revenue growth"],["pe","P/E"],["yield","Dividend yield"],["year","1-year change"]].map(([k,l])=>`<option value="${k}" ${f.sort===k?"selected":""}>${l}</option>`).join("")}</select></label>
      <button class="btn">Find stocks</button></form>`;
    const params=Object.fromEntries(Object.entries(f).filter(([k,v])=>v!==""&&v!=null));
    rq=["custom",params]; c=xpeek("custom",params); if(!c) xget("custom",params).then(()=>page==="screener"&&renderScreener());
  } else {
    const s=L.find(x=>x.key===scrSel)||{name:scrSel};
    head=`<div class="ph" style="margin:0"><div><h2>${esc(s.name||"")}</h2><div class="hint">${esc(SCR_DESC[scrSel]||"")}</div></div></div>`;
    c=xpeek("screen",{name:scrSel}); if(!c) xget("screen",{name:scrSel}).then(()=>page==="screener"&&renderScreener());
  }
  let body;
  if(!c||c.loading&&!c.data) body=sk(420);
  else if(c.error) body=errBox(c.error,...rq);
  else{
    let rows=[...c.data];
    if(scrSort.k){ const g={price:q=>q.regularMarketPrice,chg:q=>q.regularMarketChangePercent,cap:q=>q.marketCap,pe:q=>q.forwardPE,yr:q=>q.fiftyTwoWeekChangePercent,yield:q=>q.dividendYield}[scrSort.k];
      if(g) rows.sort((a,b)=>{const x=g(a),y=g(b); if(x==null) return 1; if(y==null) return -1; return (x-y)*scrSort.dir;}); }
    body=`<p class="hint" style="margin:10px 0">${rows.length} results. Sort by any column heading; open a stock from its row.</p>`+quoteTable(rows,["t","price","chg","cap","pe","yr","yield","rating","add"]);
  }
  main.innerHTML=head+`<div id="scrRes">${body}</div>`;
  const form=$("#sform");
  if(form){ form.onsubmit=e=>{ e.preventDefault(); form.querySelectorAll("[data-sf]").forEach(i=>scrForm[i.dataset.sf]=i.value.trim()); save("scrForm",JSON.stringify(scrForm)); renderScreener(); }; }
  main.querySelectorAll(".qt th").forEach((th,i)=>{ const key=["t","price","chg","cap","pe","yr","yield","rating","add"][i]; if(["price","chg","cap","pe","yr","yield"].includes(key)){ th.classList.add("sortable"); th.onclick=()=>{ scrSort={k:key,dir:scrSort.k===key?-scrSort.dir:-1}; renderScreener(); }; if(scrSort.k===key) th.textContent+=scrSort.dir>0?" ↑":" ↓"; } });
}

/* ======================= events for pages ======================= */
document.addEventListener("click",e=>{
  const t=e.target.closest("[data-page],[data-mr],[data-mov],[data-sector],[data-sector-close],[data-industry],[data-ct],[data-cs],[data-scr],[data-star],[data-retry-x]"); if(!t) return;
  if(t.dataset.page){ e.preventDefault(); if(t.dataset.cal) { calTab=t.dataset.cal; save("calTab",calTab); } goPage(t.dataset.page); return; }
  if(t.dataset.mr){ mktRange=t.dataset.mr; save("mktRange",mktRange); renderMarket(); return; }
  if(t.dataset.mov){ save("movers",t.dataset.mov); xget("screen",{name:t.dataset.mov}).then(()=>renderMarket()); renderMarket(); return; }
  if(t.dataset.sectorClose!==undefined){ sectorOpen=null; industryOpen=null; renderMarket(); return; }
  if(t.dataset.sector){ sectorOpen=sectorOpen===t.dataset.sector?null:t.dataset.sector; industryOpen=null; renderMarket(); if(sectorOpen) setTimeout(()=>$("#mSector")?.scrollIntoView({behavior:"smooth",block:"nearest"}),60); return; }
  if(t.dataset.industry){ industryOpen=industryOpen===t.dataset.industry?null:t.dataset.industry; renderSectorDetail(); return; }
  if(t.dataset.ct){ calTab=t.dataset.ct; save("calTab",calTab); renderCalendar(); return; }
  if(t.dataset.cs){ calScope=t.dataset.cs; save("calScope",calScope); renderCalendar(); return; }
  if(t.dataset.scr){ scrSel=t.dataset.scr; save("scr",scrSel); scrSort={k:null,dir:-1}; renderScreener(); return; }
  if(t.dataset.star){ e.stopPropagation(); const s=t.dataset.star, on=!me?.watch?.includes(s); api("/api/me/watch",{t:s,on}).then(()=>{ if(page==="screener") renderScreener(); else if(page==="market") renderMarket(); }).catch(()=>{}); return; }
  if(t.dataset.retryX){ t.disabled=true; t.textContent="Loading…"; xget(t.dataset.retryX,JSON.parse(t.dataset.retryP||"{}"),true).then(()=>{ if(t.closest("#drawer")) return renderTab(); ({market:renderMarket,calendar:renderCalendar,screener:renderScreener}[page]||render)(); }); return; }
},true);
/* the stars and inline links inside rows must not also open the row */
document.addEventListener("click",e=>{ if(e.target.closest("a[data-sel]")) e.preventDefault(); });
// refresh the market page while it is open
setInterval(()=>{ if(page==="market"&&!document.hidden){ const m=xpeek("macro"); if(m&&Date.now()-m.at>60e3) xget("macro",{},true).then(()=>page==="market"&&renderMarket()); else if(model) renderMarket(); } },20e3);
