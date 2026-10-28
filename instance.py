"""One running server per local catalogue; lock is released by the OS on exit."""
import json,os,time,urllib.parse
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
    def publish(self,url,version):
        temp=self.root/'instance.json.tmp'
        temp.write_text(json.dumps({'url':url,'version':version,'pid':os.getpid()}));temp.replace(self.root/'instance.json')
    def existing(self):
        try:
            data=json.loads((self.root/'instance.json').read_text());url=data['url'];p=urllib.parse.urlsplit(url)
            if p.scheme=='http' and p.hostname=='127.0.0.1' and p.port and p.path in ('','/') and not p.username and not p.query and not p.fragment:return data
        except (OSError,ValueError,KeyError,TypeError):pass
        return {}
    def close(self):
        if self.handle:self.handle.close();self.handle=None
