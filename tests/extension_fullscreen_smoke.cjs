/* 0.6.46: Hintergrund der Chrome-Erweiterung (background.js) – Fenster auf Vollbild und zurück.
   chrome.* ist nachgestellt; geprüft wird die Logik, nicht Chrome selbst. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../web/browser-extension/chrome/background.js'),'utf8');
const windows={7:{id:7,state:'maximized'},8:{id:8,state:'fullscreen'}},updates=[],session={};
let onMessage,onRemoved,reloaded=0;
const chrome={
  runtime:{lastError:null,reload:()=>reloaded++,onMessage:{addListener:f=>{onMessage=onMessage||[];onMessage.push(f);}},onInstalled:{addListener:()=>{}}},
  storage:{session:{get:(d,cb)=>cb({...d,...JSON.parse(JSON.stringify(session))}),set:(v,cb)=>{Object.assign(session,JSON.parse(JSON.stringify(v)));cb&&cb();}}},
  windows:{get:(id,cb)=>cb(windows[id]),update:(id,v,cb)=>{updates.push([id,v.state]);windows[id].state=v.state;cb&&cb();}},
  tabs:{onRemoved:{addListener:f=>{onRemoved=f;}},query:()=>{}},scripting:{},
};
vm.runInNewContext(source,{chrome,URL,console,setTimeout},{filename:'background.js'});
const send=(type,tab,url)=>onMessage.forEach(f=>f({type},{tab,url:url||'https://www.joyn.de/play/x'}));
const tick=()=>new Promise(r=>setTimeout(r,5));
(async()=>{
  send('fullscreen',{id:1,windowId:7});await tick();
  assert.deepEqual(updates,[[7,'fullscreen']]);
  send('fullscreen',{id:1,windowId:7});await tick();                 // schon Vollbild: nichts doppelt
  assert.equal(updates.length,1);
  send('fullscreen-exit',{id:1,windowId:7});await tick();            // Esc: vorheriger Zustand
  assert.deepEqual(updates[1],[7,'maximized']);
  send('fullscreen',{id:2,windowId:7});await tick();
  onRemoved(2);await tick();                                         // Tab geschlossen: Fenster zurück
  assert.deepEqual(updates.slice(2),[[7,'fullscreen'],[7,'maximized']]);
  send('fullscreen',{id:3,windowId:8});await tick();                 // Fenster war schon im Vollbild: bleibt, wird nie zurückgestellt
  send('fullscreen-exit',{id:3,windowId:8});await tick();onRemoved(3);await tick();
  assert.equal(updates.length,4);
  onRemoved(99);await tick();assert.equal(updates.length,4);         // fremder Tab
  send('fullscreen',undefined);await tick();assert.equal(updates.length,4);   // ohne Tab (z. B. Popup)
  send('reload',{id:5,windowId:7},'http://127.0.0.1:8765/');assert.equal(reloaded,1);   // Selbst-Update bleibt
  send('reload',{id:5,windowId:7},'https://www.joyn.de/');assert.equal(reloaded,1);
  console.log('extension_fullscreen_smoke ok');
})().catch(e=>{console.error(e);process.exit(1);});
