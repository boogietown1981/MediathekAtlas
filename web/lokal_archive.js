// 0.6.151: Lokale Filmarchive auf Ordnern und Freigaben (lokal.py).
// Björn (26.11.2026): Filmarchive auf Shares einbinden; vorhandene NFO-Dateien gleich nutzen, sonst Dateinamen
// einlesen und über die Erkennung zuordnen. Einstellungen → „Lokale Filmarchive“: Ordner (einer je Zeile),
// Speichern & einlesen, Jetzt einlesen, Stand je Ordner. Die Titel erscheinen im Katalog unter „Lokales Archiv“.
(function(){
const card=$('lokal-archive-panel');
if(!card)return;
let timer=0;
const num=n=>Number(n||0).toLocaleString('de-DE');
const when=ts=>ts?new Date(ts*1000).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'noch nie';
function render(d){
 const box=$('lokal-archive-dirs');
 if(box&&document.activeElement!==box&&!box.dataset.dirty)box.value=(d.dirs||[]).join('\n');
 const status=$('lokal-archive-status');
 const total=[d.movies?num(d.movies)+' Filme':'',d.series?num(d.series)+' Serien mit '+num(d.episodes)+' Folgen':'',
  d.with_nfo?num(d.with_nfo)+' mit NFO-Datei':'',d.offline?num(d.offline)+' gerade nicht erreichbar':''].filter(Boolean);
 status.textContent=d.running?'Wird eingelesen …':!(d.dirs||[]).length?'Noch kein Archivordner eingetragen.':
  (total.length?total.join(' · '):'Noch keine Videodateien gefunden.')+' · zuletzt eingelesen '+when(d.last_attempt)+
  (d.last_error?' · Fehler: '+d.last_error:'');
 const list=$('lokal-archive-folders');list.replaceChildren();
 for(const f of d.folders||[]){
  const li=el('li',undefined,'lokal-folder'+(f.reachable?'':' lokal-folder-offline'));
  li.append(el('strong',f.folder));
  li.append(el('span',' · '+(f.reachable?[num(f.files)+' Videos',f.new?num(f.new)+' neu':'',f.changed?num(f.changed)+' geändert':'',
   f.gone?num(f.gone)+' entfernt':'',f.small?num(f.small)+' kleine Videos unter 20 MB übergangen (Vorschauen/Beispiele)':'',f.incomplete?'nicht fertig (Zeitbudget), wird fortgesetzt':''].filter(Boolean).join(' · '):
   'nicht erreichbar – Titel bleiben erhalten und sind als offline markiert'),'muted'));
  list.append(li);}
 clearTimeout(timer);if(d.running&&card.open)timer=setTimeout(load,3000);}
async function load(){try{render(await api('lokal'));}catch(e){$('lokal-archive-status').textContent=e.message;}}
$('lokal-archive-dirs')?.addEventListener('input',e=>{e.target.dataset.dirty='1';});
$('lokal-archive-save')?.addEventListener('click',e=>busy(e.currentTarget,async()=>{
 const box=$('lokal-archive-dirs');const d=await api('lokal-dirs',{dirs:box.value});delete box.dataset.dirty;render(d);
 notice(d.dirs.length?'Archivordner gespeichert, Einlesen läuft im Hintergrund.':'Keine Archivordner mehr eingetragen.');
 window.AtlasUnified?.refresh?.();}));
$('lokal-archive-scan')?.addEventListener('click',e=>busy(e.currentTarget,async()=>{render(await api('lokal-scan',{}));notice('Einlesen gestartet.');}));
card.addEventListener('toggle',()=>{if(card.open)load();});
window.AtlasLokal={reload:load};
})();
