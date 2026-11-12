/* Netzkino offline downloads (0.5.32): one shared download queue with the
   Mediathek videos; ytdl-nightly resolves the file, 30 days offline use. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const elt=(tag,label,cls)=>{const n=document.createElement(tag);if(label!==undefined)n.textContent=label;if(cls)n.className=cls;return n;};
  const mib=n=>(Number(n||0)/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MiB';
  const labels={queued:'Vorgemerkt',downloading:'Lädt',tagging:'MKV wird erstellt',done:'Offline verfügbar',error:'Fehler',
    cancelled:'Abgebrochen',interrupted:'Unterbrochen',expired:'Abgelaufen und entfernt',removed:'Gelöscht'};
  const date=ts=>new Date(ts*1000).toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric'});
  let current=null,serial=0,timer=null;
  const status=text=>{const s=$('atlas-nk-download-status');if(s)s.textContent=text;};
  function actionButton(label,job,action,expected){
    const b=elt('button',label);b.type='button';
    b.onclick=async()=>{
      b.disabled=true;
      try{await window.api('netzkino-download-action',{id:job.id,action});await refresh(expected);}
      catch(e){status(e.message);}
      finally{b.disabled=false;}
    };
    return b;
  }
  async function refresh(expected){
    const result=await window.api('netzkino-downloads?id='+encodeURIComponent(expected));
    if(current!==expected)return;
    const host=$('atlas-nk-download-jobs');if(!host)return;
    host.replaceChildren();
    const add=$('atlas-nk-offline-add');
    if(add){
      const ytdl=result.ytdl||{};
      const active=(result.items||[]).some(r=>['queued','downloading','tagging','done'].includes(r.state)&&r.license==='netzkino_offline');
      add.disabled=active||ytdl.ok===false;
      add.title=ytdl.ok===false?'ytdl-nightly fehlt in dieser Installation':active?'Bereits eingereiht oder offline verfügbar':'';
    }
    for(const r of result.items||[]){
      const row=elt('div',undefined,'nk-licensed-job nk-offline-job nk-offline-'+r.state);
      row.append(elt('strong',(labels[r.state]||r.state)+' · '+r.target_name));
      if(r.state==='downloading'){
        const p=elt('progress');p.max=r.total||1;if(r.total)p.value=r.received||0;row.append(p);
        row.append(elt('small',mib(r.received)+(r.total?' / '+mib(r.total):'')));
      }
      if(r.state==='done'&&r.offline_until)
        row.append(elt('small','Offline nutzbar bis '+date(r.offline_until)+' · noch '+r.days_left+(r.days_left===1?' Tag':' Tage'),r.days_left<=3?'nk-warning':'muted'));
      if(r.state==='done'&&r.license==='licensed_file')row.append(elt('small','Eigene Lizenzdatei · kein Ablauf','muted'));
      if(r.error)row.append(elt('small','Fehler: '+r.error,'nk-warning'));
      if(['queued','downloading','tagging'].includes(r.state))row.append(actionButton('Abbrechen',r,'cancel',expected));
      if(['error','cancelled','interrupted'].includes(r.state)){
        const retry=elt('button','Erneut versuchen');retry.type='button';
        retry.onclick=async()=>{retry.disabled=true;try{await window.api('retry',{id:r.id});await refresh(expected);}catch(e){status(e.message);}finally{retry.disabled=false;}};
        row.append(retry);
      }
      if(r.state==='done')row.append(actionButton('Jetzt löschen',r,'delete',expected));
      host.append(row);
    }
  }
  async function mount(itemId){
    current=itemId;const call=++serial;
    if(timer)clearInterval(timer);
    const panel=$('atlas-nk-downloads');const form=$('atlas-nk-download-form');const add=$('atlas-nk-offline-add');
    if(panel)panel.open=false;
    if(form)form.reset();
    status('Netzkino-Titel dürfen heruntergeladen und 30 Tage offline genutzt werden. Danach entfernt MediathekAtlas die Datei automatisch.');
    if(add)add.onclick=async()=>{
      if(current!==itemId)return;
      add.disabled=true;status('Titel wird in die Download-Warteschlange aufgenommen …');
      try{
        const result=await window.api('netzkino-download-add',{id:itemId});
        if(call!==serial)return;
        status(result.created?'Eingereiht. Gespeichert wird wie bei Mediathek-Videos: '+String(result.target||'').split(/[\\/]/).slice(-2).join('/'):
          'Dieser Titel ist bereits eingereiht oder offline verfügbar.');
        await refresh(itemId);
      }catch(e){if(call===serial){status('Kein Download gestartet: '+e.message);add.disabled=false;}}
    };
    if(form)form.onsubmit=async e=>{
      e.preventDefault();
      if(current!==itemId||!form.reportValidity())return;
      const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
      status('Berechtigung und Datei-Link werden geprüft …');
      try{
        const result=await window.api('netzkino-download-add',{
          id:itemId,
          file_url:$('atlas-nk-download-url').value.trim(),
          rights_basis:$('atlas-nk-download-basis').value,
          rights_note:$('atlas-nk-download-note').value.trim(),
          confirmed:$('atlas-nk-download-confirm').checked
        });
        if(call!==serial)return;
        status(result.created?'Lizenzierte Datei in die Download-Warteschlange aufgenommen.':'Diese Datei ist bereits vorgemerkt.');
        form.reset();await refresh(itemId);
      }catch(e){if(call===serial)status('Kein Download gestartet: '+e.message);}
      finally{submit.disabled=false;}
    };
    try{await refresh(itemId);}catch(e){if(call===serial)status('Downloadstatus nicht verfügbar: '+e.message);}
    timer=setInterval(()=>{
      if(current===itemId && $('atlas-netzkino-detail')?.open)refresh(itemId).catch(()=>{});
    },3000);
  }
  $('atlas-nk-close')?.addEventListener('click',()=>{current=null;serial++;if(timer)clearInterval(timer);timer=null;});
  window.AtlasNetzkinoDownloads={mount};
})();
