/* 0.5.91: direkter Player-Link und Autostart-Kennung (web/direct_start.js), ohne Abhängigkeiten. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../web/direct_start.js'),'utf8');
const store=new Map();
const localStorage={getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v))};
const window={};
vm.runInNewContext(source,{window,localStorage,URL,setTimeout,console},{filename:'direct_start.js'});
const D=window.AtlasDirect,M='#mediathekatlas-autostart';
// Joyn: Detailseite -> Player (Routen PLAYER_MOVIE, PLAYER_SERIES, PLAYER_COMPILATION)
assert.equal(D.href('joyn','https://www.joyn.de/filme/abenteuer-portugal'),'https://www.joyn.de/play/filme/abenteuer-portugal'+M);
assert.equal(D.href('joyn','https://www.joyn.de/serien/navy-cis/1-1-yankee-white'),'https://www.joyn.de/play/serien/navy-cis/1-1-yankee-white'+M);
assert.equal(D.href('joyn','https://www.joyn.de/compilation/best-of/1-2-teil'),'https://www.joyn.de/play/compilation/best-of/1-2-teil'+M);
// Serie selbst, Sender und Live bleiben, bekommen aber die Kennung
assert.equal(D.href('joyn','https://www.joyn.de/serien/navy-cis'),'https://www.joyn.de/serien/navy-cis'+M);
assert.equal(D.href('joyn','https://www.joyn.de/play/live-tv'),'https://www.joyn.de/play/live-tv'+M);
assert.equal(D.href('joyn','https://www.joyn.de/play/filme/x'),'https://www.joyn.de/play/filme/x'+M);
// Rakuten, TOGGO, JustWatch: Adresse bleibt, Kennung kommt dazu, Abfrage bleibt erhalten
assert.equal(D.href('rakuten','https://www.rakuten.tv/de/movies/der-film'),'https://www.rakuten.tv/de/movies/der-film'+M);
assert.equal(D.href('toggo','https://www.toggo.de/videos/serien/x/folge/y'),'https://www.toggo.de/videos/serien/x/folge/y'+M);
assert.equal(D.href('justwatch','https://www.justwatch.com/de/film/x?package=jwt'),'https://www.justwatch.com/de/film/x?package=jwt'+M);
// Fremde Hosts, andere Quellen, unsichere Adressen bleiben unverändert
assert.equal(D.href('joyn','https://evil.example/filme/x'),'https://evil.example/filme/x');
assert.equal(D.href('youtube','https://www.youtube.com/watch?v=abcdefghijk'),'https://www.youtube.com/watch?v=abcdefghijk');
assert.equal(D.href('rakuten','http://www.rakuten.tv/de/movies/x'),'http://www.rakuten.tv/de/movies/x');
assert.equal(D.href('joyn','javascript:alert(1)'),'javascript:alert(1)');
assert.equal(D.href('joyn',''),'');
assert.equal(D.href('joyn',undefined),undefined);
// Schalter aus: alles wie vor 0.5.91
D.setEnabled(false);
assert.equal(D.href('joyn','https://www.joyn.de/filme/x'),'https://www.joyn.de/filme/x');
D.setEnabled(true);
assert.equal(D.href('joyn','https://www.joyn.de/filme/x'),'https://www.joyn.de/play/filme/x'+M);
// Hosts der Oberfläche = Hosts der Erweiterung
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../web/browser-extension/chrome/manifest.json'),'utf8'));
const matches=manifest.content_scripts[0].matches.map(m=>new URL(m.replace('*','x')).hostname).sort();
assert.deepEqual(Object.values(D.HOSTS).flat().sort(),matches);
console.log('direct_start_smoke ok');
