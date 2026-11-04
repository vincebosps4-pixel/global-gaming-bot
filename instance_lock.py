"""OS-held lock: a crash releases it; a second bot cannot use the same data."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        try:
            if os.fstat(self.file.fileno()).st_size==0:
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Global Gaming is already running with this data directory.') from None

    def close(self):
        if not self.file.closed:
            self.file.close()
