/* OpenTicker: the Levels page. Support and resistance for the S&P 500, VXX, the Nasdaq-100 and QQQ across the top, and
   one stock of your choice below, as large as the window allows. Levels come from /api/x/levels (key_levels in
   levels.py): swing highs and lows at the bar size you pick, from 5 minutes to quarterly, grouped into zones. The big chart
   can also carry indicators (4 and 13 EMA, VWAP, volume, momentum), worked out here from the same bars. Uses globals from index.html and pages.js. */

const LV_TOP=[["^GSPC","S&P 500","The 500 largest US companies"],["VXX","VXX","Tracks VIX futures: rises when investors get nervous"],["^NDX","Nasdaq-100","The 100 largest Nasdaq companies"],
  ["QQQ","QQQ","The fund that tracks the Nasdaq-100: what most people buy and sell to trade it"]];
/* bar sizes: [key, label, short label for phones, what the levels cover] (the server's LEVEL_BARS in yahoo_extra.py) */
const LV_IV=[["5m","5 min","5m","the past five sessions"],["10m","10 min","10m","the past five sessions"],["15m","15 min","15m","the past month"],["1h","1 hour","1h","the past six months"],
  ["1d","Daily","D","the past year"],["1wk","Weekly","W","the past ten years"],["3mo","Quarterly","Q",null]];
let lvIv=load("lvIv","1d"); if(!LV_IV.some(r=>r[0]===lvIv)) lvIv="1d";
const lvQ=t=>({t,iv:lvIv});
const lvSpan=d=>{ const x=LV_IV.find(x=>x[0]===d.iv)?.[3]; return x?"in "+x:`since ${d.span?.[0]?.slice(0,4)||"the start"}`; };   // "in the past year", "since 1999"
let lvT=load("lvT","")||null, lvHover=null, lvClipN=0;
const lvIdx=t=>t.startsWith("^");
const lvIntra=iv=>iv==="5m"||iv==="10m"||iv==="15m";
/* indicators the big chart can carry: [key, label, what it is, color] */
const LV_IND=[["ema4","4 EMA","Average of the last 4 bars, weighted toward the newest: the quickest read of the short-term push","var(--ema4)"],
  ["ema13","13 EMA","Average of the last 13 bars, weighted toward the newest. When the 4 EMA crosses it, the short-term trend has turned","var(--ema13)"],
  ["vwap","VWAP","The average price paid, weighted by how many shares traded at each price. Intraday it starts fresh each session","var(--vwap)"],
  ["vol","Volume","Shares traded in each bar, and whether that is rising or dropping","var(--ink-3)"],
  ["mom","Momentum","RSI over 14 bars, from 0 to 100: above 70 the run is stretched, below 30 it is washed out","var(--accent)"]];
let lvInd=new Set(String(load("lvInd","")).split(",").filter(k=>LV_IND.some(r=>r[0]===k)));
/* the indicator math, on the bars the chart shows */
function lvEma(c,n){ const k=2/(n+1); let e=null; return c.map((x,i)=>{ e=e==null?x:x*k+e*(1-k); return i<n-1?null:e; }); }
function lvVwap(d){   // intraday it starts again each session; on daily bars and longer it runs from the first bar on the chart
  if(!d.v) return null; const intra=d.d[0].length>10; let pv=0,vv=0,day=null;
  return d.c.map((c,i)=>{ const k=intra?d.d[i].slice(0,10):""; if(k!==day){ day=k; pv=0; vv=0; } const v=d.v[i]||0; pv+=(d.h[i]+d.l[i]+c)/3*v; vv+=v; return vv?pv/vv:null; }); }
function lvRsi(c,n=14){   // Wilder's RSI
  const out=c.map(()=>null); let g=0,l=0;
  for(let i=1;i<c.length;i++){ const ch=c[i]-c[i-1], up=Math.max(ch,0), dn=Math.max(-ch,0);
    if(i<=n){ g+=up/n; l+=dn/n; } else { g=(g*(n-1)+up)/n; l=(l*(n-1)+dn)/n; }
    if(i>=n) out[i]=l?100-100/(1+g/l):100; }
  return out; }
/* volume over the last 5 finished bars against the 20 before them (the latest bar is usually still filling in). Medians, not
   averages: Yahoo's intraday volume has the odd bar many times its neighbours, and one such bar shouldn't decide the answer */
const lvMed=a=>{ const b=[...a].sort((x,y)=>x-y), m=b.length>>1; return b.length%2?b[m]:(b[m-1]+b[m])/2; };
function lvVolTrend(d){ const v=d.v; if(!v||v.length<27) return null;
  const ok=a=>a.filter(x=>x>0), a=lvMed(ok(v.slice(-6,-1))), b=lvMed(ok(v.slice(-26,-6))); if(!(a>0&&b>0)) return null;   // 0 is a bar the server blanked
  const r=a/b-1, px=d.c[d.c.length-2]/d.c[d.c.length-7]-1; return {r,px,k:r>.15?"up":r<-.15?"down":"flat"}; }
function lvIndData(d){ return {ema4:lvEma(d.c,4),ema13:lvEma(d.c,13),vwap:lvVwap(d),rsi:lvRsi(d.c),vt:lvVolTrend(d)}; }
/* the other indexes the Market page's tiles open here: [short name, what it is] */
const LV_NAMES={"^IXIC":["Nasdaq","The Nasdaq Composite: over 3,000 stocks listed on Nasdaq"],"^DJI":["Dow Jones","The Dow Jones Industrial Average: 30 large US companies"],"^RUT":["Russell 2000","2,000 smaller US companies"]};
const lvLabel=t=>LV_TOP.find(x=>x[0]===t)?.[1]||LV_NAMES[t]?.[0]||t;
function lvSym(){ return lvT||recent?.[0]||me?.positions?.[0]?.t||me?.watch?.[0]||"NVDA"; }
function lvPick(t){ if(!t) return; lvT=t; save("lvT",t); lvClose(); renderLevels(); }

/* an index is points, everything else dollars; big numbers drop the cents so a column of levels lines up */
function lvP(t,x){ if(x==null||!isFinite(x)) return "–"; const dp=x>=1000?0:2;
  return (lvIdx(t)?"":"$")+x.toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp}); }
/* bar times come as New York wall-clock strings ("2026-11-05" or "2026-11-05T14:35"); read them as written */
const lvDate=d=>new Date(d.slice(0,10)+"T12:00:00Z"), lvFmt=(d,o)=>lvDate(d).toLocaleDateString("en-US",{...o,timeZone:"UTC"});
function lvClock(d){ const [hh,mm]=d.slice(11,16).split(":").map(Number); return `${hh%12||12}:${String(mm).padStart(2,"0")} ${hh<12?"am":"pm"}`; }
function lvWeek(d){ const x=lvDate(d); x.setUTCDate(x.getUTCDate()-((x.getUTCDay()+6)%7)); return x.toISOString().slice(0,10); }
const lvQuarter=d=>`Q${Math.floor((+d.slice(5,7)-1)/3)+1} ${d.slice(0,4)}`;
function lvDay(d,iv=lvIv){   // when a level was last touched, as briefly as is clear
  if(iv==="3mo") return lvQuarter(d);
  if(iv==="1h") return lvFmt(d,{weekday:"short"})+" "+lvFmt(d,{month:"short",day:"numeric"});
  if(d.length>10) return lvFmt(d,{weekday:"short"})+" "+lvClock(d);
  return lvFmt(d,{month:"short",day:"numeric",...(d.slice(0,4)!==String(new Date().getFullYear())?{year:"numeric"}:{})});
}
function lvWhen(d,iv=lvIv){   // the hover label for one bar
  if(iv==="3mo") return lvQuarter(d);
  if(iv==="1wk") return "Week of "+lvFmt(d,{month:"short",day:"numeric",year:"numeric"});
  return lvFmt(d,{weekday:"short",month:"short",day:"numeric",...(d.length>10?{}:{year:"numeric"})})+(d.length>10?" · "+lvClock(d):"");
}
const lvAway=(p,last)=>{ const r=p/last-1; return `${Math.abs(r*100).toFixed(Math.abs(r)<.1?1:0)}% ${r>=0?"above":"below"}`; };
const LV_STR=["","light","moderate","strong"];

/* the latest price: the live one when OpenTicker streams this ticker, otherwise Yahoo's last daily bar */
function lvLast(t,d){ const F=!lvIdx(t)&&base?.px?.[t]?facts(t):null; return F?.last??d.last; }
function lvPrev(t,d){ const F=!lvIdx(t)&&base?.px?.[t]?facts(t):null; return F?.last&&F.chg!=null?F.last/(1+F.chg):d.prev; }
/* the levels sorted high to low, each marked against the latest price (it can have crossed one since Yahoo's bar) */
function lvLevels(d,last){
  const room=(d.tol||last*.006)/2;
  const L=(d.levels||[]).map(x=>({...x,k:x.p>last+room?"resistance":x.p<last-room?"support":"here"})).filter(x=>x.k!=="here"||x.touches>=2).sort((a,b)=>b.p-a.p);
  // R1 and S1 are the nearest on each side, counting outward, the way traders name them
  L.filter(x=>x.k==="resistance").reverse().forEach((x,i)=>x.tag="R"+(i+1));
  L.filter(x=>x.k==="support").forEach((x,i)=>x.tag="S"+(i+1));
  L.filter(x=>x.k==="here").forEach(x=>x.tag="At");
  return L;
}
function lvNearest(L){ return {s:L.filter(x=>x.k==="support")[0],r:L.filter(x=>x.k==="resistance").slice(-1)[0],here:L.find(x=>x.k==="here")}; }
const lvTimes=n=>n===1?"once":n===2?"twice":n+" times";

/* the verdict: one or two words a trader can take in at a glance */
function lvVerdict(t,d,last){
  const {s,r,here}=lvNearest(lvLevels(d,last));
  if(here) return {k:"here",txt:`Testing ${lvP(t,here.p)}`};
  if(!r&&s) return {k:"up",txt:last>=d.hi52.p*.99?"At a new high":"Nothing overhead"};
  if(!s&&r) return {k:"down",txt:last<=d.lo52.p*1.01?"At a new low":"Nothing below"};
  if(!s||!r) return {k:"",txt:"No clear levels"};
  const dS=1-s.p/last, dR=r.p/last-1;
  return dS<dR*.6?{k:"up",txt:"Near support"}:dR<dS*.6?{k:"down",txt:"Near resistance"}:{k:"",txt:"Between levels"};
}
const lvTag=v=>`<span class="lvtag ${v.k}">${esc(v.txt)}</span>`;
const lvPct=(p,last)=>{ const r=(p/last-1)*100; if(Math.abs(r)<.05) return "0.0%"; return (r>=0?"+":"−")+Math.abs(r).toFixed(Math.abs(r)<10?1:0)+"%"; };
/* where the price sits between its nearest support (left) and resistance (right) */
function lvMeter(t,d,last){
  const n=lvNearest(lvLevels(d,last)), P=x=>lvP(t,x), s=n.s||n.here, r=n.r||(n.s?n.here:null);   // a level it's sitting on stands in for a missing side
  const pos=s&&r?Math.max(0,Math.min(1,(last-s.p)/(r.p-s.p))):s?1:r?0:.5;
  const side=(x,k)=>x?`<span class="mx ${k}${x.k==="here"?" at":""}"><span class="mtop"><span class="mt">${x.tag}</span><b class="num">${P(x.p)}</b></span><span class="num md">${lvPct(x.p,last)}</span></span>`
    :`<span class="mx ${k} none">${k==="sup"?"Nothing below":"Nothing above"}</span>`;
  const al=s&&r?`${lvP(t,last)}: ${lvAway(s.p,last)} support at ${P(s.p)}, ${lvAway(r.p,last)} resistance at ${P(r.p)}`:"";
  return `<div class="lvmeter" role="img" aria-label="${esc(al)}">${side(s,"sup")}<span class="mbar"><i style="left:${(pos*100).toFixed(1)}%"></i></span>${side(r,"res")}</div>`;
}
/* one plain sentence under the verdict: why that level matters */
function lvRead(t,d,last){
  const L=lvLevels(d,last), {s,r,here}=lvNearest(L), N=lvIdx(t)?`The ${lvLabel(t)}`:t, P=x=>lvP(t,x);
  const ma=["50","200"].map(k=>[k,d.ma?.[k]?.slice(-1)[0]]).filter(([k,v])=>v&&Math.abs(last/v-1)<.012)[0];
  const nearMa=ma?` Also near its ${ma[0]}-day average (${P(ma[1])}).`:"";
  if(here) return `It has turned at ${P(here.p)} ${lvTimes(here.touches)} ${lvSpan(d)}. A close clearly above or below often sets the next move.${nearMa}`;
  if(!r&&s) return `${N} is at or near its highest price ${lvSpan(d)}, so no sellers wait above. First support is ${P(s.p)}.${nearMa}`;
  if(!s&&r) return `${N} is at or near its lowest price ${lvSpan(d)}, so no buyers wait below. First resistance is ${P(r.p)}.${nearMa}`;
  if(!s||!r) return `Not enough swings ${lvSpan(d)} to mark clear levels.`;
  const dS=1-s.p/last, dR=r.p/last-1;
  const why=dR<dS*.6?`Sellers stopped it at ${P(r.p)} ${lvTimes(r.touches)}${r.flip?", and it has been support too":""}.`
    :dS<dR*.6?`Buyers stepped in at ${P(s.p)} ${lvTimes(s.touches)}${s.flip?", and it has capped the price too":""}.`
    :`Room to move ${(dS*100).toFixed(1)}% down or ${(dR*100).toFixed(1)}% up before the next level.`;
  return why+nearMa;
}

/* ---------- the chart: price, level zones and their labels, the latest price, and on the big chart the averages ---------- */
function lvChart(t,d,{w,h,last,big,ind}){
  const N=d.c.length, O=d.o, Hh=d.h, Lo=d.l, C=d.c, D=d.d;
  const L=lvLevels(d,last), near=lvNearest(L);
  const ph=innerWidth<=600, left=big?(ph?36:46):8, R=big?(ph?92:104):64, T=big?12:8, B=big?24:8, PW=w-left-R;
  // volume and momentum get their own strips under the price, sharing its time axis
  const I=ind&&ind.size?lvIndData(d):null, gap=12, VH=I&&ind.has("vol")&&d.v?(ph?44:64):0, MH=I&&ind.has("mom")?(ph?54:76):0;
  const PH=h-T-B-(VH?VH+gap:0)-(MH?MH+gap:0);
  const step=PW/N, X=i=>left+step*(i+.5);
  let lo=Math.min(...Lo,last), hi=Math.max(...Hh,last);
  // the nearest level on each side always shows (if it's not absurdly far); others only when they fit the window
  [near.s,near.r].forEach(x=>{ if(x&&Math.abs(x.p/last-1)<.18){ lo=Math.min(lo,x.lo); hi=Math.max(hi,x.hi); } });
  // years of weekly or quarterly bars can span a hundredfold move: a log scale keeps the early years readable
  const logY=lo>0&&hi/lo>4;
  if(logY){ const k=Math.pow(hi/lo,.04); lo/=k; hi*=k; } else { const pad=(hi-lo)*.06||hi*.01; lo-=pad; hi+=pad; }
  const Y=logY?v=>T+PH*(1-Math.log(Math.max(v,lo)/lo)/Math.log(hi/lo)):v=>T+PH*(1-(v-lo)/(hi-lo)), inView=x=>x.p>=lo&&x.p<=hi;
  const MA=big?[["50","var(--accent)"],["200","var(--warn)"]].map(([k,col])=>({k,col,a:(d.ma?.[k]||[]).slice(-N)})).filter(m=>m.a.some(v=>v!=null)):[];
  let s=`<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(lvLabel(t))} price with support and resistance levels, ${LV_IV.find(x=>x[0]===d.iv)?.[1]||""} bars">`;
  const ticks=logY?(()=>{ const out=[]; let lastY=1e9; for(let e=Math.floor(Math.log10(lo));e<=Math.ceil(Math.log10(hi));e++) for(const m of [1,2,5]){ const v=m*10**e; if(v<lo||v>hi) continue; if(lastY-Y(v)>=26){ out.push(v); lastY=Y(v); } } return out; })()
    :niceTicks(lo,hi,Math.max(3,Math.round(PH/70)));
  if(big) ticks.forEach(v=>{ s+=`<line x1="${left}" x2="${w-R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--grid)"/><text x="${left-8}" y="${(Y(v)+4).toFixed(1)}" font-size="11" text-anchor="end" class="num" fill="var(--ink-3)">${v>=1000?v.toLocaleString("en-US",{maximumFractionDigits:0}):v<1?String(+v.toFixed(2)):v.toFixed(v<10&&!logY?2:0)}</text>`; });
  // zones under the price, so the bars read on top of them
  const col=x=>x.k==="resistance"?"var(--down)":x.k==="support"?"var(--up)":"var(--accent)";
  // the nearest level on each side is drawn strongest; the rest step back so the eye goes to what matters now
  const isNear=x=>x===near.s||x===near.r||x===near.here;
  L.filter(inView).forEach(x=>{ const y1=Y(Math.min(hi,x.hi)), y2=Y(Math.max(lo,x.lo)), zh=Math.max(big?4:3,y2-y1), yc=(y1+y2)/2, n=isNear(x);
    s+=`<rect x="${left}" y="${(yc-zh/2).toFixed(1)}" width="${PW}" height="${zh.toFixed(1)}" fill="${col(x)}" opacity="${(n?.1+.04*x.strength:.04+.02*x.strength).toFixed(2)}"/>`;
    s+=`<line x1="${left}" x2="${w-R}" y1="${Y(x.p).toFixed(1)}" y2="${Y(x.p).toFixed(1)}" stroke="${col(x)}" stroke-width="${n?1.6:1}" ${n||x.strength>=2?"":`stroke-dasharray="4 4"`} opacity="${n?.95:.45}"/>`; });
  const clip="lvClip"+(++lvClipN);   // one per chart: the drawer's Levels tab can sit over the Levels page
  if(MA.length||I) s+=`<clipPath id="${clip}"><rect x="${left}" y="${T}" width="${PW}" height="${PH}"/></clipPath>`;   // an average far from the price runs off the chart, not over the axis
  MA.forEach(m=>{ let p=""; m.a.forEach((v,i)=>{ if(v==null) return; p+=(p?"L":"M")+X(i).toFixed(1)+","+Y(v).toFixed(1); }); s+=`<path d="${p}" fill="none" stroke="${m.col}" stroke-width="1.3" opacity=".8" stroke-dasharray="5 3" clip-path="url(#${clip})"/>`; });
  if(big&&step>=1.5){ const bw=Math.max(1,Math.min(9,step*.62));
    C.forEach((c,i)=>{ const up=c>=O[i], cl=up?"var(--up)":"var(--down)", x=X(i), yo=Y(O[i]), yc=Y(c);
      s+=`<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${Y(Hh[i]).toFixed(1)}" y2="${Y(Lo[i]).toFixed(1)}" stroke="${cl}" stroke-width="1"/><rect x="${(x-bw/2).toFixed(1)}" y="${Math.min(yo,yc).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1,Math.abs(yc-yo)).toFixed(1)}" fill="${cl}" rx="${bw>4?1:0}"/>`; }); }
  else{ const p=C.map((c,i)=>(i?"L":"M")+X(i).toFixed(1)+","+Y(c).toFixed(1)).join(""); s+=`<path d="${p}" fill="none" stroke="var(--ink)" stroke-width="${big?1.6:1.4}" stroke-linejoin="round"/>`; }
  // the indicator lines over the price; VWAP breaks at each new session rather than joining the close to the next open
  const line=(a,col,wd,dash,brk)=>{ if(!a) return; let p="", pk=null; a.forEach((v,i)=>{ const k=brk?D[i].slice(0,10):""; if(v==null){ pk=null; return; } p+=(pk===k?"L":"M")+X(i).toFixed(1)+","+Y(v).toFixed(1); pk=k; });
    s+=`<path d="${p}" fill="none" stroke="${col}" stroke-width="${wd}" ${dash?`stroke-dasharray="${dash}"`:""} stroke-linejoin="round" clip-path="url(#${clip})"/>`; };
  if(I){ if(ind.has("vwap")) line(I.vwap,"var(--vwap)",1.6,"6 3",D[0].length>10);
    if(ind.has("ema13")) line(I.ema13,"var(--ema13)",1.5); if(ind.has("ema4")) line(I.ema4,"var(--ema4)",1.5); }
  // the strips: volume bars colored by the bar's direction, then momentum with its 30 and 70 lines
  let y0=T+PH+gap; const bw0=Math.max(1,Math.min(9,step*.62));
  if(VH){ const sv=d.v.filter(x=>x>0).sort((a,b)=>a-b), mx=sv[Math.floor(sv.length*.95)]||sv[sv.length-1]||1, tr=I.vt;   // scaled to the 95th percentile so one huge bar doesn't flatten the rest
    s+=`<text x="${left+4}" y="${y0+11}" font-size="11" font-weight="600" fill="var(--ink-3)">Volume${tr?` · ${tr.k==="up"?"rising":tr.k==="down"?"dropping":"steady"}`:""}</text>`;
    d.v.forEach((v,i)=>{ if(!v) return; const bh=Math.max(1,(VH-14)*Math.min(1,v/mx)); s+=`<rect x="${(X(i)-bw0/2).toFixed(1)}" y="${(y0+VH-bh).toFixed(1)}" width="${bw0.toFixed(1)}" height="${bh.toFixed(1)}" fill="${C[i]>=O[i]?"var(--up)":"var(--down)"}" opacity=".45"/>`; });
    s+=`<line x1="${left}" x2="${w-R}" y1="${y0+VH}" y2="${y0+VH}" stroke="var(--rule)"/>`;
    y0+=VH+gap; }
  if(MH){ const YM=v=>y0+MH*(1-v/100), r=I.rsi, rl=r[r.length-1];
    s+=`<rect x="${left}" y="${YM(70).toFixed(1)}" width="${PW}" height="${(YM(30)-YM(70)).toFixed(1)}" fill="var(--grid)" opacity=".7"/>`;
    [30,70].forEach(v=>{ s+=`<line x1="${left}" x2="${w-R}" y1="${YM(v).toFixed(1)}" y2="${YM(v).toFixed(1)}" stroke="var(--ink-3)" stroke-dasharray="2 3" opacity=".6"/><text x="${left-8}" y="${(YM(v)+4).toFixed(1)}" font-size="10.5" text-anchor="end" class="num" fill="var(--ink-3)">${v}</text>`; });
    s+=`<text x="${left+4}" y="${y0+11}" font-size="11" font-weight="600" fill="var(--ink-3)">Momentum (RSI 14)</text>`;
    let p=""; r.forEach((v,i)=>{ if(v==null) return; p+=(p?"L":"M")+X(i).toFixed(1)+","+YM(v).toFixed(1); }); s+=`<path d="${p}" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round"/>`;
    if(rl!=null){ const fs=11; s+=`<rect x="${w-R+6}" y="${(YM(rl)-8.5).toFixed(1)}" width="34" height="17" rx="8.5" fill="var(--panel)" stroke="var(--accent)"/><text x="${w-R+23}" y="${(YM(rl)+fs*.36).toFixed(1)}" font-size="${fs}" font-weight="650" text-anchor="middle" class="num" fill="var(--accent)">${rl.toFixed(0)}</text>`; } }
  // the latest price
  const yl=Y(last); s+=`<line x1="${left}" x2="${w-R}" y1="${yl.toFixed(1)}" y2="${yl.toFixed(1)}" stroke="var(--ink-2)" stroke-dasharray="2 3" opacity=".7"/>`;
  // labels on the right, nudged apart so they never sit on top of each other; the latest price wins its spot
  // a small chart (and the phone's) labels only the nearest level on each side; the list below has the rest
  const fs=big?11.5:10.5, lh=big?21:17, labelled=big&&!ph?L.filter(inView):[near.r,near.s,near.here].filter(x=>x&&inView(x));
  const items=[{y:yl,txt:lvP(t,last),now:true},...labelled.map(x=>({y:Y(x.p),txt:lvP(t,x.p),tag:big?x.tag:"",n:isNear(x),x}))].sort((a,b)=>a.y-b.y);
  const placeLabels=a=>{ const top=T+lh/2-2, bot=T+PH-lh/2+2;   // push down past any overlap, then back up from the bottom edge
    for(let j=1;j<a.length;j++) a[j].y=Math.max(a[j].y,a[j-1].y+lh);
    for(let j=a.length-1;j>=0;j--) a[j].y=Math.min(a[j].y,j===a.length-1?bot:a[j+1].y-lh);
    a.forEach(o=>o.y=Math.max(top,o.y)); };
  placeLabels(items);
  items.forEach(o=>{ const tl=o.tag?o.tag.length*fs*.62+5:0, tw=o.txt.length*fs*.6+14+tl, x0=w-R+6, c=o.now?"var(--ink)":col(o.x), op=o.now||o.n||!big?1:.6;
    s+=o.now?`<rect x="${x0}" y="${(o.y-lh/2+2).toFixed(1)}" width="${tw.toFixed(1)}" height="${lh-4}" rx="${(lh-4)/2}" fill="var(--ink)"/><text x="${(x0+7).toFixed(1)}" y="${(o.y+fs*.36).toFixed(1)}" font-size="${fs}" font-weight="650" class="num" fill="var(--panel)">${o.txt}</text>`
      :`<g opacity="${op}"><rect x="${x0}" y="${(o.y-lh/2+2).toFixed(1)}" width="${tw.toFixed(1)}" height="${lh-4}" rx="${(lh-4)/2}" fill="${o.n&&big?`color-mix(in srgb,${c} 14%,var(--panel))`:"var(--panel)"}" stroke="${c}" stroke-opacity="${o.n?.9:.5}"/><text x="${(x0+7).toFixed(1)}" y="${(o.y+fs*.36).toFixed(1)}" font-size="${fs}" font-weight="600" class="num" fill="${c}">${o.tag?`<tspan font-weight="750">${o.tag}</tspan><tspan dx="5" fill="var(--ink)" font-weight="${o.n?650:500}">${o.txt}</tspan>`:o.txt}</text></g>`; });
  if(big){ // time marks along the bottom: days for intraday bars, weeks for hourly, months, years
    const iv=d.iv, key=dd=>lvIntra(iv)?dd.slice(0,10):iv==="1h"?lvWeek(dd):iv==="1d"?dd.slice(0,7):iv==="1wk"?dd.slice(0,4):dd.slice(0,3);
    const lab=dd=>lvIntra(iv)?lvFmt(dd,{weekday:"short"})+" "+(+dd.slice(8,10)):iv==="1h"?lvFmt(dd,{month:"short",day:"numeric"})
      :iv==="1d"?lvFmt(dd,{month:"short"})+(dd.slice(5,7)==="01"?" ’"+dd.slice(2,4):""):iv==="1wk"?dd.slice(0,4):dd.slice(0,3)+"0s";
    const marks=[]; let prevK=null; D.forEach((dd,i)=>{ const k=key(dd); if(prevK!==null&&k!==prevK) marks.push(i); prevK=k; });
    let lastX=-1e9; marks.forEach(i=>{ if(X(i)-lastX<56||X(i)>w-R-16) return; lastX=X(i);
      s+=`<line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${T}" y2="${h-B}" stroke="var(--grid)" opacity=".7"/><text x="${X(i).toFixed(1)}" y="${h-6}" font-size="11" text-anchor="middle" fill="var(--ink-3)">${lab(D[i])}</text>`; });
    s+=`<line id="lvX" x1="0" x2="0" y1="${T}" y2="${h-B}" stroke="var(--ink-3)" stroke-width="1" visibility="hidden"/>`;
    lvHover={t,iv:d.iv,left,step,N,T,B,h,O,Hh,Lo,C,D,V:d.v,ind:I?ind:null,A:I};
  }
  return s+"</svg>";
}

/* ---------- the indicator readout: one short line for each indicator that's on ---------- */
function lvIndRead(t,d,last){
  if(!lvInd.size) return "";
  const I=lvIndData(d), P=x=>lvP(t,x), at=a=>a?.[a.length-1], out=[];
  const side=(v,lab)=>{ const r=last/v-1; return `Price ${Math.abs(r)<.0005?"is at":`is ${Math.abs(r*100).toFixed(Math.abs(r)<.1?1:0)}% ${r>0?"above":"below"}`} ${lab} (${P(v)})`; };
  const it=(k,cl,txt)=>`<span class="lvri ${cl}"><i style="background:${LV_IND.find(x=>x[0]===k)[3]}"></i>${txt}</span>`;
  const e4=at(I.ema4), e13=at(I.ema13);
  if(lvInd.has("ema4")&&lvInd.has("ema13")&&e4!=null&&e13!=null)
    out.push(it("ema4",e4>=e13?"up":"down",`4 EMA ${e4>=e13?"above":"below"} 13 EMA: the short-term trend is ${e4>=e13?"up":"down"}`));
  else [["ema4",e4,"its 4 EMA"],["ema13",e13,"its 13 EMA"]].forEach(([k,v,lab])=>{ if(lvInd.has(k)&&v!=null) out.push(it(k,cls(last-v),side(v,lab))); });
  if(lvInd.has("vwap")){ const v=at(I.vwap), intra=d.d[0].length>10;
    out.push(v==null?it("vwap","flat","VWAP needs volume, and Yahoo sends none for this index")
      :it("vwap",cls(last-v),side(v,`VWAP, the average paid ${intra?"this session":"since "+lvFmt(d.d[0],{month:"short",day:"numeric",year:"numeric"})}`))); }
  if(lvInd.has("vol")){ const vt=I.vt;
    out.push(!d.v?it("vol","flat","No volume from Yahoo for this index"):!vt?it("vol","flat","Not enough bars to tell if volume is changing")
      :it("vol",vt.k==="flat"?"flat":vt.k,`Volume ${vt.k==="up"?"rising":vt.k==="down"?"dropping":"steady"}: a typical bar of the last 5 traded ${Math.abs(vt.r*100).toFixed(0)}% ${vt.r>=0?"more":"less"} than one of the 20 before`
        +(vt.k!=="flat"&&Math.abs(vt.px)>=.002?`, while the price ${vt.px>0?"rose":"fell"}${vt.k==="up"?", so the move has conviction":", so the move is running out of interest"}`:""))); }
  if(lvInd.has("mom")){ const r=at(I.rsi);
    if(r!=null) out.push(it("mom",r>=50?"up":"down",`Momentum ${r.toFixed(0)}: ${r>=70?"stretched, the run may need a rest":r<=30?"washed out, sellers may be tiring":r>=50?"leaning up":"leaning down"}`)); }
  return out.join("");
}
function lvKey(d){
  const k=[`<span><i class="k res"></i>Resistance (R1 nearest)</span>`,`<span><i class="k sup"></i>Support (S1 nearest)</span>`];
  if(lvIv==="1d") k.push(`<span><i class="k m50"></i>50-day average</span>`,`<span><i class="k m200"></i>200-day average</span>`);
  LV_IND.forEach(([x,lab,,col])=>{ if(lvInd.has(x)&&x!=="vol"&&x!=="mom") k.push(`<span><i class="k ind" style="--c:${col}"></i>${lab}</span>`); });
  return k.join("");
}

/* ---------- the side list: every level from the top down, with the latest price in its place ---------- */
function lvLadder(t,d,last,prev){
  const L=lvLevels(d,last), near=lvNearest(L), rows=L.map(x=>({p:x.p,x}));
  [["50","50-day"],["200","200-day"]].forEach(([k,lab])=>{ const v=d.ma?.[k]?.slice(-1)[0]; if(v) rows.push({p:v,ma:k,lab}); });
  rows.push({p:last,now:true}); rows.sort((a,b)=>b.p-a.p||(a.now?-1:1));
  const chg=prev?last/prev-1:null;
  return `<ol class="lvlad">${rows.map(r=>{
    if(r.now) return `<li class="now"><span class="lt">Now</span><span class="lp num">${lvP(t,last)}</span><span class="ld num ${cls(chg)}">${chg==null?"":pct(chg)+" today"}</span></li>`;
    if(r.ma) return `<li class="ma ma${r.ma}" title="${r.lab} average, a line many traders watch"><span class="lt"><i aria-hidden="true"></i>${r.lab}</span><span class="lp num">${lvP(t,r.p)}</span><span class="ld num">${lvPct(r.p,last)}</span></li>`;
    const x=r.x, n=x===near.s||x===near.r||x===near.here, kind=x.k==="here"?"At this level":x.k==="resistance"?"Resistance":"Support";
    const meta=`Turned here ${lvTimes(x.touches)}, last ${lvDay(x.last,d.iv)}${x.flip?". Has been both support and resistance":""}`;
    return `<li class="${x.k}${n?" near":""}" title="${kind}, ${LV_STR[x.strength]} level. ${esc(meta)}"><span class="lt">${x.tag}</span><span class="lp num">${lvP(t,x.p)}</span><span class="ld num">${x.k==="here"?"right here":lvPct(x.p,last)}</span><span class="str" aria-label="${LV_STR[x.strength]} level">${[1,2,3].map(j=>`<i class="${j<=x.strength?"on":""}"></i>`).join("")}</span>${n?`<span class="lm">${esc(meta)}</span>`:""}</li>`; }).join("")}</ol>`;
}

/* ---------- the page ---------- */
function renderLevels(){
  if(!$("#lvl")){
    $("#app").innerHTML=`<div id="lvl" class="page">
      <div class="phead"><div><h1 class="ptitle">Levels</h1><p class="hint">Support is where buyers stepped in before, resistance where sellers did. S1 and R1 are the nearest; more dots means a stronger level.</p></div>
        <div class="seg lviv" id="lvRng" role="group" aria-label="Bar size"></div></div>
      <section class="lvtop" id="lvTop" aria-label="Market levels">${LV_TOP.map(([s])=>`<button class="lvcard" data-lv="${esc(s)}" aria-pressed="false">${sk(170)}</button>`).join("")}</section>
      <section class="panel lvmain" id="lvMain">
        <div class="lvhead"><div class="lvwho" id="lvWho"></div>
          <div class="lvfind"><div class="lvsrch">${ic("search",14)}<input id="lvQ" type="search" placeholder="Show another stock…" autocomplete="off" spellcheck="false" aria-label="Show levels for another stock" aria-controls="lvRes"><div class="sres" id="lvRes" role="listbox" hidden></div></div><div class="lvquick" id="lvQuick"></div></div></div>
        <div class="lvsum" id="lvSum"></div>
        <div class="lvind"><span class="lbl" id="lvIndL">Add to chart</span><div class="seg sm" id="lvIndB" role="group" aria-labelledby="lvIndL"></div></div>
        <div class="lvrd" id="lvRd" aria-live="polite"></div>
        <div class="lvbody"><div><div class="lvchart" id="lvChart">${sk(420)}</div>
          <div class="lvkey" id="lvKey"></div></div>
          <div class="lvside"><div class="lbl">All levels</div><div id="lvLad">${sk(300)}</div></div></div>
      </section></div>`;
    lvWire();
  }
  patch($("#lvRng"),LV_IV.map(([k,l,sh])=>`<button data-lvr="${k}" aria-pressed="${k===lvIv}" aria-label="${l} bars"><span class="lg">${l}</span><span class="sh">${sh}</span></button>`).join(""));
  patch($("#lvIndB"),LV_IND.map(([k,l,tip])=>`<button data-lvind="${k}" aria-pressed="${lvInd.has(k)}" title="${esc(tip)}">${l}</button>`).join(""));
  LV_TOP.forEach(([s])=>{ const c=xpeek("levels",lvQ(s)); if(c?.data||c?.error) lvCard(s); else { lvCard(s); const iv=lvIv; xget("levels",lvQ(s)).then(()=>{ if(page==="levels"&&lvIv===iv) lvCard(s); }); } });
  lvMain();
}
function lvCard(s){
  const el=document.querySelector(`.lvcard[data-lv="${CSS.escape(s)}"]`); if(!el) return;
  const c=xpeek("levels",lvQ(s)), t=lvSym(); el.setAttribute("aria-pressed",String(t===s));
  if(!c?.data){ patch(el,c?.error?`<div class="lvch"><b>${esc(lvLabel(s))}</b></div>${errBox(c.error)}`:sk(170)); return; }
  const d=c.data, last=lvLast(s,d), prev=lvPrev(s,d), chg=prev?last/prev-1:null;
  const w=Math.max(220,Math.round(el.clientWidth-26)), h=innerWidth<=600?96:80;
  el.title=`${LV_TOP.find(x=>x[0]===s)[2]}. Click to show it below`;
  patch(el,`<div class="lvch"><div><b>${esc(lvLabel(s))}</b>${lvTag(lvVerdict(s,d,last))}</div><div class="lvpx"><span class="num">${lvP(s,last)}</span><span class="num ${cls(chg)}">${pct(chg)}</span></div></div>
    <div class="lvmini">${lvChart(s,d,{w,h,last})}</div>${lvMeter(s,d,last)}`);   // in place, so a focused card keeps focus
}
function lvMain(){
  const t=lvSym(), c=xpeek("levels",lvQ(t));
  document.querySelectorAll(".lvcard").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.lv===t)));
  const top=LV_TOP.find(x=>x[0]===t), nm=top?top[2]:LV_NAMES[t]?.[1]||nameOf(t);
  patch($("#lvWho"),`<h2>${esc(lvLabel(t))}</h2><span class="nm">${esc(nm&&nm!==t?nm:c?.data?.name||"")}</span>${lvIdx(t)?"":`<button class="lnk" data-sel="${esc(t)}">Open ${esc(t)} ›</button>`}`);
  const q=[...new Set([...(typeof recent!=="undefined"?recent:[]),...(me?.positions||[]).map(p=>p.t),...(me?.watch||[])])].filter(x=>x!==t).slice(0,5);
  patch($("#lvQuick"),q.map(x=>`<button class="chip" data-lv="${esc(x)}">${esc(x)}</button>`).join(""));
  if(!c?.data){
    if(c?.error){ $("#lvChart").innerHTML=errBox(c.error,"levels",lvQ(t)); $("#lvLad").innerHTML=""; $("#lvSum").innerHTML=""; $("#lvRd").innerHTML=""; return; }
    $("#lvChart").innerHTML=sk(lvHeight()); $("#lvLad").innerHTML=sk(300); $("#lvSum").innerHTML=`<span class="sk" style="display:block;height:44px;grid-column:1/-1"></span>`;
    const iv=lvIv; xget("levels",lvQ(t)).then(()=>{ if(page==="levels"&&lvSym()===t&&lvIv===iv) lvMain(); }); return;
  }
  const d=c.data, last=lvLast(t,d), prev=lvPrev(t,d), box=$("#lvChart");
  patch($("#lvSum"),`<div class="lvv">${lvTag(lvVerdict(t,d,last))}<p class="lvread">${lvRead(t,d,last)}</p></div>${lvMeter(t,d,last)}`);
  patch($("#lvRd"),lvIndRead(t,d,last)); patch($("#lvKey"),lvKey(d));
  // the volume and momentum strips add to the chart's height rather than squeezing the price
  const ph=innerWidth<=600, H=lvHeight()+(lvInd.has("vol")&&d.v?(ph?56:76):0)+(lvInd.has("mom")?(ph?66:88):0);
  box.innerHTML=lvChart(t,d,{w:Math.max(300,box.clientWidth),h:H,last,big:true,ind:lvInd});
  $(".lvside").style.maxHeight=innerWidth>1100?H+28+"px":"";     // the list scrolls beside the chart rather than running past it
  const lad=$("#lvLad"); patch(lad,lvLadder(t,d,last,prev));
  const now=lad.querySelector(".now"), scr=lad.scrollHeight>lad.clientHeight+4; lad.classList.toggle("lvfade",scr); if(now&&scr) lad.scrollTop=now.offsetTop-lad.clientHeight/2+now.offsetHeight/2;   // keep "Now" in view
}
/* the big chart takes the rest of the window, so the page reads as one full screen on a Mac */
function lvHeight(){ if(innerWidth<=600) return 260; const el=$("#lvChart"); const top=el?el.getBoundingClientRect().top+scrollY:520;
  return Math.round(Math.max(320,Math.min(760,innerHeight-top-84))); }   // room below for the key and Tick's button

/* ---------- the stock picker ---------- */
let lvItems=[], lvSel=-1, lvTimer=null, lvSeq=0;
function lvShow(){ const el=$("#lvRes"); if(!el) return; el.hidden=!lvItems.length;
  el.innerHTML=lvItems.map((e,i)=>`<button role="option" aria-selected="${i===lvSel}" data-lvgo="${esc(e.t)}" class="${i===lvSel?"on":""}"><b>${esc(e.t)}</b><span class="sn">${esc(e.n||"")}</span><span class="sf">${esc(e.exch||"")}</span></button>`).join(""); }
function lvClose(){ lvItems=[]; lvSel=-1; const i=$("#lvQ"); if(i){ i.value=""; i.blur(); } lvShow(); }
function lvWire(){
  const q=$("#lvQ");
  q.addEventListener("input",()=>{ const v=q.value.trim(); clearTimeout(lvTimer); if(!v){ lvItems=[]; lvShow(); return; }
    const seq=++lvSeq; lvTimer=setTimeout(async()=>{ try{ const rs=await (await fetch("/api/search?q="+encodeURIComponent(v))).json(); if(seq!==lvSeq) return; lvItems=rs.slice(0,7); lvSel=lvItems.length?0:-1; lvShow(); }catch(e){} },200); });
  q.addEventListener("keydown",e=>{
    if(e.key==="ArrowDown"||e.key==="ArrowUp"){ e.preventDefault(); if(!lvItems.length) return; lvSel=(lvSel+(e.key==="ArrowDown"?1:-1)+lvItems.length)%lvItems.length; lvShow(); }
    else if(e.key==="Enter"){ e.preventDefault(); const it=lvItems[lvSel]; const t=(it?.t||q.value).trim().toUpperCase().replace(/[./ ]/g,"-"); if(/^[A-Z][A-Z0-9-]{0,9}$/.test(t)) lvPick(t); }
    else if(e.key==="Escape"){ lvClose(); } });
  q.addEventListener("blur",()=>setTimeout(()=>{ if(document.activeElement!==q){ lvItems=[]; lvShow(); } },150));
  const ch=$("#lvChart");
  ch.addEventListener("pointermove",e=>{ const g=lvHover, svg=ch.querySelector("svg"); if(!g||!svg) return;
    const r=svg.getBoundingClientRect(), x=(e.clientX-r.left)*(svg.viewBox.baseVal.width/r.width), i=Math.floor((x-g.left)/g.step);
    const line=svg.querySelector("#lvX"); if(i<0||i>=g.N){ line?.setAttribute("visibility","hidden"); hideTip(); return; }
    const cx=g.left+g.step*(i+.5); line?.setAttribute("x1",cx); line?.setAttribute("x2",cx); line?.setAttribute("visibility","visible");
    const P=v=>lvP(g.t,v), ch1=i>0?g.C[i]/g.C[i-1]-1:null;
    let extra=""; if(g.ind){ const A=g.A, parts=[];
      [["ema4",A.ema4,"4 EMA"],["ema13",A.ema13,"13 EMA"],["vwap",A.vwap,"VWAP"]].forEach(([k,a,lab])=>{ if(g.ind.has(k)&&a?.[i]!=null) parts.push(`${lab} ${P(a[i])}`); });
      if(g.ind.has("vol")&&g.V) parts.push(`Volume ${vol(g.V[i])}`);
      if(g.ind.has("mom")&&A.rsi[i]!=null) parts.push(`Momentum ${A.rsi[i].toFixed(0)}`);
      if(parts.length) extra=`<br><span style="opacity:.75">${parts.join(" · ")}</span>`; }
    showTip(e,`<b>${lvWhen(g.D[i],g.iv)}</b><br>Close ${P(g.C[i])}${ch1!=null?` <span class="${cls(ch1)}">${pct(ch1)}</span>`:""}<br><span style="opacity:.75">Open ${P(g.O[i])} · High ${P(g.Hh[i])} · Low ${P(g.Lo[i])}</span>${extra}`); });
  ch.addEventListener("pointerleave",()=>{ ch.querySelector("#lvX")?.setAttribute("visibility","hidden"); hideTip(); });
}
document.addEventListener("click",e=>{
  const o=e.target.closest("[data-levels]"); if(o){ e.preventDefault(); openLevels(o.dataset.levels); return; }
  const r=e.target.closest("[data-lvr]"); if(r){ lvIv=r.dataset.lvr; save("lvIv",lvIv); renderLevels(); return; }
  const n=e.target.closest("[data-lvind]"); if(n){ const k=n.dataset.lvind; lvInd.has(k)?lvInd.delete(k):lvInd.add(k); save("lvInd",[...lvInd].join(",")); renderLevels(); return; }
  const g=e.target.closest("[data-lvgo]"); if(g){ e.preventDefault(); lvPick(g.dataset.lvgo); return; }
  const c=e.target.closest("#lvl [data-lv]"); if(c){ lvPick(c.dataset.lv); const m=$("#lvMain"); if(m&&c.classList.contains("lvcard")&&m.getBoundingClientRect().top>innerHeight*.6) m.scrollIntoView({behavior:"smooth",block:"start"}); }
});
/* ---------- the Levels tab on a stock's page: the same answer, sized for the drawer, with the full page a click away ---------- */
function paneLevels(el,t){
  const c=xpeek("levels",lvQ(t)), full=!!$("#drawer.full");
  const bars=`<div class="seg sm dlvbars" role="group" aria-label="Bar size">${LV_IV.map(([k,l,sh])=>`<button data-dlvr="${k}" aria-pressed="${k===lvIv}" aria-label="${l} bars"><span class="lg">${l}</span><span class="sh">${sh}</span></button>`).join("")}</div>`;
  const head=`<div class="dlvhead">${bars}<button class="lnk" data-levels="${esc(t)}">Open in Levels ›</button></div>`;
  if(!c?.data){
    if(c?.error){ el.innerHTML=head+errBox(c.error,"levels",lvQ(t)); return; }
    el.innerHTML=head+sk(360); const iv=lvIv;
    xget("levels",lvQ(t)).then(()=>{ if(drawerOpen&&sel===t&&drTab==="levels"&&lvIv===iv) renderTab(); }); return;
  }
  const d=c.data, last=lvLast(t,d), prev=lvPrev(t,d);
  const W=el.clientWidth||520, cw=full&&W>=820?W-320:W;
  const keep=lvHover, svg=lvChart(t,d,{w:Math.max(300,Math.round(cw)),h:innerWidth<=600?240:300,last,big:true}).replace(' id="lvX"',""); lvHover=keep;   // the Levels page owns the hover line
  el.innerHTML=`${head}<div class="lvsum dlvsum"><div class="lvv">${lvTag(lvVerdict(t,d,last))}<p class="lvread">${lvRead(t,d,last)}</p></div>${lvMeter(t,d,last)}</div>
    <div class="dlvbody${full&&W>=820?" two":""}"><div class="lvchart dlvchart">${svg}</div><div class="dlvside"><div class="lbl">All levels</div>${lvLadder(t,d,last,prev)}</div></div>`;
}
document.addEventListener("click",e=>{ const b=e.target.closest("[data-dlvr]"); if(!b) return; lvIv=b.dataset.dlvr; save("lvIv",lvIv); if(drawerOpen&&drTab==="levels") renderTab(); });

/* open the Levels page on a given stock (from the stock page, ⌘K or a link) */
function openLevels(t){ if(t){ lvT=t; save("lvT",t); } if(drawerOpen) closeDrawer(); if(page!=="levels") goPage("levels"); else renderLevels(); }
{ let rz=null; addEventListener("resize",()=>{ clearTimeout(rz); rz=setTimeout(()=>{ if(page==="levels"&&$("#lvl")) renderLevels(); },150); }); }
setInterval(()=>{ if(page!=="levels"||document.hidden||!$("#lvl")) return;      // new prices every few minutes while the page is open
  // wait for all of them (usually from cache) and repaint once, only when one of them is new, keeping the list where it was scrolled
  const syms=[...new Set([...LV_TOP.map(x=>x[0]),lvSym()])], at=()=>syms.map(s=>xpeek("levels",lvQ(s))?.at).join(), was=at();
  Promise.allSettled(syms.map(s=>xget("levels",lvQ(s)))).then(()=>{ if(page!=="levels"||!$("#lvl")||at()===was) return;
    const top=$("#lvLad")?.scrollTop; renderLevels(); const lad=$("#lvLad"); if(lad&&top!=null) lad.scrollTop=top; }); },60e3);
