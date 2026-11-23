// 0.6.99: Elternbereich der Kinderecke (kids_rules.py): Altersgrenze FSK 0/6/12, „Wartet auf Freigabe“,
// Freigeben/Sperren je Film oder Serie und Zurücknehmen; 0.6.113: sichtbare Titel der Kinderecke sperren. Björn 22.11.2026: „im Zweifel nicht, ich gebe dann manuell frei“.
(function(){
const box=$('kids-parents-panel');if(!box)return;
const liveBox=$('kids-live-toggle'),select=$('kids-max-age'),status=$('kids-ages-status'),waitBox=$('kids-waiting'),choiceBox=$('kids-choices'),filter=$('kids-waiting-filter'),visBox=$('kids-visible'),visFilter=$('kids-visible-filter');
let waiting=[],visible=null;
const when=t=>{try{return new Date(t*1000).toLocaleString('de-DE',{dateStyle:'medium',timeStyle:'short'});}catch{return '';}};
function button(text,cls,onclick){const b=el('button',text,cls);b.type='button';b.onclick=onclick;return b;}
async function choose(item,choice,btn){await busy(btn,async()=>{await api('kids-rules',{kind:item.kind,id:item.id,choice,title:item.title});notice(choice==='allow'?'„'+item.title+'“ steht jetzt in der Kinderecke.':choice==='block'?'„'+item.title+'“ bleibt aus der Kinderecke draußen.':'Entscheidung für „'+item.title+'“ zurückgenommen.');await load();});}
function renderWaiting(){
 waitBox.replaceChildren();const q=(filter.value||'').trim().toLocaleLowerCase('de');
 const rows=waiting.filter(w=>!q||String(w.title).toLocaleLowerCase('de').includes(q));
 if(!rows.length){waitBox.append(el('p',waiting.length?'Kein Treffer.':'Nichts wartet auf Freigabe.','muted'));return;}
 for(const w of rows){const row=el('div',undefined,'kids-parents-row');
  row.append(el('strong',w.title+(w.year?' ('+w.year+')':'')),el('span',w.type+(w.works>1&&w.type==='Serie'?' · '+w.works+' Folgen':''),'muted'),el('span',w.reason,'kids-parents-reason'),
   button('Freigeben','primary',e=>choose(w,'allow',e.target)),button('Sperren','',e=>choose(w,'block',e.target)));
  waitBox.append(row);}
}
const SOURCE={mediatheken:'Mediathek',netzkino:'Netzkino',pluto:'Pluto TV',plex:'Plex',toggo:'TOGGO',rakuten:'Rakuten TV',joyn:'Joyn',youtube:'YouTube'};
function renderVisible(){
 visBox.replaceChildren();
 if(visible===null){visBox.append(el('p','Wird geladen …','muted'));return;}
 const q=(visFilter.value||'').trim().toLocaleLowerCase('de');
 if(q.length<2){visBox.append(el('p',visible.length+' Titel in der Kinderecke. Mindestens zwei Buchstaben eingeben, um einen zu finden.','muted'));return;}
 const rows=visible.filter(t=>String(t.title).toLocaleLowerCase('de').includes(q));
 if(!rows.length){visBox.append(el('p','Kein Treffer.','muted'));return;}
 for(const t of rows.slice(0,50)){const row=el('div',undefined,'kids-parents-row'),b=t.block||{};
  row.append(el('strong',t.title+(t.year?' ('+t.year+')':'')),el('span',(t.kind==='series'?'Serie':'Film')+' · '+(t.channel||SOURCE[t.source]||t.source||''),'muted'),
   button('Sperren','',e=>choose({kind:b.kind,id:b.id,title:t.title},'block',e.target).then(loadVisible)));
  visBox.append(row);}
 if(rows.length>50)visBox.append(el('p','Weitere '+(rows.length-50)+' Treffer – Suche genauer eingeben.','muted'));
}
async function loadVisible(){
 try{const d=await api('kids');const cat=d.catalog||{};
  visible=cat.pending&&!(cat.movies||[]).length&&!(cat.series||[]).length?null:[...(cat.movies||[]),...(cat.series||[])].filter(t=>t.block&&t.block.id);}
 catch(e){visible=[];}
 renderVisible();
}
function renderChoices(list){
 choiceBox.replaceChildren();
 if(!list.length){choiceBox.append(el('p','Noch keine Freigaben oder Sperren.','muted'));return;}
 for(const c of list){const row=el('div',undefined,'kids-parents-row');
  row.append(el('strong',c.title||c.id),el('span',(c.kind==='show'?'Serie':c.kind==='tile'?'Plattform-Titel':'Film')+' · '+(c.choice==='allow'?'freigegeben':'gesperrt'),c.choice==='allow'?'kids-parents-ok':'kids-parents-reason'),el('span',when(c.updated),'muted'),
   button('Zurücknehmen','',e=>choose(c,'',e.target)));
  choiceBox.append(row);}
}
async function load(){
 status.textContent='Wird geladen …';
 const d=await api('kids-rules?waiting=1');const s=d.summary||{};
 select.value=String(s.max_age);liveBox.checked=s.live!==false;
 const ages=Object.entries(s.by_age||{}).map(([a,n])=>'FSK '+a+': '+n).join(' · ');
 status.textContent='Altersfreigaben aus Wikidata: '+(s.checked||0)+' erkannte Titel geprüft, '+(s.with_age||0)+' mit FSK'+(ages?' ('+ages+')':'')+'. Das IMDb-Archiv enthält keine Altersfreigaben.'+(s.paused_until?' Abfrage pausiert bis '+when(s.paused_until)+(s.last_error?' ('+s.last_error+')':'')+'.':'');
 waiting=d.waiting||[];renderWaiting();renderChoices(d.choices||[]);
}
select.onchange=async()=>{select.disabled=true;try{const r=await api('kids-rules',{max_age:Number(select.value)});notice('Altersgrenze der Kinderecke: FSK '+r.max_age+'.');await load();}catch(e){notice(e.message,'error');}finally{select.disabled=false;}};
filter.oninput=renderWaiting;visFilter.oninput=renderVisible;
liveBox.onchange=async()=>{liveBox.disabled=true;try{const r=await api('kids-rules',{live:liveBox.checked});notice(r.live?'Kindersender erscheinen in der Kinderecke unter „Fernsehen“.':'Keine Live-Sender in der Kinderecke.');}catch(e){notice(e.message,'error');liveBox.checked=!liveBox.checked;}finally{liveBox.disabled=false;}};
box.addEventListener('toggle',()=>{if(box.open){load().catch(err=>status.textContent=err.message);loadVisible();}});
})();
