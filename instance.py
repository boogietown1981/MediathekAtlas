"""One running server per local catalogue; lock is released by the OS on exit.

0.6.46 (Björn, 20.11.2026: nach „App beenden“ im Browser ließ sich die App nicht mehr starten, bis der
Python-Prozess von Hand beendet war): instance.json nennt jetzt auch den Zustand ('starting', 'running',
'stopping'). Ein zweiter Start (``claim``) öffnet eine gesunde Instanz im Browser, wartet auf eine, die
gerade startet oder herunterfährt, und beendet eine, die nicht mehr antwortet, selbst (erst SIGTERM,
dann hart), bevor er übernimmt. ``exit_guard`` sorgt dafür, dass das Beenden nie hängen bleibt."""
import json,os,signal,subprocess,sys,threading,time,urllib.parse,urllib.request
APP='MediathekAtlas'
STARTING_GRACE=300.0     # eine startende Instanz darf (Migration, externes Laufwerk) so lange brauchen
SILENT_GRACE=12.0        # antwortet eine laufende/endende Instanz so lange nicht, wird sie beendet
EXIT_GUARD=10.0          # so lange darf das Herunterfahren dauern, dann endet der Prozess hart
class Instance:
    def __init__(self,root):
        self.root=root;self.handle=None
    def acquire(self):
        handle=open(self.root/'instance.lock','a+b')
        if os.name=='nt':
            import msvcrt
            handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:handle.close();return False
        else:
            import fcntl
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:handle.close();return False
        self.handle=handle;return True
    def _write(self,data):
        temp=self.root/'instance.json.tmp'
        temp.write_text(json.dumps(data));temp.replace(self.root/'instance.json')
    def publish(self,url,version,state='running'):
        self._write({'url':url,'version':version,'pid':os.getpid(),'state':state,'since':time.time()})
    def mark(self,state,version=''):
        """Zustand der eigenen Instanz festhalten ('starting' vor dem Webserver, 'stopping' beim Beenden)."""
        try:
            data=self.info() if state!='starting' else {}
            if data.get('pid') not in (None,os.getpid()):data={}
            data.update(pid=os.getpid(),state=state,since=time.time())
            if version:data['version']=version
            self._write(data)
        except OSError:pass
    def info(self):
        try:
            data=json.loads((self.root/'instance.json').read_text())
            return data if isinstance(data,dict) else {}
        except (OSError,ValueError):return {}
    def existing(self):
        try:
            data=self.info();url=data['url'];p=urllib.parse.urlsplit(url)
            if p.scheme=='http' and p.hostname=='127.0.0.1' and p.port and p.path in ('','/') and not p.username and not p.query and not p.fragment:return data
        except (OSError,ValueError,KeyError,TypeError):pass
        return {}
    def close(self):
        if self.handle:self.handle.close();self.handle=None

def responds(url,timeout=3.0):
    """Antwortet unter der Adresse ein Webserver? Jede HTTP-Antwort zählt (ältere Stände kennen /api/instance nicht)."""
    try:
        with urllib.request.urlopen(url.rstrip('/')+'/api/instance',timeout=timeout):return True
    except urllib.error.HTTPError:return True
    except Exception:return False

def pid_alive(pid):
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=1:return False
    if os.name=='nt':return bool(_command(pid))
    try:os.kill(pid,0);return True
    except PermissionError:return True
    except OSError:return False

def _command(pid):
    try:
        if os.name=='nt':
            out=subprocess.run(['tasklist','/FI','PID eq %d'%pid,'/FO','CSV','/NH'],capture_output=True,text=True,timeout=10,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout
            return out.strip() if str(pid) in out else ''
        return subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True,timeout=10).stdout.strip()
    except (OSError,subprocess.SubprocessError):return ''

def is_ours(pid,command=_command):
    """Gehört die Prozessnummer (noch) zu MediathekAtlas? Schützt davor, einen fremden Prozess zu beenden,
    der die Nummer inzwischen bekommen hat."""
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=1 or pid==os.getpid():return False
    text=command(pid).casefold()
    return bool(text) and ('server.py' in text or 'mediathekatlas' in text or (os.name=='nt' and 'python' in text))

def terminate(pid,wait=4.0,sleep=time.sleep,alive=pid_alive):
    """Erst höflich (SIGTERM: der Server schließt sauber), dann hart. True, wenn der Prozess weg ist."""
    try:os.kill(pid,signal.SIGTERM)
    except OSError:pass
    deadline=time.monotonic()+wait
    while time.monotonic()<deadline:
        if not alive(pid):return True
        sleep(0.2)
    try:os.kill(pid,getattr(signal,'SIGKILL',signal.SIGTERM))
    except OSError:pass
    deadline=time.monotonic()+3.0
    while time.monotonic()<deadline:
        if not alive(pid):return True
        sleep(0.2)
    return not alive(pid)

def claim(instance,opener=None,managed=False,log=print,sleep=time.sleep,clock=time.monotonic,responds=responds,
          alive=pid_alive,ours=is_ours,kill=terminate,starting_grace=STARTING_GRACE,silent_grace=SILENT_GRACE):
    """Für den Start: 'acquired' (diese Instanz darf laufen), 'reused' (eine gesunde läuft, im Browser
    geöffnet) oder 'failed' (eine andere hält die Sperre und ließ sich nicht beenden)."""
    if instance.acquire():return 'acquired'
    started=clock();told=False;killed=False
    while True:
        info=instance.info();state=info.get('state') or 'running';pid=info.get('pid')
        url=(instance.existing() or {}).get('url')
        if state!='stopping' and url and responds(url):
            if opener:opener(url)
            log('MediathekAtlas läuft bereits und wurde im Browser geöffnet: '+url)
            return 'reused'
        if instance.acquire():
            if told:log('Die vorherige Instanz ist beendet; MediathekAtlas startet neu.')
            return 'acquired'
        waited=clock()-started
        booting=state=='starting' and alive(pid)
        if not told:
            told=True
            log('Eine andere MediathekAtlas-Instanz '+('startet gerade' if booting else 'fährt gerade herunter' if state=='stopping' else 'antwortet nicht')+'; warte …')
        if waited>(starting_grace if booting else silent_grace):
            if killed or managed or not ours(pid):
                log('MediathekAtlas läuft bereits (Prozess %s), antwortet aber nicht und ließ sich nicht automatisch beenden. Bitte den Computer neu starten oder den Prozess beenden.'%(pid or 'unbekannt'))
                return 'failed'
            log('Die vorherige Instanz (Prozess %d) antwortet nicht mehr und wird beendet.'%pid)
            kill(pid);killed=True;started=clock()-max(0.0,silent_grace-6.0)   # danach noch gut 6 s auf die Sperre warten
            continue
        sleep(0.5)

def exit_guard(code=0,seconds=EXIT_GUARD,dump=None,exit=os._exit,start=True):
    """Beendet den Prozess nach ``seconds`` hart, falls das Herunterfahren hängt (blockierter Thread,
    hängende Verbindung). Vorher schreibt ``dump`` (Pfad) auf, wo die Threads standen (für die Diagnose)."""
    def run():
        time.sleep(seconds)
        if dump:
            try:
                import faulthandler
                with open(dump,'w',encoding='utf-8') as f:
                    f.write('MediathekAtlas: Herunterfahren dauerte länger als %d s, Prozess wird beendet. Stand der Threads:\n'%seconds);f.flush()
                    faulthandler.dump_traceback(file=f,all_threads=True)
            except Exception:pass
        exit(code() if callable(code) else code)
    t=threading.Thread(target=run,daemon=True,name='exit_guard')
    if start:t.start()
    return t

def leave(code=0,exit=os._exit):
    """Sofort und endgültig beenden: Ausgaben schreiben, dann ohne die Aufräumrunde des Interpreters
    (die auf Hintergrund-Threads warten kann) hinaus."""
    for stream in (sys.stdout,sys.stderr):
        try:stream.flush()
        except Exception:pass
    exit(code)
