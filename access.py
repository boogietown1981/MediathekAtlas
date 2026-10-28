"""Password login for network (NAS) mode. Desktop mode on 127.0.0.1 does not use it.

The password is stored only as a salted PBKDF2 hash. Until a password exists, a
one-time setup code is written to files the NAS owner can open (data folder and
download share); whoever knows it may set the first password.
"""
import hashlib,hmac,json,os,secrets,threading,time
from pathlib import Path
ITERATIONS=200_000;SESSION_SECONDS=7*86400;MIN_PASSWORD=8
FAILURES=10;FAILURE_WINDOW=600
SETUP_FILE='MediathekAtlas-Einrichtungscode.txt'

def _hash(password,salt,iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),iterations).hex()

class Access:
    def __init__(self,root,setup_dirs=()):
        self.root=Path(root);self.path=self.root/'access.json';self.setup_dirs=[Path(p) for p in setup_dirs if p]
        self.lock=threading.Lock();self.sessions={};self.failures={};self.setup_code=None
        self._import_initial_password()
    def _load(self):
        try:return json.loads(self.path.read_text())
        except (OSError,ValueError):return {}
    def _store(self,data):
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(data));os.chmod(temp,0o600);temp.replace(self.path)
    def configured(self):return bool(self._load().get('hash'))
    def _import_initial_password(self):
        # Written by the Synology install wizard; consumed once, never kept in plain text.
        initial=self.root/'initial-password'
        try:password=initial.read_text().strip()
        except OSError:return
        try:
            if password and not self.configured():self.set_password(password)
        finally:initial.unlink()
    def set_password(self,password):
        if len(password)<MIN_PASSWORD:raise ValueError(f'Passwort muss mindestens {MIN_PASSWORD} Zeichen lang sein')
        salt=secrets.token_hex(16)
        with self.lock:
            self._store({'hash':_hash(password,salt),'salt':salt,'iterations':ITERATIONS,'changed':time.time()})
            self.sessions.clear();self.setup_code=None
        self._remove_setup_files()
    def verify(self,password):
        data=self._load()
        if not data.get('hash'):return False
        return hmac.compare_digest(_hash(password,data['salt'],int(data.get('iterations',ITERATIONS))),data['hash'])
    def setup_locations(self):
        return [str(p/SETUP_FILE) for p in [self.root,*self.setup_dirs]]
    def ensure_setup_code(self):
        """Create the one-time code and return the files it was written to."""
        if self.configured():return []
        with self.lock:
            if not self.setup_code:self.setup_code=secrets.token_hex(4).upper()
            code=self.setup_code
        written=[]
        text=('MediathekAtlas – Einrichtungscode für die erste Anmeldung\n\n'+code+'\n\n'
              'Code auf der Anmeldeseite eingeben und ein eigenes Passwort festlegen.\n'
              'Diese Datei wird danach automatisch gelöscht. Nach einem Neustart des Dienstes gilt ein neuer Code.\n')
        for p in [self.root,*self.setup_dirs]:
            try:
                p.mkdir(parents=True,exist_ok=True);(p/SETUP_FILE).write_text(text);written.append(str(p/SETUP_FILE))
            except OSError:pass
        return written
    def _remove_setup_files(self):
        for p in [self.root,*self.setup_dirs]:
            try:(p/SETUP_FILE).unlink()
            except OSError:pass
    def blocked(self,client):
        now=time.monotonic()
        with self.lock:
            recent=[t for t in self.failures.get(client,[]) if now-t<FAILURE_WINDOW];self.failures[client]=recent
            return len(recent)>=FAILURES
    def _failed(self,client):
        with self.lock:self.failures.setdefault(client,[]).append(time.monotonic())
    def login(self,client,password='',setup_code='',new_password=''):
        """Return a new session token or raise ValueError with a user-facing reason."""
        if self.blocked(client):raise PermissionError('Zu viele Fehlversuche. Bitte in zehn Minuten erneut versuchen.')
        if not self.configured():
            if not self.setup_code or not hmac.compare_digest(setup_code.strip().upper(),self.setup_code):
                self._failed(client);raise ValueError('Einrichtungscode ist falsch')
            self.set_password(new_password)
        elif not self.verify(password):
            self._failed(client);raise ValueError('Passwort ist falsch')
        with self.lock:self.failures.pop(client,None)
        return self.new_session()
    def new_session(self):
        token=secrets.token_urlsafe(32);now=time.time()
        with self.lock:
            self.sessions={k:v for k,v in self.sessions.items() if v>now}
            self.sessions[hashlib.sha256(token.encode()).hexdigest()]=now+SESSION_SECONDS
        return token
    def valid(self,token):
        if not token:return False
        key=hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            expires=self.sessions.get(key)
            if expires and expires>time.time():return True
            self.sessions.pop(key,None);return False
    def logout(self,token):
        if token:
            with self.lock:self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(),None)
    def change_password(self,current,new):
        if not self.verify(current):raise ValueError('Aktuelles Passwort ist falsch')
        self.set_password(new)
        return self.new_session()

def cookie_token(header,name='atlas_session'):
    for part in (header or '').split(';'):
        key,_,value=part.strip().partition('=')
        if key==name:return value
    return ''
