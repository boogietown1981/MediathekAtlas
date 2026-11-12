/* Zero-dependency smoke test of Netzkino's tab initialization & failure summary.
 * The original UI is untouched; this is an in-memory DOM fixture. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(require('path').join(__dirname,'../web/netzkino.js'),'utf8');
function element(){return {textContent:'',value:'',dataset:{},hidden:false,disabled:false,checked:false,
  children:[],classList:{toggle(){}},listeners:{},addEventListener(k,f){this.listeners[k]=f;},
  append(...xs){this.children.push(...xs);},replaceChildren(...xs){this.children=xs;},
  querySelector(){return element();}}}
const ids=new Map();function get(id){if(!ids.has(id))ids.set(id,element());return ids.get(id)}
const tab=element(), sidebar=element();
const document={readyState:'complete',getElementById:get,
  querySelector(sel){return sel.includes('data-view')?sidebar:null},
  querySelectorAll(sel){return sel.includes('data-platform')?[tab]:[]},
  createElement(){return element()}};
const window={api:async () => ({items:[],total:449,status:{catalog_count:449,
      last_result:'partial',categories_checked:29,categories_total:29,category_errors:4,categories_empty:3,
      snapshot_seed_count:449,last_success:1794390000,manual_count:0}})};
get('portals').dataset.platform='overview';
const context={window,document,URLSearchParams,setTimeout:(fn,delay)=>{if(delay===0)Promise.resolve().then(fn);return 1},
  clearTimeout:()=>{},confirm:()=>true,console};
vm.runInNewContext(source,context,{filename:'netzkino.js'});
assert.equal(typeof window.MediathekAtlasNetzkino.refresh,'function');
get('portals').dataset.platform='netzkino';
(async()=>{
  assert.equal(typeof tab.listeners.click,'function');
  tab.listeners.click();
  await Promise.resolve();
  await window.MediathekAtlasNetzkino.refresh();
  assert.match(get('netzkino-sync-summary').textContent,/449 Katalogtitel/);
  assert.match(get('netzkino-sync-summary').textContent,/Teilabgleich/);
  assert.match(get('netzkino-sync-summary').textContent,/Fehler 4/);
  window.api=async()=>{throw new Error('API lokal nicht erreichbar')};
  await window.MediathekAtlasNetzkino.refresh();
  assert.match(get('netzkino-sync-summary').textContent,/API lokal nicht erreichbar/);
  assert.equal(get('netzkino-sync-summary').dataset.phase,'ui-error');
  console.log('Netzkino JS UI: status, partial and inline error: OK');
})().catch(e=>{console.error(e);process.exitCode=1});
