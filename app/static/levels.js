/* OpenTicker: the Levels page. Support and resistance for the S&P 500, VXX and the Nasdaq-100 across the top, and
   one stock of your choice below, as large as the window allows. Levels come from /api/x/levels (key_levels in
   yahoo_extra.py): swing highs and lows over the last year, grouped into zones. Uses globals from index.html and pages.js. */

const LV_TOP=[["^GSPC","S&P 500","The 500 largest US companies"],["VXX","VXX","Tracks VIX futures: rises when investors get nervous"],["^NDX","Nasdaq-100","The 100 largest Nasdaq companies"]];
const LV_RANGES=[["3M",63],["6M",126],["1Y",252]];
let lvRange=load("lvRange","6M"); if(!LV_RANGES.some(r=>r[0]===lvRange)) lvRange="6M";
let lvT=load("lvT","")||null, lvHover=null;
const lvIdx=t=>t.startsWith("^");
const lvLabel=t=>LV_TOP.find(x=>x[0]===t)?.[1]||t;
function lvSym(){ return lvT||recent?.[0]||me?.positions?.[0]?.t||me?.watch?.[0]||"NVDA"; }
function lvPick(t){ if(!t) return; lvT=t; save("lvT",t); $("#lvMain")?.setAttribute("data-t",t); lvClose(); renderLevels(); }

/* an index is points, everything else dollars; big numbers drop the cents so a column of levels lines up */
function lvP(t,x){ if(x==null||!isFinite(x)) return "–"; const dp=x>=1000?0:2;
  return (lvIdx(t)?"":"$")+x.toLocaleString("en-US",{minimumFractionDigits:dp,maximumFractionDigits:dp}); }
const lvDay=d=>new Date(d+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",timeZone:"UTC"});
const lvAway=(p,last)=>{ const r=p/last-1; return `${Math.abs(r*100).toFixed(Math.abs(r)<.1?1:0)}% ${r>=0?"above":"below"}`; };
const LV_STR=["","light","moderate","strong"];

/* the latest price: the live one when OpenTicker streams this ticker, otherwise Yahoo's last daily bar */
function lvLast(t,d){ const F=!lvIdx(t)&&base?.px?.[t]?facts(t):null; return F?.last??d.last; }
function lvPrev(t,d){ const F=!lvIdx(t)&&base?.px?.[t]?facts(t):null; return F?.last&&F.chg!=null?F.last/(1+F.chg):d.prev; }
/* the levels sorted high to low, each marked against the latest price (it can have crossed one since Yahoo's bar) */
function lvLevels(d,last){
  const room=(d.tol||last*.006)/2;
  return (d.levels||[]).map(x=>({...x,k:x.p>last+room?"resistance":x.p<last-room?"support":"here"})).filter(x=>x.k!=="here"||x.touches>=2).sort((a,b)=>b.p-a.p);
}
function lvNearest(L){ return {s:L.filter(x=>x.k==="support")[0],r:L.filter(x=>x.k==="resistance").slice(-1)[0],here:L.find(x=>x.k==="here")}; }
const lvTimes=n=>n===1?"once":n===2?"twice":n+" times";

/* the written read: where the price sits between its nearest levels, and which one is closer */
function lvRead(t,d,last){
  const L=lvLevels(d,last), {s,r,here}=lvNearest(L), N=lvIdx(t)?`The ${lvLabel(t)}`:t, P=x=>lvP(t,x);
  const ma=["50","200"].map(k=>[k,d.ma?.[k]?.slice(-1)[0]]).filter(([k,v])=>v&&Math.abs(last/v-1)<.012)[0];
  const nearMa=ma?` It's also near its ${ma[0]}-day average (${P(ma[1])}), a line many traders watch.`:"";
  if(here) return `<b>${N} is testing ${P(here.p)}</b>, a price where it has turned ${lvTimes(here.touches)} in the past year. A close clearly above or below it often sets the next leg.${nearMa}`;
  if(!r&&s) return `<b>No resistance overhead.</b> ${N} is ${last>=d.hi52.p*.99?"at":"near"} its high for the year, so there's no recent price where sellers took over. Nearest support: ${P(s.p)}, ${lvAway(s.p,last).replace(" below","")} below.${nearMa}`;
  if(!s&&r) return `<b>No support below.</b> ${N} is ${last<=d.lo52.p*1.01?"at":"near"} its low for the year, so there's no recent price where buyers stepped in. Nearest resistance: ${P(r.p)}, ${lvAway(r.p,last).replace(" above","")} above.${nearMa}`;
  if(!s||!r) return `Not enough swings in the past year to mark clear levels for ${N}.`;
  const dS=1-s.p/last, dR=r.p/last-1, toR=dR<dS*.8, toS=dS<dR*.8;
  const side=toR?` It's closer to resistance, where sellers stopped it ${lvTimes(r.touches)}${r.flip?" (that price has worked as support too)":""}.`
    :toS?` It's closer to support, where buyers stepped in ${lvTimes(s.touches)}${s.flip?" (that price has capped it too)":""}.`:" It's about midway between the two.";
  return `<b>${N} is ${(dS*100).toFixed(1)}% above support at ${P(s.p)} and ${(dR*100).toFixed(1)}% below resistance at ${P(r.p)}.</b>${side}${nearMa}`;
}

/* ---------- the chart: price, level zones and their labels, the latest price, and on the big chart the averages ---------- */
function lvChart(t,d,{w,h,last,n,big}){
  const N=Math.min(n,d.c.length), i0=d.c.length-N, O=d.o.slice(i0), Hh=d.h.slice(i0), Lo=d.l.slice(i0), C=d.c.slice(i0), D=d.d.slice(i0);
  const L=lvLevels(d,last), near=lvNearest(L);
  const ph=innerWidth<=600, left=big?(ph?36:46):8, R=big?(ph?70:78):64, T=big?12:8, B=big?24:8, PW=w-left-R, PH=h-T-B;
  const step=PW/N, X=i=>left+step*(i+.5);
  let lo=Math.min(...Lo,last), hi=Math.max(...Hh,last);
  // the nearest level on each side always shows (if it's not absurdly far); others only when they fit the window
  [near.s,near.r].forEach(x=>{ if(x&&Math.abs(x.p/last-1)<.18){ lo=Math.min(lo,x.lo); hi=Math.max(hi,x.hi); } });
  const pad=(hi-lo)*.06||hi*.01; lo-=pad; hi+=pad;
  const Y=v=>T+PH*(1-(v-lo)/(hi-lo)), inView=x=>x.p>=lo&&x.p<=hi;
  const MA=big?[["50","var(--accent)"],["200","var(--warn)"]].map(([k,col])=>({k,col,a:(d.ma?.[k]||[]).slice(-N)})).filter(m=>m.a.some(v=>v!=null)):[];
  let s=`<svg class="lvsvg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(lvLabel(t))} price with support and resistance levels, ${lvRange}">`;
  if(big) niceTicks(lo,hi,Math.max(3,Math.round(PH/70))).forEach(v=>{ s+=`<line x1="${left}" x2="${w-R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--grid)"/><text x="${left-8}" y="${(Y(v)+4).toFixed(1)}" font-size="11" text-anchor="end" class="num" fill="var(--ink-3)">${v>=1000?v.toLocaleString("en-US",{maximumFractionDigits:0}):v.toFixed(v<10?2:0)}</text>`; });
  // zones under the price, so the bars read on top of them
  const col=x=>x.k==="resistance"?"var(--down)":x.k==="support"?"var(--up)":"var(--accent)";
  L.filter(inView).forEach(x=>{ const y1=Y(Math.min(hi,x.hi)), y2=Y(Math.max(lo,x.lo)), zh=Math.max(big?4:3,y2-y1), yc=(y1+y2)/2;
    s+=`<rect x="${left}" y="${(yc-zh/2).toFixed(1)}" width="${PW}" height="${zh.toFixed(1)}" fill="${col(x)}" opacity="${(.07+.03*x.strength).toFixed(2)}"/>`;
    s+=`<line x1="${left}" x2="${w-R}" y1="${Y(x.p).toFixed(1)}" y2="${Y(x.p).toFixed(1)}" stroke="${col(x)}" stroke-width="${x.strength>=3?1.4:1}" ${x.strength>=2?"":`stroke-dasharray="4 4"`} opacity=".75"/>`; });
  if(MA.length) s+=`<clipPath id="lvClip"><rect x="${left}" y="${T}" width="${PW}" height="${PH}"/></clipPath>`;   // an average far from the price runs off the chart, not over the axis
  MA.forEach(m=>{ let p=""; m.a.forEach((v,i)=>{ if(v==null) return; p+=(p?"L":"M")+X(i).toFixed(1)+","+Y(v).toFixed(1); }); s+=`<path d="${p}" fill="none" stroke="${m.col}" stroke-width="1.3" opacity=".8" stroke-dasharray="5 3" clip-path="url(#lvClip)"/>`; });
  if(big&&step>=1.5){ const bw=Math.max(1,Math.min(9,step*.62));
    C.forEach((c,i)=>{ const up=c>=O[i], cl=up?"var(--up)":"var(--down)", x=X(i), yo=Y(O[i]), yc=Y(c);
      s+=`<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${Y(Hh[i]).toFixed(1)}" y2="${Y(Lo[i]).toFixed(1)}" stroke="${cl}" stroke-width="1"/><rect x="${(x-bw/2).toFixed(1)}" y="${Math.min(yo,yc).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1,Math.abs(yc-yo)).toFixed(1)}" fill="${cl}" rx="${bw>4?1:0}"/>`; }); }
  else{ const p=C.map((c,i)=>(i?"L":"M")+X(i).toFixed(1)+","+Y(c).toFixed(1)).join(""); s+=`<path d="${p}" fill="none" stroke="var(--ink)" stroke-width="${big?1.6:1.4}" stroke-linejoin="round"/>`; }
  // the latest price
  const yl=Y(last); s+=`<line x1="${left}" x2="${w-R}" y1="${yl.toFixed(1)}" y2="${yl.toFixed(1)}" stroke="var(--ink-2)" stroke-dasharray="2 3" opacity=".7"/>`;
  // labels on the right, nudged apart so they never sit on top of each other; the latest price wins its spot
  // a small chart (and the phone's) labels only the nearest level on each side; the list below has the rest
  const fs=big?11.5:10.5, lh=big?21:17, labelled=big&&!ph?L.filter(inView):[near.r,near.s,near.here].filter(x=>x&&inView(x));
  const items=[{y:yl,txt:lvP(t,last),now:true},...labelled.map(x=>({y:Y(x.p),txt:lvP(t,x.p),x}))].sort((a,b)=>a.y-b.y);
  const placeLabels=a=>{ const top=T+lh/2-2, bot=h-B-lh/2+2;   // push down past any overlap, then back up from the bottom edge
    for(let j=1;j<a.length;j++) a[j].y=Math.max(a[j].y,a[j-1].y+lh);
    for(let j=a.length-1;j>=0;j--) a[j].y=Math.min(a[j].y,j===a.length-1?bot:a[j+1].y-lh);
    a.forEach(o=>o.y=Math.max(top,o.y)); };
  placeLabels(items);
  items.forEach(o=>{ const tw=o.txt.length*fs*.6+14, x0=w-R+6, c=o.now?"var(--ink)":col(o.x);
    s+=o.now?`<rect x="${x0}" y="${(o.y-lh/2+2).toFixed(1)}" width="${tw.toFixed(1)}" height="${lh-4}" rx="${(lh-4)/2}" fill="var(--ink)"/><text x="${(x0+7).toFixed(1)}" y="${(o.y+fs*.36).toFixed(1)}" font-size="${fs}" font-weight="650" class="num" fill="var(--panel)">${o.txt}</text>`
      :`<rect x="${x0}" y="${(o.y-lh/2+2).toFixed(1)}" width="${tw.toFixed(1)}" height="${lh-4}" rx="${(lh-4)/2}" fill="var(--panel)" stroke="${c}" stroke-opacity=".6"/><text x="${(x0+7).toFixed(1)}" y="${(o.y+fs*.36).toFixed(1)}" font-size="${fs}" font-weight="600" class="num" fill="${c}">${o.txt}</text>`; });
  if(big){ // month ticks along the bottom
    let lastM=""; const every=N>180?2:1; let cnt=0;
    D.forEach((dd,i)=>{ const m=dd.slice(0,7); if(m===lastM) return; const first=!lastM; lastM=m; if(first) return; if(cnt++%every) return;
      const lab=new Date(dd+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",timeZone:"UTC"})+(dd.slice(5,7)==="01"?" ’"+dd.slice(2,4):"");
      s+=`<line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${T}" y2="${h-B}" stroke="var(--grid)" opacity=".7"/><text x="${X(i).toFixed(1)}" y="${h-6}" font-size="11" text-anchor="middle" fill="var(--ink-3)">${lab}</text>`; });
    s+=`<line id="lvX" x1="0" x2="0" y1="${T}" y2="${h-B}" stroke="var(--ink-3)" stroke-width="1" visibility="hidden"/>`;
    lvHover={t,left,step,N,i0,T,B,h,O,Hh,Lo,C,D};
  }
  return s+"</svg>";
}

/* ---------- the side list: every level from the top down, with the latest price in its place ---------- */
function lvLadder(t,d,last,prev){
  const L=lvLevels(d,last), rows=L.map(x=>({p:x.p,x}));
  [["50","50-day average"],["200","200-day average"]].forEach(([k,lab])=>{ const v=d.ma?.[k]?.slice(-1)[0]; if(v) rows.push({p:v,ma:k,lab}); });
  rows.push({p:last,now:true}); rows.sort((a,b)=>b.p-a.p||(a.now?-1:1));
  const chg=prev?last/prev-1:null;
  return `<ol class="lvlad">${rows.map(r=>{
    if(r.now) return `<li class="now"><span class="lk">Now</span><span class="lp num">${lvP(t,last)}</span><span class="ld num ${cls(chg)}">${chg==null?"":pct(chg)+" today"}</span></li>`;
    if(r.ma) return `<li class="ma ma${r.ma}"><span class="lk"><i aria-hidden="true"></i>${r.lab}</span><span class="lp num">${lvP(t,r.p)}</span><span class="ld num">${lvAway(r.p,last)}</span></li>`;
    const x=r.x, kind=x.k==="here"?"At this level":x.k==="resistance"?"Resistance":"Support";
    return `<li class="${x.k}"><span class="lk">${kind}<span class="str" title="${LV_STR[x.strength][0].toUpperCase()+LV_STR[x.strength].slice(1)} level${x.flip?". It has worked as both support and resistance":""}" aria-label="${LV_STR[x.strength]} level">${[1,2,3].map(j=>`<i class="${j<=x.strength?"on":""}"></i>`).join("")}</span></span><span class="lp num">${lvP(t,x.p)}</span><span class="ld num">${x.k==="here"?"right here":lvAway(x.p,last)}</span>
      <span class="lm">${x.touches===1?"Turned here once":`Turned here ${lvTimes(x.touches)}`}, last ${lvDay(x.last)}${x.flip?" · both ways":""}</span></li>`; }).join("")}</ol>`;
}

/* ---------- the page ---------- */
function renderLevels(){
  if(!$("#lvl")){
    $("#app").innerHTML=`<div id="lvl" class="page">
      <div class="phead"><div><h1 class="ptitle">Levels</h1><p class="hint">Support is a price where buyers have stepped in before; resistance is where sellers have. The more often a price turned the market in the past year, the stronger the level.</p></div>
        <div class="seg" id="lvRng" role="group" aria-label="Chart range"></div></div>
      <section class="lvtop" id="lvTop" aria-label="Market levels">${LV_TOP.map(([s])=>`<button class="lvcard" data-lv="${esc(s)}" aria-pressed="false">${sk(170)}</button>`).join("")}</section>
      <section class="panel lvmain" id="lvMain">
        <div class="lvhead"><div class="lvwho" id="lvWho"></div>
          <div class="lvfind"><div class="lvsrch">${ic("search",14)}<input id="lvQ" type="search" placeholder="Show another stock…" autocomplete="off" spellcheck="false" aria-label="Show levels for another stock" aria-controls="lvRes"><div class="sres" id="lvRes" role="listbox" hidden></div></div><div class="lvquick" id="lvQuick"></div></div></div>
        <p class="lvread" id="lvRead"></p>
        <div class="lvbody"><div><div class="lvchart" id="lvChart">${sk(420)}</div>
          <div class="lvkey"><span><i class="k res"></i>Resistance</span><span><i class="k sup"></i>Support</span><span><i class="k m50"></i>50-day average</span><span><i class="k m200"></i>200-day average</span><span>Thicker band, stronger level</span></div></div>
          <div class="lvside"><div class="lbl">Levels, top to bottom</div><div id="lvLad">${sk(300)}</div></div></div>
      </section></div>`;
    lvWire();
  }
  $("#lvRng").innerHTML=LV_RANGES.map(([k])=>`<button data-lvr="${k}" aria-pressed="${k===lvRange}">${k}</button>`).join("");
  LV_TOP.forEach(([s])=>{ const c=xpeek("levels",{t:s}); if(c?.data||c?.error) lvCard(s); else xget("levels",{t:s}).then(()=>{ if(page==="levels") lvCard(s); }); });
  lvMain();
}
function lvCard(s){
  const el=document.querySelector(`.lvcard[data-lv="${CSS.escape(s)}"]`); if(!el) return;
  const c=xpeek("levels",{t:s}), t=lvSym(); el.setAttribute("aria-pressed",String(t===s));
  if(!c?.data){ el.innerHTML=c?.error?`<div class="lvch"><b>${esc(lvLabel(s))}</b></div>${errBox(c.error)}`:sk(170); return; }
  const d=c.data, last=lvLast(s,d), prev=lvPrev(s,d), chg=prev?last/prev-1:null, L=lvLevels(d,last), {s:sp,r:rs,here}=lvNearest(L);
  const w=Math.max(220,Math.round(el.clientWidth-26)), h=innerWidth<=600?96:92;
  el.title=`Show ${lvLabel(s)} below`;
  el.innerHTML=`<div class="lvch"><div><b>${esc(lvLabel(s))}</b><span class="hint">${esc(LV_TOP.find(x=>x[0]===s)[2])}</span></div><div class="lvpx"><span class="num">${lvP(s,last)}</span><span class="num ${cls(chg)}">${pct(chg)}</span></div></div>
    <div class="lvmini">${lvChart(s,d,{w,h,last,n:LV_RANGES.find(r=>r[0]===lvRange)[1]})}</div>
    <div class="lvfoot">${here?`<span><i class="k here"></i>Testing <b class="num">${lvP(s,here.p)}</b></span>`:""}${rs?`<span><i class="k res"></i>Resistance <b class="num">${lvP(s,rs.p)}</b> <span class="num">+${lvAway(rs.p,last).replace(" above","")}</span></span>`:`<span><i class="k res"></i>No resistance overhead</span>`}${sp?`<span><i class="k sup"></i>Support <b class="num">${lvP(s,sp.p)}</b> <span class="num">−${lvAway(sp.p,last).replace(" below","")}</span></span>`:`<span><i class="k sup"></i>No support below</span>`}</div>`;
}
function lvMain(){
  const t=lvSym(), c=xpeek("levels",{t});
  document.querySelectorAll(".lvcard").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.lv===t)));
  const top=LV_TOP.find(x=>x[0]===t), nm=top?top[2]:nameOf(t);
  $("#lvWho").innerHTML=`<h2>${esc(lvLabel(t))}</h2><span class="nm">${esc(nm&&nm!==t?nm:c?.data?.name||"")}</span>${lvIdx(t)?"":`<button class="lnk" data-sel="${esc(t)}">Open ${esc(t)} ›</button>`}`;
  const q=[...new Set([...(typeof recent!=="undefined"?recent:[]),...(me?.positions||[]).map(p=>p.t),...(me?.watch||[])])].filter(x=>x!==t).slice(0,5);
  $("#lvQuick").innerHTML=q.map(x=>`<button class="chip" data-lv="${esc(x)}">${esc(x)}</button>`).join("");
  if(!c?.data){
    if(c?.error){ $("#lvChart").innerHTML=errBox(c.error,"levels",{t}); $("#lvLad").innerHTML=""; $("#lvRead").innerHTML=""; return; }
    $("#lvChart").innerHTML=sk(lvHeight()); $("#lvLad").innerHTML=sk(300); $("#lvRead").innerHTML=`<span class="sk" style="display:block;height:20px;max-width:640px"></span>`;
    xget("levels",{t}).then(()=>{ if(page==="levels"&&lvSym()===t) lvMain(); }); return;
  }
  const d=c.data, last=lvLast(t,d), prev=lvPrev(t,d), box=$("#lvChart");
  $("#lvRead").innerHTML=lvRead(t,d,last);
  const H=lvHeight(); box.innerHTML=lvChart(t,d,{w:Math.max(300,box.clientWidth),h:H,last,n:LV_RANGES.find(r=>r[0]===lvRange)[1],big:true});
  $(".lvside").style.maxHeight=innerWidth>1100?H+28+"px":"";     // the list scrolls beside the chart rather than running past it
  const lad=$("#lvLad"); lad.innerHTML=lvLadder(t,d,last,prev);
  const now=lad.querySelector(".now"), scr=lad.scrollHeight>lad.clientHeight+4; lad.classList.toggle("scr",scr); if(now&&scr) lad.scrollTop=now.offsetTop-lad.clientHeight/2+now.offsetHeight/2;   // keep "Now" in view
}
/* the big chart takes the rest of the window, so the page reads as one full screen on a Mac */
function lvHeight(){ if(innerWidth<=600) return 260; const el=$("#lvChart"); const top=el?el.getBoundingClientRect().top+scrollY:520;
  return Math.round(Math.max(360,Math.min(760,innerHeight-top-84))); }   // room below for the key and Tick's button

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
    showTip(e,`<b>${new Date(g.D[i]+"T12:00:00Z").toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</b><br>Close ${P(g.C[i])}${ch1!=null?` <span class="${cls(ch1)}">${pct(ch1)}</span>`:""}<br><span style="opacity:.75">Open ${P(g.O[i])} · High ${P(g.Hh[i])} · Low ${P(g.Lo[i])}</span>`); });
  ch.addEventListener("pointerleave",()=>{ ch.querySelector("#lvX")?.setAttribute("visibility","hidden"); hideTip(); });
}
document.addEventListener("click",e=>{
  const o=e.target.closest("[data-levels]"); if(o){ e.preventDefault(); openLevels(o.dataset.levels); return; }
  const r=e.target.closest("[data-lvr]"); if(r){ lvRange=r.dataset.lvr; save("lvRange",lvRange); renderLevels(); return; }
  const g=e.target.closest("[data-lvgo]"); if(g){ e.preventDefault(); lvPick(g.dataset.lvgo); return; }
  const c=e.target.closest("#lvl [data-lv]"); if(c){ lvPick(c.dataset.lv); const m=$("#lvMain"); if(m&&c.classList.contains("lvcard")&&m.getBoundingClientRect().top>innerHeight*.6) m.scrollIntoView({behavior:"smooth",block:"start"}); }
});
/* open the Levels page on a given stock (from the stock page, ⌘K or a link) */
function openLevels(t){ if(t){ lvT=t; save("lvT",t); } if(drawerOpen) closeDrawer(); if(page!=="levels") goPage("levels"); else renderLevels(); }
{ let rz=null; addEventListener("resize",()=>{ clearTimeout(rz); rz=setTimeout(()=>{ if(page==="levels"&&$("#lvl")) renderLevels(); },150); }); }
setInterval(()=>{ if(page!=="levels"||document.hidden||!$("#lvl")) return;      // new prices every few minutes while the page is open
  [...LV_TOP.map(x=>x[0]),lvSym()].forEach(s=>xget("levels",{t:s}).then(()=>{ if(page==="levels") renderLevels(); })); },60e3);
