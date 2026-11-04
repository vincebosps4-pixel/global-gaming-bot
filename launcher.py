"""Windows-friendly supervisor. Installs only tested releases from one pinned repo."""
from __future__ import annotations

import hashlib
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

from instance_lock import InstanceLock

REPO='vincebosps4-pixel/global-gaming-bot'
ROOT=Path(__file__).resolve().parent
MAX_ZIP=8*1024*1024
ALLOWED={'bot.py','community.py','storage.py','instance_lock.py','launcher.py','setup_windows.py',
         'requirements.txt','VERSION','README.md','LEESMIJ.txt','.env.example','.gitignore','.dockerignore',
         'Dockerfile','START-HIER.cmd','START-BOT.cmd','STOP-BOT.cmd','STATUS.cmd',
         'test_bot.py','test_community.py','test_launcher.py','bundle.py'}
LOG=logging.getLogger('supervisor')


def version_tuple(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+',value):
        raise ValueError('Invalid release version.')
    return tuple(map(int,value.split('.')))


def download(url,limit):
    req=urllib.request.Request(url,headers={'User-Agent':'GlobalGamingUpdater/1.0','Accept':'application/vnd.github+json' if 'api.github.com' in url else 'application/octet-stream'})
    with urllib.request.urlopen(req,timeout=30) as response:
        raw=response.read(limit+1)
    if len(raw)>limit:
        raise ValueError('Download exceeded the size limit.')
    return raw


def checked_files(raw,expected_hash,version):
    if not re.fullmatch(r'[0-9a-f]{64}',expected_hash) or hashlib.sha256(raw).hexdigest()!=expected_hash:
        raise ValueError('Release checksum does not match.')
    files={}
    total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            path=PurePosixPath(info.filename)
            if info.filename not in ALLOWED or len(path.parts)!=1 or info.filename in files:
                raise ValueError('Unexpected file in release.')
            if (info.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Links are not allowed in release archives.')
            total+=info.file_size
            if total>MAX_ZIP or info.file_size>1024*1024:
                raise ValueError('Expanded release is too large.')
            files[info.filename]=archive.read(info)
    required={'bot.py','community.py','storage.py','instance_lock.py','requirements.txt','VERSION','test_bot.py','test_community.py','test_launcher.py'}
    if not required<=files.keys() or files['VERSION'].decode('ascii').strip()!=version:
        raise ValueError('Incomplete or mismatched release.')
    return files


def atomic_json(path,value):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2),encoding='utf-8')
    tmp.replace(path)


class Supervisor:
    def __init__(self,root=ROOT):
        self.root=Path(root)
        self.data=self.root/'data'
        self.data.mkdir(exist_ok=True)
        (self.root/'logs').mkdir(exist_ok=True)
        self.state_path=self.data/'supervisor.json'
        self.state=json.loads(self.state_path.read_text()) if self.state_path.exists() else {'current':None,'previous':None,'failed':[]}
        self.process=None
        self.logfile=None
        self.started=0
        self.validated=False

    def save(self):
        atomic_json(self.state_path,self.state)

    def python(self,version):
        base=self.root/'runtime'/version
        return base/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

    def prepare(self,version,files):
        version_tuple(version)
        dest=self.root/'releases'/version
        dest.mkdir(parents=True,exist_ok=True)
        for name,data in files.items():
            (dest/name).write_bytes(data)
        python=self.python(version)
        env=dict(os.environ)
        env.pop('DISCORD_BOT_TOKEN',None)
        env.pop('PYTHONPATH',None)
        env['AUTO_SETUP']='false'
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        with (self.root/'logs'/'install.log').open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,'-m','venv',str(python.parent.parent)],check=True,stdout=log,stderr=log,timeout=120,**flags)
            subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(dest/'requirements.txt')],check=True,stdout=log,stderr=log,env=env,timeout=600,**flags)
            subprocess.run([str(python),'-m','unittest','discover','-s',str(dest),'-p','test_*.py'],check=True,stdout=log,stderr=log,env=env,timeout=120,**flags)
        return dest

    def latest(self):
        release=json.loads(download(f'https://api.github.com/repos/{REPO}/releases/latest',1024*1024))
        if release.get('draft') or release.get('prerelease'):
            return None
        tag=release['tag_name']
        version=tag.removeprefix('v')
        version_tuple(version)
        current=self.state['current']
        if (current and version_tuple(version)<=version_tuple(current)) or version in self.state['failed']:
            return None
        base=f'https://github.com/{REPO}/releases/download/v{version}/'
        urls={a['name']:a['browser_download_url'] for a in release['assets']}
        if urls.get('global-gaming-bot.zip')!=base+'global-gaming-bot.zip' or urls.get('SHA256SUMS.txt')!=base+'SHA256SUMS.txt':
            raise ValueError('Release assets do not belong to the configured repository.')
        checksum=download(urls['SHA256SUMS.txt'],1024).decode('ascii').split()[0]
        raw=download(urls['global-gaming-bot.zip'],MAX_ZIP)
        return version,checked_files(raw,checksum,version)

    def bootstrap(self):
        if self.state['current']:
            return
        version=(self.root/'VERSION').read_text().strip()
        files={name:(self.root/name).read_bytes() for name in ALLOWED if (self.root/name).is_file()}
        self.prepare(version,files)
        self.state['current']=version
        self.save()

    def stop(self):
        if self.process and self.process.poll() is None:
            (self.data/'stop.request').write_text('stop',encoding='ascii')
            try:
                self.process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=15)
        self.process=None
        if self.logfile:
            self.logfile.close()
            self.logfile=None

    def start(self):
        version=self.state['current']
        token=(self.root/'config'/'token.txt').read_text(encoding='utf-8').strip()
        if not token or any(c.isspace() for c in token):
            raise ValueError('Configure the bot token using START-HIER.cmd.')
        env=dict(os.environ,DISCORD_BOT_TOKEN=token,DATA_DIR=str(self.data.resolve()),AUTO_SETUP='true',PUBLISH_ONCE='false')
        env.pop('PYTHONPATH',None)
        token=''
        (self.data/'stop.request').unlink(missing_ok=True)
        (self.data/'healthy').unlink(missing_ok=True)
        logpath=self.root/'logs'/'bot.log'
        if logpath.exists() and logpath.stat().st_size>4*1024*1024:
            logpath.replace(self.root/'logs'/'bot.previous.log')
        self.logfile=logpath.open('a',encoding='utf-8')
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        self.process=subprocess.Popen([str(self.python(version)),str(self.root/'releases'/version/'bot.py')],cwd=self.root,env=env,stdout=self.logfile,stderr=self.logfile,**flags)
        self.started=time.time()
        self.validated=False
        LOG.info('Started version %s',version)

    def activate(self,version,files):
        self.prepare(version,files)  # Old bot stays online during install and tests.
        self.stop()
        # Additive database migrations are required. Never restore old data automatically.
        self.state['previous']=self.state['current']
        self.state['current']=version
        self.save()
        self.start()

    def rollback(self):
        previous=self.state['previous']
        if not previous:
            return False
        failed=self.state['current']
        self.stop()
        self.state['failed'].append(failed)
        self.state['current']=previous
        self.state['previous']=None
        self.save()
        LOG.warning('Rolled back version %s to %s; data kept.',failed,previous)
        self.start()
        return True

    def run(self):
        lock=InstanceLock(self.data/'supervisor.lock')
        try:
            self.bootstrap()
            self.start()
            check_at=0
            while not (self.data/'supervisor.stop').exists():
                now=time.time()
                if now>=check_at:
                    check_at=now+1800
                    if not (self.root/'config'/'PAUSE-UPDATES').exists():
                        try:
                            update=self.latest()
                            if update:
                                self.activate(*update)
                        except (OSError,ValueError,KeyError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
                            LOG.warning('Update deferred (%s). Current version kept.',type(exc).__name__)
                health=self.data/'healthy'
                live=health.exists() and now-health.stat().st_mtime<75
                if live and now-self.started>30:
                    self.validated=True
                dead=self.process.poll() is not None
                stale=now-self.started>180 and not live
                if dead or stale:
                    if not self.validated and self.rollback():
                        continue
                    self.stop()
                    time.sleep(15)
                    self.start()
                time.sleep(5)
        finally:
            self.stop()
            lock.close()


if __name__=='__main__':
    (ROOT/'logs').mkdir(exist_ok=True)
    handler=RotatingFileHandler(ROOT/'logs'/'supervisor.log',maxBytes=2*1024*1024,backupCount=2,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    try:
        Supervisor().run()
    except Exception as exc:
        LOG.error('Supervisor stopped: %s',type(exc).__name__)
        raise SystemExit(1)
