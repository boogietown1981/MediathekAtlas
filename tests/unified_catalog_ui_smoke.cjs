'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const path=require('path');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.dataset={};this.style={};this.className='';this.hidden=false;this.value='';this.textContent='';this.attributes={};this.handlers={};this.disabled=false;this.parentElement=null;this.classList={toggle:(name,on)=>{if(on)this.className+=' '+name;else this.className=this.className.replace(name,'');}};}
  append(...children){for(const child of children){this.children.push(child);child.parentElement=this;}}
  replaceChildren(...children){this.children=[];this.append(...children);}
  addEventListener(kind,handler){this.handlers[kind]=handler;}
  setAttribute(k,v){this.attributes[k]=v;}
  querySelector(sel){if(sel==='.atlas-source-switch')return this.children.find(x=>x.className==='atlas-source-switch')||null;return null;}
  click(){if(this.onclick)this.onclick(); if(this.handlers.click)this.handlers.click({});}
}
const elements={};const ids=['discover','atlas-source-content','atlas-cross-title','atlas-cross-back-series','atlas-cross-open-portal','atlas-cross-items','atlas-cross-status','atlas-cross-page','atlas-cross-prev','atlas-cross-next','atlas-cross-genre','atlas-cross-query','atlas-cross-search','atlas-cross-sort','atlas-cross-reset'];
for(const id of ids)elements[id]=new Element();
const switcher=new Element();switcher.className='atlas-source-switch';
const legacy=new Element();legacy.id='legacy-catalog';
elements.discover.append(switcher,elements['atlas-source-content'],legacy);
const sourceTabs=['all','mediatheken','netzkino'].map(value=>{const x=new Element('button');x.dataset.catalogSource=value;return x;});
const kindTabs=['movies','series'].map(value=>{const x=new Element('button');x.dataset.crossKind=value;return x;});
let requests=[];let details=[];
const fakeApi=async url=>{
 if(url==='film-platforms')return {film_platforms:[]};
 requests.push(url);
 if(url==='catalog-tree')return{tree:[{genre:'Drama'},{genre:'Action'}]};
 if(url.startsWith('catalog?'))return {total:1,items:[{work_id:'m1',metadata:{title:'ARD Beitrag',kind:'movie',year:2019,genres:['Drama']},source:{title:'ARD Beitrag'},available:true}]};
 if(url.startsWith('netzkino-grouped?')) {
  const q=new URLSearchParams(url.split('?')[1]);
  if(q.get('view')==='episodes')return {total:1,items:[{id:'a'.repeat(32),title:'Serie Staffel 1 - 1. Pilot',media_type:'episode',genres:'Drama',season:1,episode:1}],genres:['drama']};
  if(q.get('view')==='series')return {total:1,items:[{id:'series-test',series_key:'series-'+('a'.repeat(24)),title:'Eine Serie',media_type:'series',episode_count:1,genres:'Drama'}],genres:['drama']};
  return {total:1,items:[{id:'b'.repeat(32),title:'Netzkino Film',media_type:'movie',genres:'Action'}],genres:['action']};
 }
 throw new Error('Unexpected request: '+url);
};
const document={getElementById:id=>elements[id]||null,createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='[data-catalog-source]'?sourceTabs:selector==='[data-cross-kind]'?kindTabs:[],querySelector:()=>null};
// Long polling timers (portal overview) must not keep the test process alive.
const shortTimeout=(fn,ms)=>ms>1000?0:setTimeout(fn,ms);
const context={setTimeout:shortTimeout,clearTimeout:id=>id&&clearTimeout(id),document,window:{api:fakeApi,AtlasNetzkinoDetail:{open:id=>details.push(id)}},URLSearchParams,console};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/unified_catalog.js'),'utf8'),context);
const settle=()=>new Promise(resolve=>setTimeout(resolve,20));
(async()=>{
 await settle();
 assert.strictEqual(elements['atlas-catalog-advanced'],undefined); // stub does not register dynamic IDs
 assert.strictEqual(legacy.parentElement.tag,'details','legacy catalogue must survive as advanced controls');
 assert.strictEqual(elements.discover.dataset.source,'mediatheken');
 assert.ok(elements['atlas-cross-items'].children.some(c=>c.tag==='article'));
 sourceTabs[0].click();await settle();
 assert.ok(requests.some(u=>u.startsWith('netzkino-grouped?')),'combined view must include Netzkino');
 assert.ok(requests.some(u=>u.startsWith('catalog?')),'combined view must include Mediatheken');
 assert.strictEqual(elements['atlas-cross-items'].children.filter(c=>c.tag==='article').length,2);
 sourceTabs[2].click();kindTabs[1].click();await settle();
 const card=elements['atlas-cross-items'].children.find(c=>c.tag==='article');
 const text=card.children[1];const action=text.children.find(x=>x.className==='atlas-uc-actions').children[0];action.click();await settle();
 assert.ok(requests.some(u=>u.includes('view=episodes')),'series should show episodes inline');
 assert.strictEqual(elements['atlas-cross-back-series'].hidden,false);
 assert.strictEqual(details.length,0);
 console.log('Unified 0.5.31.8 UI: source switch, combined cards, legacy retention and inline series passed');
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
