// 0.5.56: Datenbanksicherungen (aus ArchiveMedia v0.10.53). Mehrfachauswahl, zweifache Löschbestätigung.
(function(){
const box=$('backup-panel');if(!box)return;
const list=$('backup-list'),info=$('backup-status'),del=$('backup-delete'),make=$('backup-create');
let rows=[],polling=null;
function mb(n){return (Number(n||0)/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MB';}
function when(iso){try{return new Date(iso).toLocaleString('de-DE',{dateStyle:'medium',timeStyle:'short'});}catch{return iso;}}
function selected(){return rows.filter(r=>r.box.checked).map(r=>({name:r.item.name,fingerprint:r.item.fingerprint}));}
function sync(){const n=selected().length;del.disabled=!n;del.textContent=n?n+' Sicherung'+(n>1?'en':'')+' löschen':'Ausgewählte löschen';}
async function load(){
 const d=await api('backups');rows=[];list.replaceChildren();
 const st=d.state||{};
 info.textContent=(st.phase==='running'?'Sicherung läuft · '+Math.round((st.progress||0)*100)+' % · ':st.phase==='failed'?'Letzte Sicherung fehlgeschlagen: '+st.error+' · ':'')+d.count+' Sicherungen · '+mb(d.total_bytes)+' · automatisch alle '+d.interval_days+' Tage, '+d.auto_keep+' automatische bleiben erhalten';
 if(!d.backups.length)list.append(el('p','Noch keine Sicherung vorhanden.','muted'));
 for(const b of d.backups){const row=el('label',undefined,'backup-row'),cb=el('input');cb.type='checkbox';cb.onchange=sync;row.append(cb,el('strong',when(b.modified_utc)),el('span',b.automatic?'automatisch':'eigene','backup-kind'+(b.automatic?'':' own')),el('span',mb(b.size_bytes),'muted'),el('code',b.name));list.append(row);rows.push({box:cb,item:b});}
 if(d.reappeared?.length)list.append(el('p','Erneut aufgetaucht nach dem Löschen: '+d.reappeared.join(', '),'notice-error'));
 sync();
 clearTimeout(polling);if(st.phase==='running')polling=setTimeout(()=>load().catch(()=>{}),1500);
}
make.onclick=e=>busy(e.target,async()=>{await api('backup-create',{});notice('Sicherung gestartet. Die App bleibt währenddessen nutzbar.');setTimeout(()=>load().catch(()=>{}),800);});
del.onclick=e=>{const picked=selected();if(!picked.length)return;const typed=prompt('Zum Löschen von '+picked.length+' Sicherung(en) bitte BACKUP LÖSCHEN eingeben. Die aktive Datenbank bleibt unberührt.');if(typed!=='BACKUP LÖSCHEN'){notice('Nicht gelöscht: Bestätigung fehlt.');return;}busy(e.target,async()=>{const r=await api('backup-delete',{backups:picked,confirm:typed});notice(r.deleted_count+' Sicherung(en) gelöscht, '+mb(r.freed_bytes)+' frei.'+(r.warning?' Hinweis: '+r.warning:''));await load();});};
box.addEventListener('toggle',()=>{if(box.open)load().catch(err=>info.textContent=err.message);});
})();
