"""Keep the local preview running independently of a terminal/chat session."""
import argparse
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    data = project / 'data'
    data.mkdir(exist_ok=True)
    # One supervisor per project, even when two launchers are clicked together.
    with (data / 'server.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        (data / 'supervisor.pid').write_text(str(os.getpid()))
        (data / 'server.port').write_text(str(args.port))
        stop = data / 'server.stop'
        stop.unlink(missing_ok=True)
        command = [sys.executable, '-m', 'streamlit', 'run', str(project / 'app.py'),
                   '--server.address', '127.0.0.1', '--server.port', str(args.port),
                   '--server.headless', 'true', '--browser.gatherUsageStats', 'false',
                   '--server.disconnectedSessionTTL', '0']
        while not stop.exists():
            with (data / 'server.log').open('a', encoding='utf-8') as out, \
                    (data / 'server-error.log').open('a', encoding='utf-8') as err:
                child = subprocess.Popen(command, cwd=project, stdout=out, stderr=err,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                (data / 'server.pid').write_text(str(child.pid))
                child.wait()
                err.write(f'\nServer exited ({child.returncode}); restart pending.\n')
            # Short delay avoids a tight loop if a dependency/config is broken.
            for _ in range(30):
                if stop.exists():
                    break
                time.sleep(0.1)


if __name__ == '__main__':
    main()
