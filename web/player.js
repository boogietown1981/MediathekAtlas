// In-app player. Public entry points used by the catalogue, the detail views and the download list:
//   playMedia(item[,list]) – a catalogue entry (film, episode or whole series); list = episodes for "Nächste Folge"
//   playJob(job)            – a finished download
//   playNetzkino(id[,label]) – a Netzkino film (offline copy or the MP4 resolved by ytdl-nightly)
//   playPluto(id[,label])    – a Pluto TV film, episode or live channel (official HLS incl. adverts)
//   playLive(ref[,label])    – a live channel from the Live-TV tab (broadcaster stream or Pluto TV)
// The server decides per title whether the browser plays the source itself (MP4 from the broadcaster,
// local MP4) or whether ffmpeg remuxes it into a stream (MKV downloads, HLS). Remuxed streams have no
// seekable length in the browser, so this player brings its own timeline and restarts the stream at the
// chosen position. Playback positions are remembered per title on this device.
(()=>{
const S={call:0,info:null,offset:0,session:'',list:[],index:-1,key:'',mode:'',saved:0,retried:false,drag:false,seekTimer:0,ref:null,level:'',stats:null};
const video=$('player-video'),bar=$('player-bar'),slider=$('player-seek'),time=$('player-time'),status=$('player-status'),toggle=$('player-toggle'),dialog=$('player');
const fmt=s=>{s=Math.max(0,Math.floor(s||0));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=String(s%60).padStart(2,'0');return h?h+':'+String(m).padStart(2,'0')+':'+x:m+':'+x;};
const store=k=>{try{return JSON.parse(localStorage.getItem('atlas-play:'+k)||'null');}catch{return null;}};
const remember=(k,v)=>{try{v?localStorage.setItem('atlas-play:'+k,JSON.stringify(v)):localStorage.removeItem('atlas-play:'+k);}catch{}};
const embed=$('player-embed'),stage=$('player-stage');
const position=()=>S.mode==='embed'?S.embedPos||0:S.mode==='remux'?S.offset+(video.currentTime||0):video.currentTime||0;
const duration=()=>S.mode==='embed'?S.info?.duration||0:S.mode==='remux'?S.info?.duration||0:(Number.isFinite(video.duration)?video.duration:S.info?.duration||0);
function episodeKey(item){return item.work_id||item.id;}
function say(text){status.textContent=text||'';status.hidden=!text;}
// 0.5.81: the position also goes to the server (watch_state), so "Weiterschauen" works in every browser
// and on every device that uses this MediathekAtlas; the copy in this browser stays as a fast first answer.
const REF_SOURCE={offer:'mediatheken',job:'download'};
function push(key,pos,dur,done){
 if(!key||key.startsWith('live:')||typeof api!=='function')return;
 const ref=S.ref||{},name=Object.keys(ref).find(k=>k!=='direct')||'';
 const info={title:$('player-title').textContent||'',ref,source:REF_SOURCE[name]||name};
 api('watch-progress',{key,pos:Math.round(pos*10)/10,duration:Math.round((dur||0)*10)/10,done:!!done,info}).then(()=>window.AtlasWatch?.changed?.()).catch(()=>{});
}
function save(final){if(!S.key||S.info?.live)return;const d=duration(),p=position();if(final==='ended'||(d&&p>d-45)){remember(S.key,{done:true,at:Date.now()});push(S.key,p,d,true);return;}if(p>20){remember(S.key,{pos:p,at:Date.now()});push(S.key,p,d,false);}}
// Positions known to the server replace older ones of this browser (called by web/watchlist.js at the start).
window.AtlasPlayerSync=function(progress){for(const [k,v] of Object.entries(progress||{})){const mine=store(k);if(!mine||(mine.at||0)<(v.at||0))remember(k,v.done?{done:true,at:v.at}:{pos:v.pos,at:v.at});}};
function streamUrl(t){return S.info.remux+'&'+new URLSearchParams({t:t.toFixed(1),session:S.session,token,quality:S.level||wish()});}
// 0.5.63: quality of the playback. The wish ('auto', 'max' or a picture height) is remembered on this
// device. "Automatisch" loads at most 720p and steps down one level when the stream keeps waiting.
// 0.5.72: the two elements are created when the page does not have them (an older page kept open
// across an update), so the player itself always loads.
const qualityBox=$('player-quality-box')||Object.assign(document.createElement('label'),{id:'player-quality-box',className:'player-quality',hidden:true});
const qualitySelect=$('player-quality')||qualityBox.appendChild(Object.assign(document.createElement('select'),{id:'player-quality'}));
if(!qualityBox.isConnected){qualityBox.prepend('Qualität ');document.querySelector('.player-actions')?.prepend(qualityBox);}
const AUTO_HEIGHT=720;
function wish(){try{const v=localStorage.getItem('atlas-play-quality')||'auto';return /^(auto|max|\d{3,4})$/.test(v)?v:'auto';}catch{return 'auto';}}
function levels(){return (S.info?.levels||[]).filter(l=>l.height>0).sort((a,b)=>b.height-a.height);}
// Height the server plays for a wish (same rule as hls_variants.choose): largest level that fits, else the smallest.
function heightFor(w){const all=levels();if(!all.length)return 0;if(w==='max')return (S.info.hls?all[0]:all.find(l=>l.height<=1080)||all[all.length-1]).height;const top=w==='auto'?AUTO_HEIGHT:Number(w)||AUTO_HEIGHT;return (all.find(l=>l.height<=top)||all[all.length-1]).height;}
function currentHeight(){return heightFor(S.level||wish());}
function renderQuality(){const all=levels(),info=S.info;
 // Nothing to choose: one level only, local files, YouTube.
 const show=!!info&&info.origin==='online'&&info.mode!=='embed'&&all.length>1,own=info&&info.hls&&nativeHls()&&S.mode==='direct';
 qualityBox.hidden=!show;if(!show)return;
 const w=wish(),auto=heightFor('auto');
 qualitySelect.replaceChildren(new Option(S.mode==='hls'?'Automatisch'+(S.hlsHeight&&w==='auto'?' (jetzt '+S.hlsHeight+'p)':' (passt sich der Verbindung an)'):own?'Automatisch (Browser passt an)':'Automatisch ('+(S.level?'jetzt '+currentHeight():'bis '+auto)+'p)','auto'),new Option('Beste ('+heightFor('max')+'p)','max'),...all.map(l=>new Option(l.height+'p'+(l.bandwidth?' · '+(l.bandwidth/1e6).toFixed(1).replace('.',',')+' Mbit/s':''),String(l.height))));
 qualitySelect.value=[...qualitySelect.options].some(o=>o.value===w)?w:'auto';}
qualitySelect.onchange=async()=>{try{localStorage.setItem('atlas-play-quality',qualitySelect.value);}catch{}
 S.level='';S.retried=false;const info=S.info;if(!info)return;const t=info.live?0:position();
 if(S.mode==='hls'&&S.hls){S.hls.currentLevel=hlsLevel(wish());renderQuality();return;}   // hls.js switches while playing
 // Safari and the macOS app play HLS themselves and adapt on their own ("Automatisch"); a fixed level
 // comes through MediathekAtlas (ffmpeg) because the browser offers no choice of its own.
 if(info.hls){renderQuality();describe(info);if(nativeHls()&&wish()==='auto'&&info.url)startDirect(info.url,t);else if(info.ffmpeg)startRemux(t);else say('Für eine feste Qualitätsstufe wird ffmpeg benötigt.');return;}
 if(S.mode==='remux'){renderQuality();startRemux(t);return;}
 // Broadcaster files: every resolution is its own file, so the address is looked up again.
 try{const next=await api('play?'+new URLSearchParams({...S.ref,quality:wish()}));S.info=next;renderQuality();describe(next);if(next.mode==='direct')startDirect(next.src,t);else startRemux(t);}catch(e){say(e.message);}};
// Waiting pauses of the running stream: for the automatic step-down and for the diagnosis.
function newStats(){return {began:Date.now(),first:0,playing:0,watched:0,stalls:0,stallSeconds:0,stallAt:0,recent:[],reduced:0,reducedAt:0,sent:false};}
function stallEnd(){const st=S.stats;if(!st||!st.stallAt)return;const d=(Date.now()-st.stallAt)/1000;st.stallAt=0;if(d<0.3)return;st.stalls++;st.stallSeconds+=d;st.recent.push([Date.now(),d]);}
function stallLoad(){const st=S.stats;if(!st)return 0;const now=Date.now();st.recent=st.recent.filter(x=>now-x[0]<60000);return st.recent.reduce((a,x)=>a+x[1],0)+(st.stallAt?(now-st.stallAt)/1000:0);}
function stepDown(){const st=S.stats;if(!st||S.mode!=='remux'||wish()!=='auto'||!st.first||Date.now()-st.reducedAt<30000)return;
 if(stallLoad()<6)return;const lower=levels().find(l=>l.height<currentHeight());if(!lower)return;
 stallEnd();st.recent=[];st.reduced++;st.reducedAt=Date.now();S.level=String(lower.height);renderQuality();
 notice('Die Verbindung reicht für diese Qualität nicht. Wiedergabe läuft mit '+lower.height+'p weiter; unter „Qualität“ lässt sich eine feste Stufe wählen.');
 startRemux(S.info.live?0:position());}
function sendStats(){const st=S.stats,info=S.info;if(!st||st.sent||!info)return;stallEnd();if(st.playing)st.watched+=(Date.now()-st.playing)/1000;st.playing=0;
 if(st.watched<5&&!st.stalls)return;st.sent=true;
 api('playback-stats',{mode:S.mode,provider:info.provider||'mediathek',live:!!info.live,wish:wish(),level:String((S.mode==='hls'?S.hlsHeight:currentHeight())||''),native:!!(info.hls&&S.mode==='direct'),fallback:S.hlsFailed||'',switches:st.switches||0,watched:st.watched,first:st.first,stalls:st.stalls,stall_seconds:st.stallSeconds,reduced:st.reduced}).catch(()=>{});}
function startRemux(t){gateOff();S.gated=false;if(S.stats)S.stats.stallAt=0;S.fresh=true;S.mode='remux';S.offset=Math.max(0,t||0);video.controls=false;bar.hidden=false;slider.hidden=!S.info.duration;slider.max=S.info.duration||0;video.src=streamUrl(S.offset);video.play().catch(()=>{});say('Stream wird vorbereitet …');}
// 0.5.68 (Björn, 12.11.2026: on the providers' own sites the stations run clearly smoother than in the
// app): HLS is played by hls.js inside the browser, as those sites do - it loads the segments itself,
// keeps a buffer ahead, adapts the quality to the connection and keeps picture and sound together.
// Safari keeps its own HLS player. Only when the provider does not allow loading from this page (or
// the browser lacks the technique) the stream goes through ffmpeg as before.
// 0.5.72: hls.js is fetched only when a stream needs it and never in Safari, so it cannot stand in
// the way of the page or the player.
const hlsWanted=()=>!/Apple/.test(navigator.vendor||'')&&!!(window.MediaSource||window.ManagedMediaSource);
let hlsLoading=null;
function loadHls(){if(window.Hls)return Promise.resolve(true);if(!hlsLoading)hlsLoading=new Promise(done=>{const tag=document.createElement('script');tag.src='/hls.min.js';
  const timer=setTimeout(()=>done(false),8000);tag.onload=()=>{clearTimeout(timer);done(!!window.Hls);};tag.onerror=()=>{clearTimeout(timer);done(false);};document.head.append(tag);}).then(ok=>{if(!ok)hlsLoading=null;return ok;});
 return hlsLoading;}
function hlsJs(){return hlsWanted()&&!!(window.Hls&&window.Hls.isSupported());}
function hlsLevel(w){const all=S.hls?S.hls.levels:[];if(!all.length||w==='auto')return -1;const top=w==='max'?1e9:Number(w)||1e9;let best=-1;
 all.forEach((l,i)=>{const h=l.height||0;if(h<=top&&(best<0||h>(all[best].height||0)||(h===(all[best].height||0)&&l.bitrate<all[best].bitrate)))best=i;});
 if(best<0)all.forEach((l,i)=>{if(best<0||(l.height||1e9)<(all[best].height||1e9))best=i;});return best;}
function stopHls(){if(S.hls){try{S.hls.destroy();}catch{}S.hls=null;}}
// 0.5.72: /api/play no longer asks the provider for the levels when hls.js can read them; the ffmpeg path fetches them afterwards.
function probeLevels(){const info=S.info;if(!info||!info.hls||(info.levels||[]).length)return;api('play?'+new URLSearchParams({...S.ref,quality:wish(),probe:'1'})).then(r=>{if(S.info===info&&r.levels?.length){info.levels=r.levels;renderQuality();}}).catch(()=>{});}
function startHls(url,t){stopHls();gateOff();S.gated=false;S.fresh=true;S.mode='hls';video.controls=true;bar.hidden=true;say('Stream wird geladen …');
 const live=!!S.info.live,H=window.Hls,hls=new H({startPosition:live||!t?-1:t,maxBufferLength:30,maxMaxBufferLength:60,backBufferLength:30,liveSyncDurationCount:3,liveMaxLatencyDurationCount:10,
  manifestLoadingMaxRetry:1,levelLoadingMaxRetry:3,fragLoadingMaxRetry:4,capLevelToPlayerSize:false});
 S.hls=hls;let recovered=0;
 const fallback=reason=>{if(S.hls!==hls)return;const at=live?0:(video.currentTime||t||0);stopHls();S.hlsFailed=reason;video.removeAttribute('src');video.load();
  if(S.info.ffmpeg){startRemux(at);probeLevels();}else if(nativeHls())startDirect(url,at);else say('Dieser Stream lässt sich im Browser nicht laden ('+reason+') und ffmpeg fehlt.');
  renderQuality();describe(S.info);};
 hls.on(H.Events.MANIFEST_PARSED,()=>{if(S.hls!==hls)return;
  const seen=new Map();for(const l of hls.levels)if(l.height&&(!seen.has(l.height)||l.bitrate<seen.get(l.height)))seen.set(l.height,l.bitrate);
  if(seen.size)S.info.levels=[...seen].map(([height,bandwidth])=>({id:String(height),label:height+'p',height,bandwidth}));
  hls.currentLevel=hlsLevel(wish());renderQuality();video.play().catch(()=>{});});
 hls.on(H.Events.LEVEL_SWITCHED,(e,d)=>{const l=hls.levels[d.level];S.hlsHeight=l&&l.height||0;if(S.stats)S.stats.switches=(S.stats.switches||0)+1;renderQuality();});
 hls.on(H.Events.ERROR,(e,d)=>{if(S.hls!==hls||!d.fatal)return;
  if(d.type===H.ErrorTypes.MEDIA_ERROR&&recovered<2){recovered++;hls.recoverMediaError();return;}
  fallback(d.type===H.ErrorTypes.NETWORK_ERROR?'Anbieter nicht direkt erreichbar':String(d.details||d.type));});
 hls.loadSource(url);hls.attachMedia(video);}
function startDirect(src,t){gateOff();S.gated=false;S.fresh=true;S.mode='direct';video.controls=true;bar.hidden=true;video.src=src;if(t)video.addEventListener('loadedmetadata',()=>{try{video.currentTime=t;}catch{}},{once:true});video.play().catch(()=>{});say('Wird geladen …');}
function seek(t){const d=duration();t=Math.max(0,d?Math.min(t,d-1):t);if(S.mode==='direct'){video.currentTime=t;return;}
 // Restarting ffmpeg for every arrow key press would be wasteful: wait until input settles.
 S.offset=t;slider.value=t;time.textContent=fmt(t)+' / '+fmt(d);clearTimeout(S.seekTimer);S.seekTimer=setTimeout(()=>startRemux(t),350);}
async function open(ref,label,key,start){
 const call=++S.call;save();sendStats();S.retried=false;S.embedAlt=false;S.key=key||'';S.session=Math.random().toString(36).slice(2);stopVideo();S.ref=ref;S.level='';S.stats=null;S.info=null;S.hlsFailed='';S.hlsHeight=0;renderQuality();
 $('player-title').textContent=label||'Wird geladen …';$('player-meta').textContent='';$('player-restart').hidden=true;
 if(!dialog.open)dialog.showModal();say('Quelle wird ermittelt …');renderNext();
 let info;try{info=await api('play?'+new URLSearchParams({...ref,quality:wish(),...(hlsWanted()?{levels:'0'}:{})}));}catch(e){if(call===S.call)say(e.message+(ref.direct?' Auf youtube.com lässt sich das Video weiterhin ansehen.':''));return;}
 // 0.5.72: a title chosen meanwhile wins; the answer for the earlier one must not start under its name
 // (Björn, 12.11.2026: arte started although another station had been clicked).
 if(call!==S.call)return;
 if(info.hls&&info.url&&hlsWanted()){await loadHls();if(call!==S.call)return;}
 S.info=info;S.stats=newStats();$('player-title').textContent=info.title||label||'Video';describe(info);renderQuality();
 const last=start===0||info.live?null:store(S.key);let t=last&&!last.done&&last.pos>20&&(!info.duration||last.pos<info.duration-45)?last.pos:0;
 $('player-restart').hidden=!t;
 if(t)notice('Fortgesetzt bei '+fmt(t)+'. „Von vorn“ startet neu.');
 if(info.mode==='embed'){startEmbed(info,t);return;}
 if(info.mode==='direct')startDirect(info.src,t);
 else if(info.hls&&info.url&&hlsJs())startHls(info.url,t);
 else if(info.hls&&info.url&&nativeHls()&&(wish()==='auto'||!info.ffmpeg))startDirect(info.url,t);
 else if(!info.ffmpeg)say('Für diesen Stream wird ffmpeg benötigt. Unter Einstellungen die Werkzeugprüfung öffnen.');
 else{startRemux(t);probeLevels();}}
function describe(info){
 $('player-meta').textContent=[info.origin==='local'?'Lokale Datei'+(info.file?' · '+info.file:''):(info.provider==='netzkino'?'Online-Stream von Netzkino':info.provider==='pluto'?(info.live?'Live bei Pluto TV':'Online-Stream von Pluto TV'):info.provider==='justwatch'?'Online-Stream von JustWatch TV':info.provider==='rakuten'?(info.live?'Live bei Rakuten TV':'Online-Stream von Rakuten TV'):info.provider==='toggo'?'Online-Stream von TOGGO':info.provider==='youtube'?'YouTube'+(info.channel?' · '+info.channel:''):info.live?'Live-Stream des Senders':'Online-Stream des Senders')+(info.quality?' · '+info.quality:''),info.duration?fmt(info.duration):'',info.mode==='remux'&&(S.mode==='remux'||!(info.hls&&(hlsJs()||(nativeHls()&&wish()==='auto'))))?'über MediathekAtlas umgewandelt':''].filter(Boolean).join(' · ');}
// 0.5.53: YouTube – the official embedded player (youtube-nocookie.com). Its IFrame API reports the
// position via postMessage, so "Weiterschauen" works as for every other title.
// 0.5.76 (Björn, 13.11.2026: music videos show "nicht verfügbar" in the embedded player but play on
// youtube.com): many labels allow playback on youtube.com only. A refused video is tried once more
// through youtube.com/embed; a bar below the player always offers the way out: open on YouTube, or
// (with the offline switch on) load it shortly and play the copy here.
const EMBED_REFUSED=[100,101,150,152,153];
const embedHelp=(()=>{const n=document.createElement('div');n.id='player-embed-help';n.hidden=true;stage.after(n);return n;})();
function embedHelpShow(reason){const info=S.info||{};embedHelp.replaceChildren();embedHelp.hidden=false;embedHelp.classList.toggle('refused',!!reason);
 const text=document.createElement('span');text.textContent=reason||'Spielt das Video hier nicht?';embedHelp.append(text);
 if(/^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}$/.test(info.web_url||'')){const a=document.createElement('a');a.className='button';a.textContent='Auf YouTube ansehen';a.href=info.web_url;a.target='_blank';a.rel='noopener noreferrer';embedHelp.append(a);}
 if(info.offline&&S.ref?.youtube){
  // 0.5.78: the own player (stream resolved by yt-dlp on the server) – only with the opt-in switch
  const own=document.createElement('button');own.type='button';own.className='primary';own.textContent='▶ Im eigenen Player abspielen';own.onclick=()=>ownPlayer();embedHelp.append(own);
  const b=document.createElement('button');b.type='button';b.textContent='⬇ Kurz laden und hier abspielen';b.onclick=()=>loadAndPlay(b,text);embedHelp.append(b);}
 else if(reason&&info.offline_hint){const h=document.createElement('small');h.textContent=info.offline_hint;embedHelp.append(h);}}
async function loadAndPlay(button,text){const ref=S.ref,key=S.key,label=$('player-title').textContent,session=S.session,id=ref.youtube;button.disabled=true;
 let quality='best';try{const v=localStorage.getItem('atlas-download-quality')||'';if(/^(best|\d{3,4})$/.test(v))quality=v;}catch{}
 try{await api('youtube-download-add',{id,quality});}catch(e){text.textContent='Laden nicht möglich: '+e.message;button.disabled=false;return;}
 window.AtlasOffline?.refresh('youtube');
 for(let i=0;i<400;i++){
  if(S.session!==session||!dialog.open)return;   // another title was opened or the player closed: the copy keeps loading
  let job;try{job=((await api('youtube-downloads?'+new URLSearchParams({id}))).items||[])[0];}catch{job=null;}
  if(job&&job.state==='done'){open(ref,label,key);return;}
  if(job&&['error','cancelled','interrupted','expired','removed'].includes(job.state)){text.textContent='Laden fehlgeschlagen'+(job.error?': '+job.error:'')+'.';button.disabled=false;return;}
  text.textContent=job&&job.state==='tagging'?'Datei wird fertiggestellt …':job&&job.total?'Wird geladen … '+Math.round(100*job.received/job.total)+' %':job&&job.received?'Wird geladen … '+(job.received/1048576).toFixed(1).replace('.',',')+' MiB':'Wird geladen …';
  await new Promise(r=>setTimeout(r,2500));}
 text.textContent='Das Laden dauert ungewöhnlich lange; der Auftrag steht unter Downloads.';button.disabled=false;}
function ownPlayer(){const list=S.list,index=S.index,id=S.ref.youtube,label=$('player-title').textContent,key=S.key;
 // later videos of a running playlist go straight to the own player as well
 S.direct=true;const p=open({youtube:id,direct:'1'},label,key);S.list=list;S.index=index;renderNext();return p;}
function embedRefused(code){if(S.mode!=='embed')return;
 if(code!==100&&S.info?.offline&&S.ref?.youtube){ownPlayer();return;}
 if(!S.embedAlt){S.embedAlt=true;startEmbed(S.info,S.embedPos||0);return;}   // second try: youtube.com instead of youtube-nocookie.com
 embedHelpShow(code===100?'Das Video ist bei YouTube nicht mehr verfügbar.':'YouTube erlaubt dieses Video nicht in eingebetteten Playern, nur auf youtube.com.');}
function startEmbed(info,t){S.mode='embed';S.embedPos=t||0;stage.classList.add('embed');embed.hidden=false;embedHelpShow('');
 const q=new URLSearchParams({autoplay:'1',rel:'0',playsinline:'1',enablejsapi:'1',origin:location.origin,start:String(Math.floor(t||0))});
 if(!/^https:\/\/www\.youtube-nocookie\.com\/embed\/[A-Za-z0-9_-]{11}$/.test(info.embed||'')){say('Ungültige YouTube-Adresse');return;}
 const host=S.embedAlt?'https://www.youtube.com':'https://www.youtube-nocookie.com';
 embed.src=(S.embedAlt?info.embed.replace('https://www.youtube-nocookie.com','https://www.youtube.com'):info.embed)+'?'+q;say('');
 embed.onload=()=>{try{embed.contentWindow.postMessage(JSON.stringify({event:'listening',id:'atlas'}),host);}catch{}};}
window.addEventListener('message',e=>{if(!['https://www.youtube-nocookie.com','https://www.youtube.com'].includes(e.origin)||S.mode!=='embed'||e.source!==embed.contentWindow)return;
 let d;try{d=typeof e.data==='string'?JSON.parse(e.data):e.data;}catch{return;}
 if(d&&d.event==='onError'&&EMBED_REFUSED.includes(Number(d.info))){embedRefused(Number(d.info));return;}
 const info=d&&d.info;if(!info||typeof info!=='object')return;if(typeof info.currentTime==='number')S.embedPos=info.currentTime;
 if(info.playerState===0){save('ended');if(S.list[S.index]?.youtube&&S.list[S.index+1])playIndex(S.index+1);}else if(info.playerState===2)save();});
// 0.5.68: only Safari (and other Apple WebKit browsers) plays HLS itself. Chrome reports a built-in
// HLS player as well since late 2025, but it is new and plays live streams unevenly.
function nativeHls(){return /Apple/.test(navigator.vendor||'')&&!!video.canPlayType('application/vnd.apple.mpegurl');}
// 0.5.77 (Björn, 13.11.2026: "nicht richtig smooth, vorher mehr buffern bis sich der Stream fängt"): online streams
// collect a reserve before they run – 8 s at the start, 4 s after a seek, 5 s after every stall – instead of
// starting with the first frame and stalling again at once. At most 15 s of waiting; a click on play ends it.
const GATE={start:8,seek:4,stall:5,max:15};
function ahead(){const b=video.buffered,t=video.currentTime;for(let i=0;i<b.length;i++)if(b.start(i)<=t+1&&b.end(i)>t)return b.end(i)-Math.max(t,b.start(i));return 0;}
function gateOff(){if(S.gate){clearInterval(S.gate.timer);S.gate=null;}}
function gate(need){if(S.gate||!S.info||S.info.origin!=='online'||S.mode==='embed'||!S.mode||ahead()>=need)return false;
 const g=S.gate={need,until:Date.now()+GATE.max*1000,timer:0,best:0,grew:Date.now()};if(S.stats)S.stats.gates=(S.stats.gates||0)+1;
 const tick=()=>{if(S.gate!==g)return;const have=ahead();
  if(have>g.best+0.2){g.best=have;g.grew=Date.now();}
  // enough, waited long enough, or nothing more arrives (short file, stream at its end)
  if(have>=need||Date.now()>g.until||Date.now()-g.grew>3000||video.ended){gateOff();g.own=true;video.play().catch(()=>{});return;}
  say('Puffer wird gefüllt … '+Math.floor(have)+' von '+need+' s');};
 g.pausing=true;video.pause();g.pausing=false;g.timer=setInterval(tick,250);tick();return true;}
function stopVideo(){gateOff();stopHls();embedHelp.hidden=true;if(S.mode==='embed'){embed.removeAttribute('src');embed.hidden=true;stage.classList.remove('embed');S.mode='';}clearTimeout(S.seekTimer);video.pause();video.removeAttribute('src');video.load();}
function renderNext(){const b=$('player-next'),n=S.list[S.index+1];b.hidden=!n;if(n&&n.youtube){b.textContent='Nächstes Video ▸ '+String(n.label||'').slice(0,40);return;}if(n){const m=n.metadata||{};b.textContent='Nächste Folge ▸ '+(Number.isInteger(m.season)&&Number.isInteger(m.episode)?'S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0'):'');}}
function playIndex(i){S.index=i;const item=S.list[i];if(item.youtube)return open(S.direct?{youtube:item.youtube,direct:'1'}:{youtube:item.youtube},item.label||'YouTube','youtube:'+item.youtube);return open({offer:item.id},episodeLabel(item),episodeKey(item));}
function episodeLabel(item){const m=item.metadata||{};return (m.title||item.source?.title||'Video')+(Number.isInteger(m.season)&&Number.isInteger(m.episode)?' · S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0'):'')+(m.episode_title?' · '+m.episode_title:'');}
async function episodes(show){const d=await api('catalog?'+new URLSearchParams({kind:'series',show,downloaded:'all',archive:'0'}));return d.items.filter(x=>!x.series_parent);}
window.playMedia=async function(item,list){
 try{
  if(item.series_parent){$('player-title').textContent=item.metadata?.title||'Serie';const all=await episodes(item.show_key);if(!all.length)throw Error('Für diese Serie sind keine Folgen abspielbar.');
   // "Weiterschauen": the first episode that was started but not finished, otherwise the first unseen one.
   const started=all.findIndex(x=>{const s=store(episodeKey(x));return s&&!s.done;}),unseen=all.findIndex(x=>!store(episodeKey(x))?.done);
   S.list=all;return playIndex(started>=0?started:unseen>=0?unseen:0);}
  const eps=(list||[]).filter(x=>!x.series_parent&&x.metadata?.kind==='series');
  S.list=eps;S.index=eps.findIndex(x=>x.id===item.id);if(S.index<0){S.list=[];S.index=-1;}
  return open({offer:item.id},episodeLabel(item),episodeKey(item));
 }catch(e){notice(e.message,'error');}};
window.playPluto=function(id,label){S.list=[];S.index=-1;return open({pluto:id},label||'Pluto TV','pluto:'+id);};
// Live-TV tab (0.5.50): ref is {offer:id} (broadcaster live stream) or {pluto:id}; live has no resume position.
window.playLive=function(ref,label){S.list=[];S.index=-1;return open(ref,label||'Live-TV','live:'+Object.values(ref).join(':'),0);};
window.playJustWatch=function(id,label){S.list=[];S.index=-1;return open({justwatch:id},label||'JustWatch TV','justwatch:'+id);};
// 0.5.53: YouTube plays in the official embedded player (or locally when an offline copy exists).
window.playYouTube=function(id,label){S.direct=false;S.list=[];S.index=-1;return open({youtube:id},label||'YouTube','youtube:'+id);};
// 0.5.71: a music playlist plays video after video (embedded player or offline copy), with "Nächstes Video".
window.playYouTubeList=function(items,start){S.direct=false;S.list=(items||[]).filter(x=>x&&x.id).map(x=>({youtube:x.id,label:x.label}));if(!S.list.length)return;return playIndex(Math.min(Math.max(0,start|0),S.list.length-1));};
// 0.5.81: "Weiterschauen" opens a title again by the reference and key the player stored for it.
window.playRef=function(ref,label,key){S.direct=false;S.list=[];S.index=-1;return open(ref,label||'Video',key);};
window.playRakuten=function(id,label){S.list=[];S.index=-1;return open({rakuten:id},label||'Rakuten TV','rakuten:'+id);};
// 0.5.79: TOGGO episode (only streams TOGGO lists without copy protection; otherwise the server names the reason)
window.playToggo=function(id,label){S.list=[];S.index=-1;return open({toggo:id},label||'TOGGO','toggo:'+id);};
window.playNetzkino=function(id,label){S.list=[];S.index=-1;return open({netzkino:id},label||'Netzkino','netzkino:'+id);};
window.playJob=function(job){S.list=[];S.index=-1;const m=job.metadata||{};return open({job:job.id},episodeLabel({metadata:m,source:job.source}),'job:'+job.id);};
window.playable=function(item){return !!(item&&(item.series_parent||item.downloaded||(item.links||[]).some(l=>/^https?:\/\//i.test(l.url)&&!/\.mpd(\?|$)/i.test(l.url))));};
function close(){S.call++;save();sendStats();stopVideo();qualityBox.hidden=true;S.key='';if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});if(dialog.open)dialog.close();}
$('player-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
$('player-next').onclick=()=>{save('ended');playIndex(S.index+1);};
$('player-restart').onclick=()=>{remember(S.key,null);if(S.key&&typeof api==='function')api('watch-forget',{key:S.key}).then(()=>window.AtlasWatch?.changed?.()).catch(()=>{});$('player-restart').hidden=true;if(S.mode==='embed'){startEmbed(S.info,0);return;}S.mode==='remux'?startRemux(0):seek(0);};
toggle.onclick=()=>video.paused?video.play().catch(()=>{}):video.pause();
$('player-mute').onclick=()=>{video.muted=!video.muted;$('player-mute').textContent=video.muted?'🔇':'🔊';};
$('player-full').onclick=()=>{const box=$('player-stage');document.fullscreenElement?document.exitFullscreen().catch(()=>{}):(box.requestFullscreen?box.requestFullscreen().catch(()=>{}):video.webkitEnterFullscreen?.());};
$('player-back').onclick=()=>seek(position()-10);$('player-fwd').onclick=()=>seek(position()+30);
slider.oninput=()=>{S.drag=true;time.textContent=fmt(Number(slider.value))+' / '+fmt(duration());};
slider.onchange=()=>{S.drag=false;seek(Number(slider.value));};
video.addEventListener('timeupdate',()=>{if(S.mode!=='remux'||S.drag)return;const p=position();slider.value=p;time.textContent=fmt(p)+' / '+fmt(duration());});
video.addEventListener('play',()=>{gateOff();});   // a click on play ends the waiting
video.addEventListener('playing',()=>{if(S.fresh&&!S.gated){S.gated=true;if(gate(S.stats&&S.stats.first?GATE.seek:GATE.start))return;}say('');toggle.textContent='❚❚';S.fresh=false;const st=S.stats;if(st){stallEnd();if(!st.first)st.first=(Date.now()-st.began)/1000;if(!st.playing)st.playing=Date.now();}});
video.addEventListener('pause',()=>{if(S.gate&&S.gate.pausing)return;toggle.textContent='▶';save();const st=S.stats;if(st&&st.playing){st.watched+=(Date.now()-st.playing)/1000;st.playing=0;}});
video.addEventListener('waiting',()=>{say('Puffern …');const st=S.stats;if(st&&st.first&&!S.fresh&&!st.stallAt&&!video.seeking)st.stallAt=Date.now();if(!S.fresh&&!video.seeking&&!video.paused)gate(GATE.stall);});
setInterval(()=>{if(dialog.open)stepDown();},2000);
video.addEventListener('ended',()=>{save('ended');if(S.list[S.index+1])playIndex(S.index+1);else say('Ende');});
video.addEventListener('error',()=>{if(!S.info||!video.getAttribute('src')||S.mode==='hls')return;
 // A browser that cannot decode the broadcaster's file (or an unsupported container) gets the ffmpeg stream instead.
 if(S.mode==='direct'&&S.info.ffmpeg&&!S.retried){S.retried=true;const t=video.currentTime||0;startRemux(t);return;}
 say(S.mode==='remux'?'Wiedergabe fehlgeschlagen. Details im Live-Protokoll; häufige Ursache: Stream nicht mehr verfügbar oder Geosperre.':'Diese Datei kann der Browser nicht abspielen.');});
setInterval(()=>{if(dialog.open&&!video.paused)save();},10000);
dialog.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target!==slider)return;if(e.key===' '||e.key==='k'){e.preventDefault();toggle.click();}else if(e.key==='ArrowLeft'&&e.target!==slider){e.preventDefault();seek(position()-10);}else if(e.key==='ArrowRight'&&e.target!==slider){e.preventDefault();seek(position()+10);}else if(e.key==='f'){$('player-full').click();}});
window.addEventListener('pagehide',()=>{save();sendStats();});
})();
