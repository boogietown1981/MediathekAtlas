// In-app player. Public entry points used by the catalogue, the detail views and the download list:
//   playMedia(item[,list]) – a catalogue entry (film, episode or whole series); list = episodes for "Nächste Folge"
//   playJob(job)            – a finished download
//   playNetzkino(id[,label]) – a Netzkino film (offline copy or the MP4 resolved by ytdl-nightly)
// The server decides per title whether the browser plays the source itself (MP4 from the broadcaster,
// local MP4) or whether ffmpeg remuxes it into a stream (MKV downloads, HLS). Remuxed streams have no
// seekable length in the browser, so this player brings its own timeline and restarts the stream at the
// chosen position. Playback positions are remembered per title on this device.
(()=>{
const S={info:null,offset:0,session:'',list:[],index:-1,key:'',mode:'',saved:0,retried:false,drag:false,seekTimer:0};
const video=$('player-video'),bar=$('player-bar'),slider=$('player-seek'),time=$('player-time'),status=$('player-status'),toggle=$('player-toggle'),dialog=$('player');
const fmt=s=>{s=Math.max(0,Math.floor(s||0));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=String(s%60).padStart(2,'0');return h?h+':'+String(m).padStart(2,'0')+':'+x:m+':'+x;};
const store=k=>{try{return JSON.parse(localStorage.getItem('atlas-play:'+k)||'null');}catch{return null;}};
const remember=(k,v)=>{try{v?localStorage.setItem('atlas-play:'+k,JSON.stringify(v)):localStorage.removeItem('atlas-play:'+k);}catch{}};
const position=()=>S.mode==='remux'?S.offset+(video.currentTime||0):video.currentTime||0;
const duration=()=>S.mode==='remux'?S.info?.duration||0:(Number.isFinite(video.duration)?video.duration:S.info?.duration||0);
function episodeKey(item){return item.work_id||item.id;}
function say(text){status.textContent=text||'';status.hidden=!text;}
function save(final){if(!S.key)return;const d=duration(),p=position();if(final==='ended'||(d&&p>d-45)){remember(S.key,{done:true,at:Date.now()});return;}if(p>20)remember(S.key,{pos:p,at:Date.now()});}
function streamUrl(t){return S.info.remux+'&'+new URLSearchParams({t:t.toFixed(1),session:S.session,token});}
function startRemux(t){S.mode='remux';S.offset=Math.max(0,t||0);video.controls=false;bar.hidden=false;slider.hidden=!S.info.duration;slider.max=S.info.duration||0;video.src=streamUrl(S.offset);video.play().catch(()=>{});say('Stream wird vorbereitet …');}
function startDirect(src,t){S.mode='direct';video.controls=true;bar.hidden=true;video.src=src;if(t)video.addEventListener('loadedmetadata',()=>{try{video.currentTime=t;}catch{}},{once:true});video.play().catch(()=>{});say('Wird geladen …');}
function seek(t){const d=duration();t=Math.max(0,d?Math.min(t,d-1):t);if(S.mode==='direct'){video.currentTime=t;return;}
 // Restarting ffmpeg for every arrow key press would be wasteful: wait until input settles.
 S.offset=t;slider.value=t;time.textContent=fmt(t)+' / '+fmt(d);clearTimeout(S.seekTimer);S.seekTimer=setTimeout(()=>startRemux(t),350);}
async function open(ref,label,key,start){
 save();S.retried=false;S.key=key||'';S.session=Math.random().toString(36).slice(2);stopVideo();
 $('player-title').textContent=label||'Wird geladen …';$('player-meta').textContent='';$('player-restart').hidden=true;
 if(!dialog.open)dialog.showModal();say('Quelle wird ermittelt …');renderNext();
 let info;try{info=await api('play?'+new URLSearchParams(ref));}catch(e){say(e.message);return;}
 S.info=info;$('player-title').textContent=info.title||label||'Video';
 $('player-meta').textContent=[info.origin==='local'?'Lokale Datei'+(info.file?' · '+info.file:''):(info.provider==='netzkino'?'Online-Stream von Netzkino':'Online-Stream des Senders')+(info.quality?' · '+info.quality:''),info.duration?fmt(info.duration):'',info.mode==='remux'&&!(info.hls&&nativeHls())?'über MediathekAtlas umgewandelt':''].filter(Boolean).join(' · ');
 const last=start===0?null:store(S.key);let t=last&&!last.done&&last.pos>20&&(!info.duration||last.pos<info.duration-45)?last.pos:0;
 $('player-restart').hidden=!t;
 if(t)notice('Fortgesetzt bei '+fmt(t)+'. „Von vorn“ startet neu.');
 if(info.mode==='direct')startDirect(info.src,t);
 else if(info.hls&&info.url&&nativeHls())startDirect(info.url,t);
 else if(!info.ffmpeg)say('Für diesen Stream wird ffmpeg benötigt. Unter Einstellungen die Werkzeugprüfung öffnen.');
 else startRemux(t);}
function nativeHls(){return !!video.canPlayType('application/vnd.apple.mpegurl');}
function stopVideo(){clearTimeout(S.seekTimer);video.pause();video.removeAttribute('src');video.load();}
function renderNext(){const b=$('player-next'),n=S.list[S.index+1];b.hidden=!n;if(n){const m=n.metadata||{};b.textContent='Nächste Folge ▸ '+(Number.isInteger(m.season)&&Number.isInteger(m.episode)?'S'+String(m.season).padStart(2,'0')+'E'+String(m.episode).padStart(2,'0'):'');}}
function playIndex(i){S.index=i;const item=S.list[i];return open({offer:item.id},episodeLabel(item),episodeKey(item));}
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
window.playNetzkino=function(id,label){S.list=[];S.index=-1;return open({netzkino:id},label||'Netzkino','netzkino:'+id);};
window.playJob=function(job){S.list=[];S.index=-1;const m=job.metadata||{};return open({job:job.id},episodeLabel({metadata:m,source:job.source}),'job:'+job.id);};
window.playable=function(item){return !!(item&&(item.series_parent||item.downloaded||(item.links||[]).some(l=>/^https?:\/\//i.test(l.url)&&!/\.mpd(\?|$)/i.test(l.url))));};
function close(){save();stopVideo();S.key='';if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});if(dialog.open)dialog.close();}
$('player-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
$('player-next').onclick=()=>{save('ended');playIndex(S.index+1);};
$('player-restart').onclick=()=>{remember(S.key,null);$('player-restart').hidden=true;S.mode==='remux'?startRemux(0):seek(0);};
toggle.onclick=()=>video.paused?video.play().catch(()=>{}):video.pause();
$('player-mute').onclick=()=>{video.muted=!video.muted;$('player-mute').textContent=video.muted?'🔇':'🔊';};
$('player-full').onclick=()=>{const box=$('player-stage');document.fullscreenElement?document.exitFullscreen().catch(()=>{}):(box.requestFullscreen?box.requestFullscreen().catch(()=>{}):video.webkitEnterFullscreen?.());};
$('player-back').onclick=()=>seek(position()-10);$('player-fwd').onclick=()=>seek(position()+30);
slider.oninput=()=>{S.drag=true;time.textContent=fmt(Number(slider.value))+' / '+fmt(duration());};
slider.onchange=()=>{S.drag=false;seek(Number(slider.value));};
video.addEventListener('timeupdate',()=>{if(S.mode!=='remux'||S.drag)return;const p=position();slider.value=p;time.textContent=fmt(p)+' / '+fmt(duration());});
video.addEventListener('playing',()=>{say('');toggle.textContent='❚❚';});
video.addEventListener('pause',()=>{toggle.textContent='▶';save();});
video.addEventListener('waiting',()=>say('Puffern …'));
video.addEventListener('ended',()=>{save('ended');if(S.list[S.index+1])playIndex(S.index+1);else say('Ende');});
video.addEventListener('error',()=>{if(!S.info||!video.getAttribute('src'))return;
 // A browser that cannot decode the broadcaster's file (or an unsupported container) gets the ffmpeg stream instead.
 if(S.mode==='direct'&&S.info.ffmpeg&&!S.retried){S.retried=true;const t=video.currentTime||0;startRemux(t);return;}
 say(S.mode==='remux'?'Wiedergabe fehlgeschlagen. Details im Live-Protokoll; häufige Ursache: Stream nicht mehr verfügbar oder Geosperre.':'Diese Datei kann der Browser nicht abspielen.');});
setInterval(()=>{if(dialog.open&&!video.paused)save();},10000);
dialog.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT'&&e.target!==slider)return;if(e.key===' '||e.key==='k'){e.preventDefault();toggle.click();}else if(e.key==='ArrowLeft'&&e.target!==slider){e.preventDefault();seek(position()-10);}else if(e.key==='ArrowRight'&&e.target!==slider){e.preventDefault();seek(position()+10);}else if(e.key==='f'){$('player-full').click();}});
window.addEventListener('pagehide',()=>save());
})();
