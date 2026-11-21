"""Stream a Windows distribution ZIP to stdout, including the pinned Applio package."""
import hashlib
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_STORED

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from voice_studio.runtime import ARCHIVE, CHUNK, SHA256, URL


def build(output, source):
    files = subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).decode().split("\0")
    with ZipFile(output,"w",ZIP_STORED,allowZip64=True) as z:
        for name in filter(None,files):
            z.write(ROOT/name, "Voice-Cover/"+name)
        digest = hashlib.sha256()
        with z.open("Voice-Cover/runtime/packages/"+ARCHIVE,"w",force_zip64=True) as target:
            while block := source.read(CHUNK):
                target.write(block)
                digest.update(block)
        if digest.hexdigest()!=SHA256:
            raise ValueError("The bundled Applio ZIP failed its upstream SHA-256 check.")


if __name__ == "__main__":
    with urlopen(URL,timeout=120) as source:
        build(sys.stdout.buffer,source)
