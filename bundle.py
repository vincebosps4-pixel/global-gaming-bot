"""Build a release from an explicit allowlist; no credentials or runtime data."""
import hashlib
from pathlib import Path
import sys
import zipfile

from launcher import ALLOWED


def build(destination: Path):
    root=Path(__file__).resolve().parent
    destination.mkdir(parents=True,exist_ok=True)
    archive=destination/'global-gaming-bot.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as out:
        for name in sorted(ALLOWED):
            path=root/name
            if path.is_file():
                out.write(path,name)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination/'SHA256SUMS.txt').write_text(digest+'  global-gaming-bot.zip\n',encoding='ascii')
    return archive


if __name__=='__main__':
    print(build(Path(sys.argv[1] if len(sys.argv)>1 else 'dist')))
