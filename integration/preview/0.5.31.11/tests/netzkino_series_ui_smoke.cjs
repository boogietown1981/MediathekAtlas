/* Ensure separate media tabs, series consolidation & original episode links are reachable. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'../web/netzkino.js'),'utf8');
function element(){return {tagName:'',textContent:'',value:'',dataset:{},hidden:false,
  disabled:false,checked:false,children:[],classList:{toggle(){}},handlers:{},
  append(...children){this.children.push(...children);},prepend(...children){this.children.unshift(...children);},
  replaceChildren(...children){this.children=children;},addEventListener(k,f){this.handlers[k]=f;},
  querySelector(){return element();},onclick:null};}
const fields=new Map();function get(id){if(!fields.has(id))fields.set(id,element());return fields.get(id);}
const tab=element(),sidebar=element();let calls=[];
const group={id:'series-a01234567890123456789012',series_key:'series-a01234567890123456789012',
  title:'Acapulco H.E.A.T.',media_type:'series',kind:'series',episode_count:20,seasons:[1],
  numbering_gaps:[{season:1,episodes:[3,4]}],poster:'',year:1993,series_url:'',updated:2};
const episode={id:'x',title:'Acapulco H.E.A.T. Staffel 1 - 1. Eine Folge',
  media_type:'episode',kind:'movie',url:'https://www.netzkino.de/details/episode-1',
  season:1,episode:1,origin:'catalog',year:1993};
const window={api:async p=>{calls.push(p); const view=new URLSearchParams(p.split('?')[1]||'').get('view');
    return {items:view==='series'?[group]:view==='episodes'?[episode]:[],total:view==='series'||view==='episodes'?1:0,
      counts:{movies:418,series:11,episodes:22},series:view==='episodes'?group:null,
      status:{catalog_count:449,last_result:'partial',categories_checked:14,categories_total:29,
        category_errors:0,manual_count:0,last_success:1794390000}};
}};
const document={readyState:'complete',getElementById:get,
  querySelector(s){return s.includes('data-view')?sidebar:null;},
  querySelectorAll(s){return s.includes('data-platform')?[tab]:[];},
  createElement(t){const e=element();e.tagName=t;return e;}};
get('portals').dataset.platform='netzkino';
const c={window,document,URLSearchParams,setTimeout:()=>1,clearTimeout:()=>{},confirm:()=>true,console};
vm.runInNewContext(src,c,{filename:'netzkino.js'});
(async()=>{
 const refresh=window.MediathekAtlasNetzkino.refresh;
 await refresh();
 assert.match(get('netzkino-view-movies').textContent,/418/);
 assert.match(get('netzkino-view-series').textContent,/11/);
 get('netzkino-view-series').onclick(); await refresh();
 assert.equal(get('netzkino-items').children.length,1);
 const card=get('netzkino-items').children[0];
 const actions=card.children.find(x=>x.children.some(y=>y.textContent==='Folgen anzeigen (20)'));
 assert(actions,'series-card lacks an episode button');
 assert(card.children.some(x=>x.classList && /Nummerierungslücken/.test(x.textContent)));
 actions.children[0].onclick(); await refresh();
 assert(calls.some(x=>x.includes('view=episodes')));
 assert.match(get('netzkino-series-heading').textContent,/20 Folgen/);
 assert.equal(get('netzkino-items').children[0].children.find(x=>x.tagName==='h3').textContent,episode.title);
 get('netzkino-back-series').onclick();await refresh();
 assert(calls[calls.length-1].includes('view=series'));
 console.log('Netzkino movie/series/episode UI smoke: OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
