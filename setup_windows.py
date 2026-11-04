"""Run by the owner on the Windows PC that will host the bot."""
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
TASK='Global Gaming Bot'


def task(*args):
    return subprocess.run(['schtasks',*args],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)


def start():
    (ROOT/'data').mkdir(exist_ok=True)
    (ROOT/'data'/'supervisor.stop').unlink(missing_ok=True)
    task('/Change','/TN',TASK,'/ENABLE')
    result=task('/Run','/TN',TASK)
    if result.returncode:
        pythonw=Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable),str(ROOT/'launcher.py')],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
    print('De bot start op de achtergrond. De eerste start installeert onderdelen en kan enkele minuten duren.')
    print('Gebruik STATUS.cmd om te zien of hij verbonden is.')


def setup():
    if os.name!='nt' or sys.version_info<(3,12):
        raise SystemExit('Gebruik Windows met Python 3.12 of nieuwer: https://www.python.org/downloads/windows/')
    print('GLOBAL GAMING — installatie op deze 24/7-pc')
    print('De bot start na Windows-aanmelding en controleert elke 30 minuten op gepubliceerde GitHub-updates.')
    print('Laat deze pc ingeschakeld, verbonden met internet en aangemeld. Het scherm mag vergrendeld zijn.')
    config=ROOT/'config'
    config.mkdir(exist_ok=True)
    secret=config/'token.txt'
    if not secret.exists():
        token=getpass.getpass('Plak de Global Gaming-botsleutel (wordt niet getoond): ').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}',token):
            raise SystemExit('De sleutel heeft niet het verwachte formaat. Er is niets opgeslagen.')
        secret.write_text(token,encoding='utf-8')
        token=''
    identity=subprocess.check_output(['whoami'],text=True).strip()
    result=subprocess.run(['icacls',str(secret),'/inheritance:r','/grant:r',identity+':(F)','*S-1-5-18:(F)','*S-1-5-32-544:(F)'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise SystemExit('De toegangsbeveiliging voor de sleutel kon niet worden ingesteld. De bot is niet gestart.')
    pythonw=Path(sys.executable).with_name('pythonw.exe')
    executable=pythonw if pythonw.exists() else Path(sys.executable)
    action=f'"{executable}" "{ROOT / "launcher.py"}"'
    result=task('/Create','/TN',TASK,'/SC','ONLOGON','/TR',action,'/RL','LIMITED','/F')
    if result.returncode:
        print('Automatisch starten bij aanmelden lukte niet. Je kunt START-BOT.cmd gebruiken.')
        print('Wil je automatisch starten: voer START-HIER.cmd uit met een Windows-account dat een eigen geplande taak mag maken.')
    else:
        print('Automatisch starten bij aanmelden is ingesteld.')
    start()


def status():
    health=ROOT/'data'/'healthy'
    print('Online en verbonden.' if health.exists() and time.time()-health.stat().st_mtime<75 else 'Nog niet verbonden, offline of bezig met opstarten.')
    print('Logbestanden: '+str(ROOT/'logs'))
    print('Deel nooit config/token.txt of de inhoud daarvan.')


if __name__=='__main__':
    arg=sys.argv[1] if len(sys.argv)>1 else 'setup'
    if arg=='start':
        start()
    elif arg=='stop':
        (ROOT/'data').mkdir(exist_ok=True)
        (ROOT/'data'/'supervisor.stop').write_text('stop',encoding='ascii')
        task('/Change','/TN',TASK,'/DISABLE')
        print('Stop aangevraagd. Binnen ongeveer 30 seconden sluit de bot af. START-BOT.cmd zet hem weer aan.')
    elif arg=='status':
        status()
    else:
        setup()
