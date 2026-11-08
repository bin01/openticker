/* filings list insiders last name first in capitals ("TETER TIMOTHY S"); say it the usual way ("Timothy S. Teter") */
function personName(x){ const w=String(x||"").trim().toLowerCase().replace(/\b[a-z]/g,c=>c.toUpperCase()).split(/\s+/).filter(Boolean);
  if(w.length<2||!/^[A-Z ]+$/.test(String(x).trim())) return w.join(" "); return [...w.slice(1).map(p=>p.length===1?p+".":p),w[0]].join(" "); }
/* OpenTicker: the stock page's tabs (Financials, Analysts, Ownership, Options, Dividends and filings, ETF holdings)
   and the written "What stands out" insights on its Overview. Uses globals from index.html and pages.js. */

let drTab="overview";
const isEtf=t=>(detailCache[t]?.info?.quoteType||"")==="ETF"||FUND_LIST.includes(t);
function tabsFor(t){
  return isEtf(t)
    ? [["overview","Overview"],["levels","Levels"],["holdings","Holdings"],["events","Distributions"]]
    : [["overview","Overview"],["levels","Levels"],["analysts","Analysts"],["financials","Financials"],["ownership","Ownership"],["options","Options"],["events","Dividends"]];
}
const TAB_SRC={analysts:"analysts",financials:"financials",ownership:"ownership",options:"options",events:"events",holdings:"etf"};
function prefetchStock(t){
  // load what the insights need right away; the rest loads when its tab opens
  const need=isEtf(t)?["etf","events"]:["analysts","ownership","options","financials","events"];
  need.forEach(n=>xget(n,{t}).then(()=>{ if(drawerOpen&&sel===t){ renderInsights(); if(TAB_SRC[drTab]===n) renderTab(); if(["analysts","ownership","events"].includes(n)) drawPriceChart(); } }));
}
function renderTabs(){
  const el=$("#drTabs"); if(!el) return;
  const tabs=tabsFor(sel); if(!tabs.some(x=>x[0]===drTab)) drTab="overview";
  el.innerHTML=tabs.map(([k,l])=>`<button role="tab" data-tab="${k}" aria-selected="${k===drTab}">${l}</button>`).join("");
  $("#drOverview").hidden=drTab!=="overview"; $("#drPane").hidden=drTab==="overview";
  if(drTab!=="overview") renderTab();
}
function setTab(k){ drTab=k; renderTabs(); const d=$("#drawer"); const top=$("#drTabs"); if(top&&d.scrollTop>top.offsetTop) d.scrollTop=top.offsetTop-8; }
function renderTab(){
  const el=$("#drPane"); if(!el||drTab==="overview") return;
  if(drTab==="levels") return paneLevels(el,sel);   // levels.js: its data depends on the bar size, not just the ticker
  const src=TAB_SRC[drTab], c=xpeek(src,{t:sel});
  if(!c||c.loading&&!c.data){ el.innerHTML=sk(380); xget(src,{t:sel}).then(()=>{ if(drawerOpen) renderTab(); }); return; }
  if(c.error){ el.innerHTML=errBox(c.error,src,{t:sel}); return; }
  const r=stockRow(sel)||{}, d=c.data;
  el.innerHTML=({analysts:paneAnalysts,financials:paneFinancials,ownership:paneOwnership,options:paneOptions,events:paneEvents,holdings:paneEtf}[drTab])(d,r);
  if(drTab==="analysts"&&detailCache[sel]&&r.last!=null) renderAnalyst(r,detailCache[sel],"drAnalyst2");
  if(drTab==="options") $("#optExp")?.addEventListener("change",async e=>{ const k={t:sel,exp:e.target.value}; el.querySelector("#optChain").innerHTML=sk(300); const x=await xget("options",k); if(drawerOpen) el.querySelector("#optChain").innerHTML=x.error?errBox(x.error):chainTable(x.data); });
  if(drTab==="financials") el.querySelectorAll("[data-freq]").forEach(b=>b.onclick=()=>{ finFreq=b.dataset.freq; save("finFreq",finFreq); renderTab(); });
}
document.addEventListener("click",e=>{ const b=e.target.closest("[data-tab]"); if(b&&b.closest("#drawer")){ e.preventDefault(); setTab(b.dataset.tab); } });

/* ---------- formatting helpers ---------- */
const usdB=x=>x==null||!isFinite(x)?"–":(x<0?"−":"")+"$"+(a=>a>=1e12?(a/1e12).toFixed(2)+"T":a>=1e9?(a/1e9).toFixed(a>=1e11?0:1)+"B":a>=1e6?(a/1e6).toFixed(0)+"M":a>=1e3?(a/1e3).toFixed(0)+"K":a.toFixed(0))(Math.abs(x));
const shs=x=>x==null?"–":(a=>a>=1e9?(a/1e9).toFixed(2)+"B":a>=1e6?(a/1e6).toFixed(1)+"M":a>=1e3?(a/1e3).toFixed(0)+"K":String(Math.round(a)))(Math.abs(x));
const qLabel=(d,freq)=>{ const x=new Date(d+"T12:00:00Z"); return freq==="annual"?"FY"+String(x.getUTCFullYear()).slice(2):x.toLocaleDateString("en-US",{month:"short",timeZone:"UTC"})+" \u2019"+String(x.getUTCFullYear()).slice(2); };   // "Jul ’25": a quarter ending in July 2025, not July 25th
const PERIOD={"0q":"This quarter","+1q":"Next quarter","0y":"This year","+1y":"Next year","LTG":"Long-term (5 yr)"};

/* ---------- small charts, drawn at the size they are shown (12px labels, light grid) ---------- */
const paneW=()=>{ const w=$("#drPane")?.clientWidth||520; return Math.round($("#drawer.full")&&w>=760?(w-40)/2:Math.min(720,Math.max(300,w))); };
const shortUsd=x=>x==null||!isFinite(x)?"–":(x<0?"−":"")+"$"+(a=>a>=1e12?(a/1e12).toFixed(1)+"T":a>=1e9?(a/1e9).toFixed(0)+"B":a>=1e6?(a/1e6).toFixed(0)+"M":a>=1e3?(a/1e3).toFixed(0)+"K":a.toFixed(a<10&&a%1?2:0))(Math.abs(x));
const swatch=se=>`<span><i class="sw" style="background:${se.color};opacity:${se.soft?.5:.9}"></i>${esc(se.name)}</span>`;
/* bar and line charts share one horizontal grid: n equal slots, a mark centered in each, so charts stacked
   above each other line up quarter for quarter. `missing[i]` shades a slot Yahoo has no figures for. */
/* on a narrow chart, "Mar ’25 Jun ’25 …" collides: keep the year only where it changes */
const slotLabels=(labels,gw)=>gw>=54?labels:labels.map((l,i)=>{ const [mo,yr]=l.split(" "); return !yr||i===0||labels[i-1].split(" ")[1]!==yr?l:mo; });
const finTip=x=>esc(x).replace(/\n/g,"&#10;");
function gapBand(x,w,T,bottom,label){
  return `<rect x="${x.toFixed(1)}" y="${T}" width="${w.toFixed(1)}" height="${(bottom-T).toFixed(1)}" rx="4" fill="var(--grid)" opacity=".55" pointer-events="none"/>`+
    (w>=50?`<text x="${(x+w/2).toFixed(1)}" y="${(T+(bottom-T)/2+4).toFixed(1)}" font-size="11" text-anchor="middle" fill="var(--ink-3)" pointer-events="none">${label}</text>`:"");
}
function yScale(all,{T,bottom}){
  const mn=Math.min(0,...all), mx=Math.max(0,...all), lo0=mn<0?mn*1.12:0, hi0=mx>0?mx*1.12:0;
  const ticks=niceTicks(lo0,hi0||Math.abs(lo0)*.1,3), lo=Math.min(lo0,ticks[0]), hi=Math.max(hi0,ticks[ticks.length-1]);
  return {ticks, Y:v=>T+(bottom-T)*(1-(v-lo)/((hi-lo)||1))};
}
function gridLines(ticks,Y,L,W,R,axis){
  return ticks.map(t=>`<line x1="${L}" x2="${W-R}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="${t===0?"var(--rule)":"var(--grid)"}"/><text x="${L-6}" y="${(Y(t)+3.5).toFixed(1)}" font-size="11.5" text-anchor="end" class="mono" fill="var(--ink-3)">${axis(t)}</text>`).join("");
}
function barChart(labels,series,{h=150,fmt=usdB,axis=shortUsd,note,missing=[],r=6}={}){
  const W=paneW(),H=h,L=44,R=r,T=16,B=22, n=labels.length, k=series.length, bottom=H-B;
  const all=series.flatMap(s=>s.values).filter(v=>v!=null); if(!all.length) return "";
  const {ticks,Y}=yScale(all,{T,bottom}), gw=(W-L-R)/n, bw=Math.max(5,Math.min(k===1?36:24,(gw*.7-(k-1)*3)/k)), axl=slotLabels(labels,gw);
  let s=`<svg class="chart fin-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">`+gridLines(ticks,Y,L,W,R,axis);
  labels.forEach((lab,i)=>{ const x0=L+gw*i, cx=x0+gw/2;
    if(missing[i]||series.every(se=>se.values[i]==null)){ s+=gapBand(x0+3,gw-6,T-6,bottom,"No data"); }
    else s+=`<rect class="hov" x="${(x0+2).toFixed(1)}" y="${T-6}" width="${(gw-4).toFixed(1)}" height="${(bottom-T+6).toFixed(1)}" rx="4"><title>${finTip(lab+"\n"+series.map(se=>se.name+": "+(se.values[i]==null?"not reported":fmt(se.values[i]))).join("\n"))}</title></rect>`;
    series.forEach((se,j)=>{ const v=se.values[i]; if(v==null) return; const x=cx-(k*bw+(k-1)*3)/2+j*(bw+3), y=Math.min(Y(v),Y(0)), hh=Math.abs(Y(v)-Y(0));
      s+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(hh,1.5).toFixed(1)}" rx="${Math.min(3,bw/4)}" fill="${v<0?"var(--down)":se.color}" opacity="${se.soft?.5:.9}" pointer-events="none"/>`;
      if(j===0&&se.top&&i===n-1&&se.top[i]) s+=`<text x="${Math.min(W-R,x+bw/2).toFixed(1)}" y="${(Y(Math.max(v,0))-5).toFixed(1)}" font-size="12" text-anchor="${x+bw/2>W-60?"end":"middle"}" class="mono" font-weight="600" fill="var(--ink)">${se.top[i]}</text>`; });
    s+=`<text x="${cx.toFixed(1)}" y="${H-6}" font-size="12" text-anchor="middle" fill="var(--ink-3)">${esc(axl[i])}</text>`; });
  s+="</svg>";
  return `<div class="legend" style="margin-bottom:6px">${series.map(swatch).join("")}${note?`<span class="ks">${note}</span>`:""}</div>`+s;
}
/* Revenue with net income drawn inside it: the inner bar is the slice of revenue the company kept,
   a loss hangs below the line in red. Every quarter carries its revenue, and under its date a pill with the change from
   the period before (Yahoo keeps only five quarters, so a year-earlier comparison exists for the latest one alone). */
function revChart(labels,rev,ni,growth,{missing=[],h=204,r=6,yoy=[],prevWord="quarter"}={}){
  const W=paneW(),H=h,L=44,R=r,T=22,B=48, n=labels.length, bottom=H-B;
  const all=[...rev,...ni].filter(v=>v!=null); if(!all.length) return "";
  const {ticks,Y}=yScale(all,{T,bottom}), gw=(W-L-R)/n, bw=Math.max(8,Math.min(44,gw*.6)), iw=Math.max(4,bw*.42), axl=slotLabels(labels,gw);
  const fitsAll=rev.every(v=>v==null||usdB(v).length*7+6<=gw);
  let s=`<svg class="chart fin-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">`+gridLines(ticks,Y,L,W,R,shortUsd);
  labels.forEach((lab,i)=>{ const x0=L+gw*i, cx=x0+gw/2, v=rev[i], p=ni[i], g=growth[i], last=i===n-1;
    if(missing[i]) s+=gapBand(x0+3,gw-6,T-8,bottom,"No report");
    else s+=`<rect class="hov" x="${(x0+2).toFixed(1)}" y="${T-8}" width="${(gw-4).toFixed(1)}" height="${(bottom-T+8).toFixed(1)}" rx="4"><title>${finTip(lab+"\nRevenue: "+(v==null?"not reported":usdB(v))+"\nNet income: "+(p==null?"not reported":usdB(p))+(g!=null?`\nRevenue vs the ${prevWord} before: `+pct(g,0):"")+(yoy[i]!=null&&prevWord==="quarter"?"\nRevenue vs a year earlier: "+pct(yoy[i],0):""))}</title></rect>`;
    if(v!=null){ const y=Math.min(Y(v),Y(0)), hh=Math.abs(Y(v)-Y(0));
      s+=`<rect x="${(cx-bw/2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(hh,2).toFixed(1)}" rx="${Math.min(4,bw/5)}" fill="var(--accent)" opacity="${hh<2?.9:.45}" pointer-events="none"/>`;
      if(fitsAll||last) s+=`<text x="${cx.toFixed(1)}" y="${(Y(Math.max(v,0))-6).toFixed(1)}" font-size="${last?12:11.5}" text-anchor="middle" class="mono" font-weight="${last?600:400}" fill="${last?"var(--ink)":"var(--ink-2)"}">${usdB(v)}</text>`; }
    if(p!=null){ const y=Math.min(Y(p),Y(0)), hh=Math.abs(Y(p)-Y(0));
      s+=`<rect x="${(cx-iw/2).toFixed(1)}" y="${y.toFixed(1)}" width="${iw.toFixed(1)}" height="${Math.max(hh,1.5).toFixed(1)}" rx="${Math.min(2.5,iw/4)}" fill="${p<0?"var(--down)":"var(--accent)"}" opacity=".95" pointer-events="none"/>`; }
    s+=`<text x="${cx.toFixed(1)}" y="${H-29}" font-size="12" text-anchor="middle" fill="var(--ink-3)">${esc(axl[i])}</text>`;
    if(g!=null){ const t=pct(g,0), pw=Math.min(gw-4,t.length*7.2+14), up=g>=0;
      s+=`<rect x="${(cx-pw/2).toFixed(1)}" y="${H-21}" width="${pw.toFixed(1)}" height="19" rx="9.5" fill="var(--${up?"up":"down"}-soft)"/><text x="${cx.toFixed(1)}" y="${H-7.5}" font-size="12" font-weight="600" text-anchor="middle" class="mono" fill="var(--${up?"up":"down"})">${t}</text>`; } });
  s+="</svg>";
  const loss=ni.some(v=>v!=null&&v<0);
  return `<div class="legend" style="margin-bottom:6px"><span><i class="sw" style="background:var(--accent);opacity:.45"></i>Revenue</span><span><i class="sw" style="background:var(--accent)"></i>Profit</span>${loss?`<span><i class="sw" style="background:var(--down)"></i>Loss</span>`:""}${growth.some(g=>g!=null)?`<span class="ks">Under each date: change from the ${prevWord} before</span>`:""}</div>`+s;
}
function lineChart(labels,series,{h=140,fmt=v=>pc(v,0),missing=[],r=44}={}){
  const W=paneW(),H=h,L=44,R=r,T=10,B=22, n=labels.length, bottom=H-B, all=series.flatMap(s=>s.values).filter(v=>v!=null); if(!all.length||n<2) return "";
  let lo=Math.min(...all),hi=Math.max(...all); const pad=(hi-lo)*.15||Math.abs(hi)*.1||.05; lo-=pad; hi+=pad;
  const gw=(W-L-R)/n, X=i=>L+gw*(i+.5), Y=v=>T+(bottom-T)*(1-(v-lo)/(hi-lo));
  let s=`<svg class="chart fin-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`;
  labels.forEach((_,i)=>{ if(missing[i]) s+=gapBand(L+gw*i+3,gw-6,T-6,bottom,""); });
  niceTicks(lo,hi,3).forEach(t=>{ s+=`<line x1="${L}" x2="${W-R}" y1="${Y(t).toFixed(1)}" y2="${Y(t).toFixed(1)}" stroke="var(--grid)"/><text x="${L-6}" y="${(Y(t)+3.5).toFixed(1)}" font-size="11.5" text-anchor="end" class="mono" fill="var(--ink-3)">${fmt(t)}</text>`; });
  const ends=[];
  series.forEach(se=>{ const pts=se.values.map((v,i)=>[i,v]).filter(p=>p[1]!=null); if(!pts.length) return;
    // solid between neighbouring quarters, dashed across quarters with no figure, so a gap never reads as a trend
    for(let j=1;j<pts.length;j++){ const a=pts[j-1],b=pts[j];
      s+=`<line x1="${X(a[0]).toFixed(1)}" y1="${Y(a[1]).toFixed(1)}" x2="${X(b[0]).toFixed(1)}" y2="${Y(b[1]).toFixed(1)}" stroke="${se.color}" stroke-width="1.75" stroke-linecap="round" opacity="${se.soft?.6:1}"${b[0]-a[0]>1?` stroke-dasharray="2 4" opacity=".5"`:""}/>`; }
    pts.forEach(p=>{ s+=`<circle cx="${X(p[0]).toFixed(1)}" cy="${Y(p[1]).toFixed(1)}" r="${p===pts[pts.length-1]?2.75:2}" fill="${se.color}" opacity="${se.soft?.7:1}"><title>${finTip(se.name+" · "+labels[p[0]]+": "+fmt(p[1]))}</title></circle>`; });
    const e=pts[pts.length-1]; ends.push({x:X(e[0])+7,y:Y(e[1])+3.5,v:e[1],se}); });
  ends.sort((a,b)=>a.y-b.y).forEach((e,i,a)=>{ if(i&&e.y-a[i-1].y<13) e.y=a[i-1].y+13; });
  ends.forEach(e=>{ s+=`<text x="${e.x.toFixed(1)}" y="${e.y.toFixed(1)}" font-size="12" class="mono" fill="${e.se.soft?"var(--ink-2)":e.se.color}">${fmt(e.v)}</text>`; });
  slotLabels(labels,gw).forEach((lab,i)=>{ s+=`<text x="${X(i).toFixed(1)}" y="${H-6}" font-size="12" text-anchor="middle" fill="var(--ink-3)">${esc(lab)}</text>`; });
  return `<div class="legend" style="margin-bottom:6px">${series.map(swatch).join("")}</div>`+s+"</svg>";
}
const C1="var(--accent)", C2="var(--ink-3)", C3="var(--warn)";

/* ---------- Financials ---------- */
let finFreq=load("finFreq","quarterly");
function rowOf(block,key){ return block?.rows?.find(r=>r.key===key)?.values||[]; }
/* Statements come with their own period lists, which skip quarters Yahoo doesn't have and end at different
   dates. Put every statement on one timeline (each quarter or year from the first to the latest, gaps kept)
   so charts line up, growth compares with the right period, and a missing quarter shows as missing. */
const monthKey=d=>{ const x=new Date(d+"T12:00:00Z"); x.setUTCDate(x.getUTCDate()+16); return x.getUTCFullYear()*12+x.getUTCMonth()-1; };   // a period ending Jan 3 belongs to December
const keyLabel=(k,freq)=>{ const y=Math.floor(k/12), yy=String(y).slice(2); return freq==="annual"?"FY"+yy:new Date(Date.UTC(y,k%12,15)).toLocaleDateString("en-US",{month:"short",timeZone:"UTC"})+" ’"+yy; };
const filled=b=>(b?.periods||[]).filter((_,i)=>(b.rows||[]).some(r=>r.values[i]!=null));   // Yahoo lists some periods with every figure blank
function finTimeline(blocks,freq,max=10){
  const step=freq==="annual"?12:3, have=[...new Set(blocks.flatMap(b=>filled(b).map(monthKey)))].sort((a,b)=>a-b); if(!have.length) return [];
  const out=new Set(have);
  for(let k=have[have.length-1]-step;k>have[0];k-=step) if(!have.some(h=>Math.abs(h-k)<=1)) out.add(k);
  return [...out].sort((a,b)=>a-b).slice(-max);
}
const slotOf=(keys,k)=>{ for(const d of [0,-1,1]){ const i=keys.indexOf(k+d); if(i>=0) return i; } return -1; };
function onTimeline(T,block,key){ const ks=(block?.periods||[]).map(monthKey), v=rowOf(block,key); return T.map(k=>{ const i=slotOf(ks,k); return i<0?null:v[i]??null; }); }
const hasPeriod=(T,block)=>{ const ks=filled(block).map(monthKey); return T.map(k=>slotOf(ks,k)>=0); };
const yearBefore=(T,i)=>slotOf(T,T[i]-12);   // the slot a year earlier, or -1
function finSeries(d,freq=finFreq){
  const F=d[freq]||{}, inc=F.income||{}, cf=F.cashflow||{}, bs=F.balance||{}, T=finTimeline([inc,cf,bs],freq);
  const at=(b,k)=>onTimeline(T,b,k);
  return {T,inc,cf,bs,labels:T.map(k=>keyLabel(k,freq)),incOk:hasPeriod(T,inc),cfOk:hasPeriod(T,cf),bsOk:hasPeriod(T,bs),
    rev:at(inc,"Total Revenue"),gp:at(inc,"Gross Profit"),op:at(inc,"Operating Income"),ni:at(inc,"Net Income"),
    fcf:at(cf,"Free Cash Flow"),bb:at(cf,"Repurchase Of Capital Stock").map(v=>v==null?null:-v),dv:at(cf,"Cash Dividends Paid").map(v=>v==null?null:-v),
    cash:at(bs,"Cash Cash Equivalents And Short Term Investments"),debt:at(bs,"Total Debt"),shares:at(bs,"Ordinary Shares Number")};
}
// growth on the same period a year earlier; a quarter with no revenue (or none to compare with) has no growth
const yoyAt=(T,arr,i)=>{ const j=yearBefore(T,i); return j>=0&&arr[i]&&arr[j]?arr[i]/arr[j]-1:null; };
// change from the slot just before, when that slot is the previous period on the grid
const prevAt=(T,arr,i,step)=>i>0&&Math.abs(T[i]-T[i-1]-step)<=1&&arr[i]&&arr[i-1]?arr[i]/arr[i-1]-1:null;
const listAnd=a=>a.length<2?a.join(""):a.slice(0,-1).join(", ")+" and "+a[a.length-1];
function paneFinancials(d){
  const s=finSeries(d), T=s.T, labs=s.labels, n=T.length, ann=finFreq==="annual", unit=ann?"year":"quarter";
  if(!(s.inc.periods||[]).length) return `<p class="hint">Yahoo has no financial statements for this company.</p>`;
  const growth=s.rev.map((_,i)=>yoyAt(T,s.rev,i));
  const m=k=>s.rev.map((r,i)=>r&&k[i]!=null?k[i]/r:null);
  const lastI=s.incOk.lastIndexOf(true), g=growth[lastI], prevI=lastI>0?s.incOk.lastIndexOf(true,lastI-1):-1, gPrev=prevI>=0?growth[prevI]:null;
  const notes=[];
  if(g!=null) notes.push(`Revenue ${g>=0?"grew":"fell"} ${pc(Math.abs(g),0)} from a year earlier in the latest ${unit} (${labs[lastI]})${gPrev!=null?`, ${g>gPrev+0.02?"faster than":g<gPrev-0.02?"slower than":"about the same as"} the ${unit} before (${pct(gPrev,0)})`:""}.`);
  const om=m(s.op), ya=yearBefore(T,lastI), base=ya>=0&&om[ya]!=null?ya:om.findIndex(v=>v!=null);
  if(om[lastI]!=null&&base>=0&&base<lastI){ const gap=Math.round((T[lastI]-T[base])/(ann?12:3));
    notes.push(`Operating margin is ${pc(om[lastI],0)}, ${om[lastI]>om[base]+0.01?"up from":om[lastI]<om[base]-0.01?"down from":"steady versus"} ${pc(om[base],0)} ${base===ya?"a year ago":gap+" "+unit+"s ago"}.`); }
  const sh=s.shares.map((v,i)=>[v,i]).filter(x=>x[0]); if(sh.length>1){ const ch=sh[sh.length-1][0]/sh[0][0]-1; if(Math.abs(ch)>0.01) notes.push(`Share count ${ch<0?"shrank":"grew"} ${pc(Math.abs(ch),1)} from ${labs[sh[0][1]]} to ${labs[sh[sh.length-1][1]]}${ch<0?", so buybacks are lifting each share's slice of profit":", which dilutes existing holders"}.`); }
  // be plain about holes in Yahoo's data instead of drawing them as zeros
  const zero=labs.filter((_,i)=>s.incOk[i]&&s.rev[i]===0&&s.rev.some(v=>v>0)), gaps=labs.filter((_,i)=>!s.incOk[i]);
  if(zero.length||gaps.length) notes.push(`Yahoo ${zero.length?`shows no revenue for ${listAnd(zero)}${gaps.length?" and ":""}`:""}${gaps.length?`has no income statement for ${listAnd(gaps)}`:""}, so ${zero.length?"margins and growth skip those":"the charts leave "+(gaps.length>1?"those":"that")+" "+unit+(gaps.length>1?"s":"")+" empty"}.`);
  const tbl=(blk)=>`<table class="hz fin"><thead><tr><th></th>${(blk.periods||[]).map(p=>`<th>${qLabel(p,finFreq)}</th>`).join("")}</tr></thead><tbody>${(blk.rows||[]).map(r=>`<tr><td>${esc(r.label)}</td>${r.values.map(v=>`<td class="num">${r.key==="Diluted EPS"?(v==null?"–":"$"+v.toFixed(2)):r.key==="Ordinary Shares Number"?shs(v):usdB(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  const R=44, anyCf=s.cfOk.some(Boolean), anyBs=s.bsOk.some(Boolean);
  return `<div class="seg sm" style="margin-bottom:12px"><button data-freq="quarterly" aria-pressed="${finFreq==="quarterly"}">Quarterly</button><button data-freq="annual" aria-pressed="${ann}">Annual</button></div>
    ${notes.length?insightList(notes.map(t=>({html:t}))):""}
    <div class="dr-sec half"><h4>Revenue and profit</h4>${revChart(labs,s.rev,s.ni,ann?growth:s.rev.map((_,i)=>prevAt(T,s.rev,i,3)),{missing:s.incOk.map(x=>!x),r:R,yoy:growth,prevWord:unit})}</div>
    <div class="dr-sec half"><h4>Margins</h4>${lineChart(labs,[{name:"Gross",values:m(s.gp),color:C2,soft:1},{name:"Operating",values:m(s.op),color:C1},{name:"Net",values:m(s.ni),color:C3}],{missing:s.incOk.map(x=>!x),r:R,h:204})}</div>
    ${anyCf?`<div class="dr-sec half"><h4>Cash generated and returned</h4>${barChart(labs,[{name:"Free cash flow",values:s.fcf,color:C1},...(s.bb.some(v=>v)?[{name:"Buybacks",values:s.bb,color:C2,soft:1}]:[]),...(s.dv.some(v=>v)?[{name:"Dividends",values:s.dv,color:C3}]:[])],{missing:s.cfOk.map(x=>!x),r:R,h:170})}</div>`:""}
    ${anyBs?`<div class="dr-sec half"><h4>Cash and debt</h4>${barChart(labs,[{name:"Cash and investments",values:s.cash,color:C1},...(s.debt.some(v=>v)?[{name:"Total debt",values:s.debt,color:C3}]:[])],{missing:s.bsOk.map(x=>!x),r:R,h:170})}</div>`:""}
    <details class="dr-sec"><summary><h4 style="display:inline">All figures</h4></summary>${tbl(s.inc)}${tbl(s.cf)}${tbl(s.bs)}</details>`;
}

/* ---------- Analysts ---------- */
function paneAnalysts(d,r){
  const tr=(d.trend||[]).slice().reverse(), names=["strongBuy","buy","hold","sell","strongSell"], cols=["var(--up)","color-mix(in oklab,var(--up) 55%,var(--panel))","var(--ink-3)","color-mix(in oklab,var(--down) 55%,var(--panel))","var(--down)"];
  const lbl={"0m":"Now","-1m":"1 month ago","-2m":"2 months ago","-3m":"3 months ago"};
  const trend=tr.length?`<div class="rtrend">${tr.map(p=>{ const tot=names.reduce((a,k)=>a+(p[k]||0),0)||1; return `<div class="rt"><span class="ks">${lbl[p.period]||p.period}</span><span class="rbar">${names.map((k,i)=>p[k]?`<i style="width:${(p[k]/tot*100).toFixed(1)}%;background:${cols[i]}" title="${k}: ${p[k]}"></i>`:"").join("")}</span><span class="num ks">${tot}</span></div>`; }).join("")}
    <div class="meter-l" style="margin-left:100px"><span><i class="sw" style="background:${cols[0]}"></i>Strong buy</span><span><i class="sw" style="background:${cols[1]}"></i>Buy</span><span><i class="sw" style="background:${cols[2]}"></i>Hold</span><span><i class="sw" style="background:${cols[4]}"></i>Sell</span></div></div>`:"";
  const et=d.eps_trend||{}, ev=d.eps_revisions||{}, ee=d.earnings_estimate||{}, re=d.revenue_estimate||{}, ge=d.growth_estimates||{};
  const per=["0q","+1q","0y","+1y"].filter(p=>et[p]||ee[p]);
  const chg=(a,b)=>a!=null&&b?a/b-1:null;
  const estT=per.length?`<table class="hz"><thead><tr><th>EPS estimate</th><th>Now</th><th>30 days ago</th><th>90 days ago</th><th>Change (90d)</th><th>Revisions (30d)</th></tr></thead><tbody>${per.map(p=>{ const e=et[p]||{}, v=ev[p]||{}, c=chg(e.current,e["90daysAgo"]);
      return `<tr><td>${PERIOD[p]}</td><td class="num">${e.current!=null?"$"+e.current.toFixed(2):"–"}</td><td class="num ks">${e["30daysAgo"]!=null?"$"+e["30daysAgo"].toFixed(2):"–"}</td><td class="num ks">${e["90daysAgo"]!=null?"$"+e["90daysAgo"].toFixed(2):"–"}</td><td class="num ${cls(c)}">${pct(c,1)}</td><td class="num"><span class="up">▲${v.upLast30days??0}</span> <span class="down">▼${v.downLast30days??0}</span></td></tr>`; }).join("")}</tbody></table>`:"";
  const fT=per.length?`<table class="hz fct"><thead><tr><th>Forecast</th><th>EPS</th><th>Growth</th><th>Revenue</th><th>Growth</th><th>Analysts</th></tr></thead><tbody>${per.map(p=>{ const e=ee[p]||{}, v=re[p]||{};
      return `<tr><td>${PERIOD[p]}</td><td class="num">${e.avg!=null?"$"+e.avg.toFixed(2):"–"}</td><td class="num ${cls(e.growth)}">${pct(e.growth,0)}</td><td class="num">${usdB(v.avg)}</td><td class="num ${cls(v.growth)}">${pct(v.growth,0)}</td><td class="num ks">${e.numberOfAnalysts??"–"}</td></tr>`; }).join("")}</tbody></table>`:"";
  const gT=Object.keys(ge).length?`<p class="hint" style="margin:8px 0 0">${["0y","+1y","LTG"].filter(p=>ge[p]?.stockTrend!=null).map(p=>`${PERIOD[p]}: ${esc(sel)} ${pct(ge[p].stockTrend,0)}${ge[p].indexTrend!=null?` vs S&amp;P 500 ${pct(ge[p].indexTrend,0)}`:""}`).join(" · ")} expected earnings growth.</p>`:"";
  const ch=d.changes||[], ups=ch.filter(c=>/up/i.test(c.action)).length, downs=ch.filter(c=>/down/i.test(c.action)).length;
  const ptUp=ch.filter(c=>c.pt&&c.ptPrior&&c.pt>c.ptPrior).length, ptDn=ch.filter(c=>c.pt&&c.ptPrior&&c.pt<c.ptPrior).length;
  const act=c=>/up/i.test(c.action)?`<span class="chip up">Upgrade</span>`:/down/i.test(c.action)?`<span class="chip down">Downgrade</span>`:/init/i.test(c.action)?`<span class="chip">New</span>`:`<span class="chip">${/reit|main/i.test(c.action)?"Reiterated":esc(c.action||"")}</span>`;
  const chT=ch.length?`<p class="hint" style="margin:0 0 8px">${ch.length} analyst notes in the last year: ${ups} upgrade${ups===1?"":"s"}, ${downs} downgrade${downs===1?"":"s"}${ptUp+ptDn?`, ${ptUp} price-target raise${ptUp===1?"":"s"} and ${ptDn} cut${ptDn===1?"":"s"}`:""}.</p><table class="hz rchg"><tbody>${ch.slice(0,18).map(c=>`<tr><td class="ks">${new Date(c.date+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"})}</td><td>${esc(c.firm||"")}</td><td>${act(c)}</td><td class="ks">${c.from&&c.from!==c.to?esc(c.from)+" → ":""}${esc(c.to||"")}</td><td class="num">${c.pt?`${c.ptPrior&&c.ptPrior!==c.pt?`<span class="ks">$${Math.round(c.ptPrior)} → </span>`:""}$${Math.round(c.pt)}`:""}</td></tr>`).join("")}</tbody></table>`:`<p class="hint">No rating changes in the last year.</p>`;
  return `<div class="dr-sec" style="margin-top:0"><div id="drAnalyst2"></div></div>
    ${trend?`<div class="dr-sec"><h4>Ratings over the last 3 months</h4>${trend}</div>`:""}
    ${estT?`<div class="dr-sec"><h4>Where earnings estimates are heading</h4>${estT}</div>`:""}
    ${fT?`<div class="dr-sec"><h4>Forecasts</h4>${fT}${gT}</div>`:""}
    <div class="dr-sec"><h4>Rating changes</h4>${chT}</div>`;
}

/* ---------- Ownership ---------- */
function paneOwnership(d){
  const m=d.major||{}, ins=m.insidersPercentHeld, inst=m.institutionsPercentHeld, other=ins!=null&&inst!=null?Math.max(0,1-ins-inst):null;
  const bar=ins!=null&&inst!=null?`<div class="obar"><i style="width:${(inst*100).toFixed(1)}%;background:${C1}"></i><i style="width:${(ins*100).toFixed(1)}%;background:${C3}"></i><i style="width:${(other*100).toFixed(1)}%;background:var(--ink-3);opacity:.35"></i></div>
    <div class="legend"><span><i class="sw" style="background:${C1}"></i>Institutions ${pc(inst,0)}</span><span><i class="sw" style="background:${C3}"></i>Insiders ${pc(ins,1)}</span><span><i class="sw" style="background:var(--ink-3);opacity:.35"></i>Everyone else ${pc(other,0)}</span>${m.institutionsCount?`<span class="ks">${Math.round(m.institutionsCount).toLocaleString("en-US")} institutions</span>`:""}</div>`:"";
  const tx=d.insiders||[], buys=tx.filter(x=>x.kind==="buy"), sells=tx.filter(x=>x.kind==="sell");
  const bv=buys.reduce((a,x)=>a+(x.value||0),0), sv=sells.reduce((a,x)=>a+(x.value||0),0);
  const sum=tx.length?`<div class="kf" style="margin-top:0"><div><div class="lbl">Insider buys (12 mo)</div><div class="v up">${buys.length}</div><div class="ks">${usdB(bv)}</div></div><div><div class="lbl">Insider sales (12 mo)</div><div class="v down">${sells.length}</div><div class="ks">${usdB(sv)}</div></div><div><div class="lbl">Net</div><div class="v ${cls(bv-sv)}">${bv-sv>=0?"Buying":"Selling"}</div><div class="ks">${usdB(Math.abs(bv-sv))}</div></div></div>
    <p class="hint">Insiders sell for many reasons (taxes, diversification, planned sales), so steady selling is normal. Open-market buying is rarer and usually more telling.</p>`:"";
  const tc=personName, aw=tx.filter(x=>x.kind==="award").length, shown=tx.filter(x=>x.kind!=="award");
  const txT=shown.length?`<table class="hz itx"><thead><tr><th>Date</th><th style="text-align:left">Insider</th><th style="text-align:left">Type</th><th>Shares</th><th>Value</th></tr></thead><tbody>${shown.slice(0,25).map(x=>`<tr><td class="ks">${x.date?new Date(x.date+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"}):""}</td><td>${esc(tc(x.insider))}<div class="ks">${esc(tc(x.role))}</div></td><td><span class="chip ${x.kind==="buy"?"up":x.kind==="sell"?"down":""}">${{buy:"Buy",sell:"Sale",award:"Award",other:"Other"}[x.kind]}</span></td><td class="num">${shs(x.shares)}</td><td class="num">${x.value?usdB(x.value):"–"}</td></tr>`).join("")}</tbody></table>${aw?`<p class="hint">Not shown: ${aw} stock awards (pay, not trades).</p>`:""}`:`<p class="hint">${aw?`Only stock awards (${aw}) in the last year, no buying or selling.`:"No insider transactions reported in the last year."}</p>`;
  const hT=rows=>rows.length?`<table class="hz"><thead><tr><th>Holder</th><th>Owns</th><th>Value</th><th>Change</th></tr></thead><tbody>${rows.map(h=>`<tr><td>${esc(h.holder||"")}</td><td class="num">${pc(h.pct,2)}</td><td class="num">${usdB(h.value)}</td><td class="num ${cls(h.chg)}">${pct(h.chg,1)}</td></tr>`).join("")}</tbody></table><p class="hint">Change is the shift in shares held at their latest filing.</p>`:`<p class="hint">Not reported.</p>`;
  return `${bar?`<div class="dr-sec" style="margin-top:0"><h4>Who owns it</h4>${bar}</div>`:""}
    <div class="dr-sec"><h4>Insider trading</h4>${sum}${txT}</div>
    <div class="dr-sec"><h4>Largest institutions</h4>${hT(d.institutions||[])}</div>
    <div class="dr-sec"><h4>Largest funds</h4>${hT(d.funds||[])}</div>`;
}

/* ---------- Options ---------- */
function moveCard(x,title,price){
  if(!x||x.move==null) return "";
  const lo=price*(1-x.move), hi=price*(1+x.move);
  return `<div class="stat"><div class="lbl">${title}</div><div class="v">±${pc(x.move,1)}</div><div class="ks">${money(lo)} to ${money(hi)} by ${new Date(x.expiry+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"})}${ivOk(x.iv,x.expiry,x.move)?` · implied volatility ${pc(x.iv,0)}`:""}</div></div>`;
}
/* Yahoo's implied volatility is unreliable near expiry and outside market hours (2% next to a ±4% two-day move); only show it when it is plausible */
function ivOk(iv,expiry,move,ref){ if(!(iv>0.08)) return false; const days=(new Date(expiry+"T21:00:00Z")-Date.now())/864e5; if(days<2) return false;
  const est=move>0?move/(0.8*Math.sqrt(days/365)):ref; return !(est>0)||(iv>=est*0.5&&iv<=est*2); }   // est: the yearly swing the expected move implies
function chainTable(d){
  const c=d?.chain; if(!c?.rows?.length) return `<p class="hint">No contracts for this date.</p>`;
  const p=d.price, f=v=>v==null?"–":v.toFixed(2), n=v=>v==null?"–":Math.round(v).toLocaleString("en-US");
  const atm=c.rows.reduce((b,r)=>Math.abs(r.strike-p)<Math.abs(b.strike-p)?r:b,c.rows[0]).strike;
  return `<div class="tbl-wrap"><table class="hz chain"><thead><tr><th colspan="4" class="ctr">Calls</th><th class="ctr">Strike</th><th colspan="4" class="ctr">Puts</th></tr><tr><th>Bid</th><th>Ask</th><th>Vol</th><th>OI</th><th></th><th>Bid</th><th>Ask</th><th>Vol</th><th>OI</th></tr></thead><tbody>${c.rows.map(r=>`<tr class="${r.strike===atm?"atm":""}"><td class="num ${r.strike<p?"itm":""}">${f(r.call?.bid)}</td><td class="num ${r.strike<p?"itm":""}">${f(r.call?.ask)}</td><td class="num ks">${n(r.call?.vol)}</td><td class="num ks">${n(r.call?.oi)}</td><td class="num ctr"><b>${r.strike}</b></td><td class="num ${r.strike>p?"itm":""}">${f(r.put?.bid)}</td><td class="num ${r.strike>p?"itm":""}">${f(r.put?.ask)}</td><td class="num ks">${n(r.put?.vol)}</td><td class="num ks">${n(r.put?.oi)}</td></tr>`).join("")}</tbody></table></div><p class="hint">Shaded cells are in the money. The highlighted row is the strike closest to the price.</p>`;
}
function paneOptions(d){
  if(!d.expirations?.length) return `<p class="hint">No options data for this stock right now. Some stocks have no listed options; for others Yahoo may be briefly unavailable, so try again in a few minutes.</p>`;
  const U=d.unusual||[], anyOI=U.some(u=>u.oi>0);   // columns that would be empty on every row are left out
  const p=d.price, hist=typicalEarningsMove(sel), ivRef=d.near?.move>0?d.near.move/(0.8*Math.sqrt(Math.max(1,d.near.days||1)/365)):null; const anyIV=U.some(u=>ivOk(u.iv,u.expiry,null,ivRef));
  const pcv=d.pcVolume, mood=pcv==null?"":pcv>1.2?"Traders are buying more puts than calls, a defensive lean.":pcv<0.6?"Calls far outnumber puts, a bullish lean.":"Puts and calls are fairly balanced.";
  return `<div class="stats">${moveCard(d.near,"Expected move, next expiry",p)}${d.earnings?moveCard(d.earnings,`Through earnings, ${dayLabel(d.earnings.earningsDate).replace(/^[A-Z][a-z]{2}, /,"")}`,p):""}
      <div class="stat"><div class="lbl">Put/call ratio</div><div class="v">${pcv!=null?pcv.toFixed(2):"–"}</div><div class="ks">by volume${d.pcOI!=null?` · ${d.pcOI.toFixed(2)} by open interest`:""}</div></div>
      ${hist!=null?`<div class="stat"><div class="lbl">Typical earnings move</div><div class="v">±${pc(hist,1)}</div><div class="ks">average over the last reports</div></div>`:""}</div>
    <p class="hint">The expected move is how far option prices say the stock could swing, up or down, by that date (the price of a bet on either direction at today's price, divided by the stock price). ${mood}${d.earnings&&hist!=null?` Options price a ${pc(d.earnings.move,1)} move through earnings versus a typical ${pc(hist,1)}, so they look ${d.earnings.move>hist*1.15?"expensive":d.earnings.move<hist*0.85?"cheap":"about fairly priced"} by that measure.`:""}</p>
    <div class="dr-sec"><h4>Unusual activity</h4>${d.unusual?.length?`<table class="hz"><thead><tr><th>Contract</th><th>Volume</th>${anyOI?"<th>Open interest</th>":""}${anyIV?`<th title="Implied volatility: the yearly swing option prices assume">Implied vol.</th>`:""}</tr></thead><tbody>${d.unusual.map(u=>`<tr><td><span class="chip ${u.side==="call"?"up":"down"}">${u.side==="call"?"Call":"Put"}</span> $${u.strike} · ${new Date(u.expiry+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"})}</td><td class="num">${u.volume.toLocaleString("en-US")}</td>${anyOI?`<td class="num ks">${u.oi?u.oi.toLocaleString("en-US"):"New"}</td>`:""}${anyIV?`<td class="num">${ivOk(u.iv,u.expiry,null,ivRef)?pc(u.iv,0):"–"}</td>`:""}</tr>`).join("")}</tbody></table><p class="hint">Contracts trading more than twice their open interest (the contracts already held), a sign of fresh positioning.${anyOI?` "New" means none were held before today.`:" None of these were held before today."}</p>`:`<p class="hint">Nothing unusual in the nearest three expiries.</p>`}</div>
    <div class="dr-sec"><h4>Option chain</h4><div class="frm" style="margin-bottom:8px"><select id="optExp">${d.expirations.map(e=>`<option value="${e}" ${e===d.chain?.expiry?"selected":""}>${new Date(e+"T12:00:00Z").toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</option>`).join("")}</select></div><div id="optChain">${chainTable(d)}</div></div>`;
}
function typicalEarningsMove(t){
  const h=earnHist[t]; if(!h?.rows) return null; const today=base.dates[base.dates.length-1];
  const rx=h.rows.filter(x=>x.eps!=null&&x.date<=today).slice(0,8).map(x=>reaction(t,x.date,x.hour)).filter(v=>v!=null);
  return rx.length>=3?rx.reduce((a,v)=>a+Math.abs(v),0)/rx.length:null;
}

/* ---------- Dividends and filings ---------- */
function paneEvents(d,r){
  const yrs=d.dividendYears||[], thisYear=new Date().getFullYear(), full=yrs.filter(y=>y.year<thisYear);
  const cagr=full.length>=6?Math.pow(full[full.length-1].total/full[full.length-6].total,1/5)-1:null;
  const last4=(d.dividends||[]).slice(-4), ttm=last4.reduce((a,x)=>a+(x.amount||0),0), y=r.last&&ttm?ttm/r.last:null;
  const divs=yrs.length?`<div class="kf" style="margin-top:0"><div><div class="lbl">Yield (last 4 payments)</div><div class="v">${y!=null?pc(y,2):"–"}</div><div class="ks">${money(ttm)} a share</div></div><div><div class="lbl">5-year dividend growth</div><div class="v ${cls(cagr)}">${cagr!=null?pct(cagr,1)+" a year":"–"}</div></div><div><div class="lbl">Last paid</div><div class="v">${last4.length?money(last4[last4.length-1].amount):"–"}</div><div class="ks">${last4.length?dayLabel(last4[last4.length-1].date):""}</div></div></div>
    ${barChart(yrs.map(x=>x.year===thisYear?x.year+"*":String(x.year)),[{name:"Dividends per share",values:yrs.map(x=>x.total),color:C1}],{fmt:v=>"$"+v.toFixed(2),h:150,note:"* this year so far"})}`:`<p class="hint">${isEtf(sel)?"No distributions on record.":"This company doesn't pay a dividend."}</p>`;
  const sp=d.splits||[];
  const fl=(d.filings||[]).filter(f=>/^(10-K|10-Q|8-K|DEF 14A|S-1|S-3|S-4|424B|20-F|6-K|SC 13D)/.test(f.type||"")).slice(0,16), FT={"10-K":"Annual report","10-Q":"Quarterly report","8-K":"Major event","DEF 14A":"Proxy","S-1":"Registration","4":"Insider trade","SC 13G":"Large holder","SC 13G/A":"Large holder"};
  const fT=fl.length?`<ul class="flist">${fl.map(f=>{ const u=safeUrl(f.url); return `<li><span class="ks">${f.date?new Date(f.date+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"}):""}</span><span class="chip">${esc(f.type||"")}</span><span>${u?`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(f.title||FT[f.type]||"Filing")}</a>`:esc(f.title||"")}</span></li>`; }).join("")}</ul>`:`<p class="hint">No filings listed.</p>`;
  return `<div class="dr-sec" style="margin-top:0"><h4>${isEtf(sel)?"Distributions":"Dividends"}</h4>${divs}</div>
    ${sp.length?`<div class="dr-sec"><h4>Stock splits</h4><p class="hint" style="margin:0">${sp.slice(-6).map(s=>`${s.ratio>=1?s.ratio+"-for-1":"1-for-"+Math.round(1/s.ratio)} on ${new Date(s.date+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",year:"numeric",timeZone:"UTC"})}`).join(" · ")}</p></div>`:""}
    ${isEtf(sel)?"":`<div class="dr-sec"><h4>SEC filings</h4>${fT}</div>`}`;
}

/* ---------- ETF holdings ---------- */
const SECT_NAMES={technology:"Technology",healthcare:"Health care",financial_services:"Financials",consumer_cyclical:"Consumer discretionary",communication_services:"Communication",industrials:"Industrials",consumer_defensive:"Consumer staples",energy:"Energy",basic_materials:"Materials",realestate:"Real estate",utilities:"Utilities"};
function paneEtf(d){
  const H=d.holdings||[], S=Object.entries(d.sectors||{}).filter(([k,v])=>v>0.001).sort((a,b)=>b[1]-a[1]), mx=Math.max(...H.map(h=>h.w||0),...S.map(s=>s[1]),0.01);
  const ops=d.operations||{}, er=ops["Annual Report Expense Ratio"], tna=ops["Total Net Assets"], to=ops["Annual Holdings Turnover"], top=H.reduce((a,h)=>a+(h.w||0),0);
  return `<div class="kf" style="margin-top:0"><div><div class="lbl">Expense ratio</div><div class="v">${er?.fund!=null?pc(er.fund,2):"–"}</div><div class="ks">${er?.category!=null?`category average ${pc(er.category,2)}`:""}</div></div><div><div class="lbl">Fund size</div><div class="v">${tna?.fund!=null?usdB(tna.fund*(tna.fund<1e7?1e6:1)):"–"}</div><div class="ks">${esc(d.overview?.family||"")}</div></div><div><div class="lbl">Turnover</div><div class="v">${to?.fund!=null?pc(to.fund,0):"–"}</div><div class="ks">${esc(d.overview?.categoryName||"")}</div></div></div>
    ${H.length?`<div class="dr-sec"><h4>Top ${H.length} holdings · ${pc(top,0)} of the fund</h4><div class="ibars">${H.map(h=>`<button class="ibar" data-sel="${esc(h.t.replace(".","-"))}"><span><b class="mono">${esc(h.t)}</b> ${esc(trunc(h.n||"",30))}</span><i style="width:${((h.w||0)/mx*100).toFixed(1)}%"></i><b class="num">${pc(h.w,1)}</b></button>`).join("")}</div></div>`:""}
    ${S.length?`<div class="dr-sec"><h4>Sectors</h4><div class="ibars">${S.map(([k,v])=>`<div class="ibar"><span>${SECT_NAMES[k]||k}</span><i style="width:${(v/S[0][1]*100).toFixed(1)}%"></i><b class="num">${pc(v,1)}</b></div>`).join("")}</div></div>`:""}
    ${d.description?`<div class="dr-sec"><h4>Strategy</h4><p class="about open" style="margin:0">${esc(d.description)}</p></div>`:""}`;
}

/* ---------- What stands out (Overview insights) ---------- */
function renderInsights(){
  const el=$("#drIns"); if(!el) return;
  const r=stockRow(sel); if(!r) return;
  const items=stockInsights(r);
  el.innerHTML=items.length?insightList(items.slice(0,7)):`<div class="sk" style="height:90px"></div>`;
}
function stockInsights(r){
  const t=r.t, out=[], info=detailCache[t]?.info||{}, A=xpeek("analysts",{t})?.data, O=xpeek("ownership",{t})?.data, OP=xpeek("options",{t})?.data, F=xpeek("financials",{t})?.data, E=xpeek("etf",{t})?.data;
  const fundName=r.bench||"SPY";
  // momentum vs the fund
  const r1=r.rets?.["1M"], ex=r.ex?.["3M"];
  if(r1!=null&&r.ex?.["1M"]!=null&&Math.abs(r.ex["1M"])>0.03){ const a=r.ex["1M"]>0, same=ex!=null&&(ex>0)===a;
    out.push({tone:cls(r.ex["1M"]),html:`<b>${a?"Outrunning":"Lagging"} ${esc(fundName)}:</b> ${pct(r1,1)} over the past month, ${pc(Math.abs(r.ex["1M"]),1)} ${a?"ahead of":"behind"} it.${ex!=null?` ${same?`Over 3 months it's ${pc(Math.abs(ex),0)} ${ex>0?"ahead":"behind"} too.`:(Math.abs(ex)<0.005?`Over 3 months it's level with it.`:`Over 3 months it's still ${pc(Math.abs(ex),0)} ${ex>0?"ahead":"behind"}.`)}`:""}`}); }
  if(r.offHi!=null&&r.offHi>-0.02) out.push({tone:"up",html:`<b>At a 52-week high</b> (${money(r.hi)}).`});
  else if(r.lo&&r.last<=r.lo*1.03) out.push({tone:"down",html:`<b>Near its 52-week low</b> of ${money(r.lo)}, ${pct(r.offHi,0).replace("+","")} below the high.`});
  else if(r.vs200!=null&&r.vs50!=null&&Math.sign(r.vs50)!==Math.sign(r.vs200)) out.push({tone:"",html:`<b>Trend is turning:</b> ${r.vs50>0?"above":"below"} its 50-day average but ${r.vs200>0?"above":"below"} the 200-day.`});
  if(E){ const ops=E.operations||{}, er=ops["Annual Report Expense Ratio"]; if(er?.fund!=null&&er?.category!=null) out.push({tone:er.fund<er.category?"up":"",html:`<b>Costs ${pc(er.fund,2)} a year</b>, ${er.fund<er.category?"cheaper":"pricier"} than the ${pc(er.category,2)} category average.`,tab:"holdings",tabLabel:"Holdings"});
    const top=(E.holdings||[]).reduce((a,h)=>a+(h.w||0),0); if(top) out.push({tone:"",html:`<b>${top>0.5?"Concentrated":"Spread out"}:</b> the top ${E.holdings.length} holdings are ${pc(top,0)} of the fund, led by ${E.holdings.slice(0,3).map(h=>esc(h.t)).join(", ")}.`,tab:"holdings",tabLabel:"Holdings"}); }
  // earnings: options-implied vs history
  const nextE=_nextEarn(t,info);
  if(OP?.earnings?.move!=null){ const hist=typicalEarningsMove(t); out.push({tone:"",html:`<b>Earnings ${dayLabel(OP.earnings.earningsDate)==="Today"?"today":dayLabel(OP.earnings.earningsDate)}:</b> option prices imply a ±${pc(OP.earnings.move,1)} swing${hist!=null?` versus a typical ±${pc(hist,1)} after past reports`:""}.`,tab:"options",tabLabel:"Options"}); }
  else if(nextE&&nextE.days>=0&&nextE.days<=21) out.push({tone:"",html:`<b>Reports earnings ${nextE.days===0?"today":nextE.days===1?"tomorrow":"in "+nextE.days+" days"}.</b>`});
  // estimates moving
  const yr=A?.eps_trend?.["0y"], nx=A?.eps_trend?.["+1y"];
  if(yr?.current!=null&&yr["90daysAgo"]){ const c=yr.current/yr["90daysAgo"]-1; if(Math.abs(c)>=0.02){ const rv=A.eps_revisions?.["0y"]||{};
    out.push({tone:cls(c),html:`<b>Estimates ${c>0?"rising":"falling"}:</b> analysts ${c>0?"raised":"cut"} this year's earnings-per-share forecast ${pc(Math.abs(c),1)} in 90 days${rv.upLast30days!=null?` (${rv.upLast30days} up, ${rv.downLast30days||0} down in the last month)`:""}.`,tab:"analysts",tabLabel:"Analysts"}); } }
  else if(nx?.current!=null&&nx["90daysAgo"]){ const c=nx.current/nx["90daysAgo"]-1; if(Math.abs(c)>=0.02) out.push({tone:cls(c),html:`<b>Next year's estimates ${c>0?"rising":"falling"}</b> (${pct(c,1)} in 90 days).`,tab:"analysts",tabLabel:"Analysts"}); }
  // rating changes
  const recent=(A?.changes||[]).filter(c=>c.date>=shiftDays(nyToday(),-90));
  const up=recent.filter(c=>/up/i.test(c.action)).length, dn=recent.filter(c=>/down/i.test(c.action)).length;
  if(up+dn>0) out.push({tone:up>dn?"up":dn>up?"down":"",html:`<b>${up} upgrade${up===1?"":"s"} and ${dn} downgrade${dn===1?"":"s"}</b> in the last 90 days${(()=>{ const l=recent.find(c=>/up|down/i.test(c.action)); return l?`; latest: ${esc(l.firm)} ${/up/i.test(l.action)?"upgraded":"downgraded"} it to ${esc(l.to||"")}${l.pt?` with a ${money(l.pt)} target`:""}`:""; })()}.`,tab:"analysts",tabLabel:"Analysts"});
  if(info.targetMeanPrice&&r.last){ const u=info.targetMeanPrice/r.last-1; if(Math.abs(u)>0.15) out.push({tone:cls(u),html:`<b>Analysts see ${u>0?"room to run":"downside"}:</b> the average target of ${money(info.targetMeanPrice)} is ${pct(u,0)} from here.`,tab:"analysts",tabLabel:"Analysts"}); }
  // fundamentals trend
  if(F){ const q=finSeries(F,"quarterly"), li=q.incOk.lastIndexOf(true), pi=li>0?q.incOk.lastIndexOf(true,li-1):-1;
    const g=li>=0?yoyAt(q.T,q.rev,li):null, g0=pi>=0?yoyAt(q.T,q.rev,pi):null;
    if(g!=null){
      out.push({tone:cls(g),html:`<b>Revenue ${g>=0?"up":"down"} ${pc(Math.abs(g),0)}:</b> last quarter vs a year earlier${g0!=null?`, ${g>g0+0.02?"accelerating from":g<g0-0.02?"slowing from":"steady with"} ${pct(g0,0)}`:""}.`,tab:"financials",tabLabel:"Financials"}); }
    else if(info.revenueGrowth!=null) out.push({tone:cls(info.revenueGrowth),html:`<b>Revenue ${info.revenueGrowth>=0?"up":"down"} ${pc(Math.abs(info.revenueGrowth),0)}</b> from a year earlier.`,tab:"financials",tabLabel:"Financials"}); }
  // insiders
  if(O){ const tx=O.insiders||[], b=tx.filter(x=>x.kind==="buy"), s=tx.filter(x=>x.kind==="sell"), bv=b.reduce((a,x)=>a+(x.value||0),0), sv=s.reduce((a,x)=>a+(x.value||0),0);
    if(b.length>=2&&bv>sv*0.2) out.push({tone:"up",html:`<b>Insiders are buying:</b> ${b.length} open-market purchases worth ${usdB(bv)} in the past year.`,tab:"ownership",tabLabel:"Ownership"});
    else if(sv>5e6) out.push({tone:"",html:`<b>Insiders sold ${usdB(sv)}</b> over the past year across ${s.length} sales${b.length?` and bought ${usdB(bv)}`:", with no purchases"}.`,tab:"ownership",tabLabel:"Ownership"}); }
  // options mood
  if(OP?.pcVolume!=null&&(OP.pcVolume>1.3||OP.pcVolume<0.5)&&(OP.volume?.calls+OP.volume?.puts)>5000) out.push({tone:OP.pcVolume>1.3?"down":"up",html:`<b>Options traders lean ${OP.pcVolume>1.3?"defensive":"bullish"}:</b> ${OP.pcVolume.toFixed(2)} puts traded for every call${OP.unusual?.length?`, with ${OP.unusual.length} unusually busy contracts`:""}.`,tab:"options",tabLabel:"Options"});
  // short interest and valuation
  if(info.shortPercentOfFloat>0.08) out.push({tone:"down",html:`<b>Heavily shorted:</b> ${pc(info.shortPercentOfFloat,1)} of the float is sold short.`});
  if(info.forwardPE&&info.trailingPE&&info.forwardPE<info.trailingPE*0.75) out.push({tone:"up",html:`<b>Profits expected to jump:</b> the P/E falls from ${mult(info.trailingPE)} on past earnings to ${mult(info.forwardPE)} on next year's estimates.`});
  return out;
}
function _nextEarn(t,info){
  const e=EARN[t]; let d=e&&e.reported==null?e.date:null;
  if(!d){ const ts=earnTs(info); if(ts) d=new Date(ts*1000).toLocaleDateString("en-CA",{timeZone:"America/New_York"}); }
  if(!d) return null; const days=Math.round((new Date(d+"T12:00:00Z")-new Date(nyToday()+"T12:00:00Z"))/864e5); return {date:d,days};
}
