/* Rights-first Netzkino download management. This does NOT extract Netzkino streams. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const elt=(tag,label,cls)=>{const n=document.createElement(tag);if(label!==undefined)n.textContent=label;if(cls)n.className=cls;return n;};
  const fmt=n=>Number.isFinite(Number(n))?(Number(n)/1048576).toLocaleString('de-DE',{maximumFractionDigits:1})+' MiB':'–';
  const labels={queued:'Vorgemerkt',running:'Lädt',paused:'Pausiert',complete:'Fertig',error:'Fehler',cancelled:'Abgebrochen'};
  let current=null,serial=0,timer=null;
  async function refresh(expected){
    const result=await window.api('netzkino-downloads');
    if(current!==expected)return;
    const host=$('atlas-nk-download-jobs');if(!host)return;
    host.replaceChildren();
    const rows=(result.items||[]).filter(r=>r.netzkino_id===expected);
    if(!rows.length){host.append(elt('p','Keine berechtigten Datei-Downloads für diesen Titel.','muted'));return;}
    for(const r of rows){
      const row=elt('div',undefined,'nk-licensed-job');
      const title=elt('strong',(labels[r.state]||r.state)+' · '+r.target_name);
      row.append(title);
      row.append(elt('small',r.bytes_total?fmt(r.bytes_done)+' / '+fmt(r.bytes_total):fmt(r.bytes_done)));
      if(r.bytes_total){const progress=elt('progress');progress.max=r.bytes_total;progress.value=r.bytes_done;row.append(progress);}
      if(r.error_code)row.append(elt('small','Fehler: '+r.error_code,'nk-warning'));
      const mode=r.state==='paused'||r.state==='error'?'resume':['running','queued'].includes(r.state)?'pause':null;
      if(mode){
        const btn=elt('button',mode==='pause'?'Pausieren':'Fortsetzen');btn.type='button';
        btn.onclick=async()=>{
          btn.disabled=true;
          try{await window.api('netzkino-download-action',{id:r.id,action:mode});await refresh(expected);}
          catch(e){$('atlas-nk-download-status').textContent=e.message;}
          finally{btn.disabled=false;}
        };
        row.append(btn);
      }
      if(['queued','running','paused','error'].includes(r.state)) {
        const cancel=elt('button','Abbrechen');cancel.type='button';
        cancel.onclick=async()=>{
          cancel.disabled=true;
          try{await window.api('netzkino-download-action',{id:r.id,action:'cancel'});await refresh(expected);}
          catch(e){$('atlas-nk-download-status').textContent=e.message;}
          finally{cancel.disabled=false;}
        };
        row.append(cancel);
      }
      host.append(row);
    }
  }
  async function mount(itemId){
    current=itemId;const call=++serial;
    if(timer)clearInterval(timer);
    const panel=$('atlas-nk-downloads');const form=$('atlas-nk-download-form');
    if(!panel||!form)return;
    panel.open=false;
    form.reset();
    $('atlas-nk-download-status').textContent='Nur mit gesonderter Erlaubnis zum Datei-Download. Netzkino-Streaming/Plus allein berechtigt nicht dazu.';
    form.onsubmit=async e=>{
      e.preventDefault();
      if(current!==itemId||!form.reportValidity())return;
      const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
      $('atlas-nk-download-status').textContent='Berechtigung und Datei-Link werden geprüft …';
      try{
        const result=await window.api('netzkino-download-add',{
          id:itemId,
          file_url:$('atlas-nk-download-url').value.trim(),
          rights_basis:$('atlas-nk-download-basis').value,
          rights_note:$('atlas-nk-download-note').value.trim(),
          confirmed:$('atlas-nk-download-confirm').checked
        });
        if(call!==serial)return;
        $('atlas-nk-download-status').textContent=result.created?
          'Lizenzierte Datei in die separate Downloadwarteschlange aufgenommen.':'Diese Datei ist bereits vorgemerkt.';
        form.reset();await refresh(itemId);
      }catch(e){if(call===serial)$('atlas-nk-download-status').textContent='Kein Download gestartet: '+e.message;}
      finally{submit.disabled=false;}
    };
    try{await refresh(itemId);}catch(e){if(call===serial)$('atlas-nk-download-status').textContent='Downloadstatus nicht verfügbar: '+e.message;}
    timer=setInterval(()=>{
      if(current===itemId && $('atlas-netzkino-detail')?.open && panel.open)
        refresh(itemId).catch(()=>{});
    },3000);
  }
  $('atlas-nk-close')?.addEventListener('click',()=>{current=null;serial++;if(timer)clearInterval(timer);timer=null;});
  window.AtlasNetzkinoDownloads={mount};
})();
