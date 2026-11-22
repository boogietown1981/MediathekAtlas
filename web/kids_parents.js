// 0.6.99: Elternbereich der Kinderecke (kids_rules.py): Altersgrenze FSK 0/6/12, „Wartet auf Freigabe“,
// Freigeben/Sperren je Film oder Serie und Zurücknehmen. Björn 22.11.2026: „im Zweifel nicht, ich gebe dann manuell frei“.
(function(){
const box=$('kids-parents-panel');if(!box)return;
const liveBox=$('kids-live-toggle'),select=$('kids-max-age'),status=$('kids-ages-status'),waitBox=$('kids-waiting'),choiceBox=$('kids-choices'),filter=$('kids-waiting-filter');
let waiting=[];
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
function renderChoices(list){
 choiceBox.replaceChildren();
 if(!list.length){choiceBox.append(el('p','Noch keine Freigaben oder Sperren.','muted'));return;}
 for(const c of list){const row=el('div',undefined,'kids-parents-row');
  row.append(el('strong',c.title||c.id),el('span',(c.kind==='show'?'Serie':'Film')+' · '+(c.choice==='allow'?'freigegeben':'gesperrt'),c.choice==='allow'?'kids-parents-ok':'kids-parents-reason'),el('span',when(c.updated),'muted'),
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
filter.oninput=renderWaiting;
liveBox.onchange=async()=>{liveBox.disabled=true;try{const r=await api('kids-rules',{live:liveBox.checked});notice(r.live?'Kindersender erscheinen in der Kinderecke unter „Fernsehen“.':'Keine Live-Sender in der Kinderecke.');}catch(e){notice(e.message,'error');liveBox.checked=!liveBox.checked;}finally{liveBox.disabled=false;}};
box.addEventListener('toggle',()=>{if(box.open)load().catch(err=>status.textContent=err.message);});
})();
