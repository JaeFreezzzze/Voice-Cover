"""Prepare the Windows audio runtime on first launch. Requires only the standard library."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile
from uuid import uuid4

from . import engine
from .store import Studio, workdir

ARCHIVE = "ApplioV3.7.2.zip"
REVISION = "4d83961296ca8f23007b7df994de7d7086b0d36e"
URL = f"https://huggingface.co/IAHispano/Applio/resolve/{REVISION}/Compiled/Windows/{ARCHIVE}"
SHA256 = "a177815f88631b28989836d6a88a6f71a3cb3f7eb6c45eefce757d8ac502c979"
CHUNK = 1024 * 1024
REQUIRED_MODELS = (
    "rvc/models/embedders/contentvec/config.json", "rvc/models/embedders/contentvec/pytorch_model.bin",
    "rvc/models/predictors/rmvpe.pt", "rvc/models/predictors/fcpe.pt",
    *(f"rvc/models/pretraineds/hifi-gan/f0{kind}{rate}k.pth" for kind in "GD" for rate in (32,40,48)),
)


def verify(path):
    with path.open("rb") as src:
        if hashlib.file_digest(src, "sha256").hexdigest() != SHA256:
            raise ValueError(f"Applio 安装包校验失败：{path}")


def fetch_archive(cache, report):
    cache.mkdir(parents=True, exist_ok=True)
    partial = cache / (ARCHIVE + ".part")
    target = cache / ARCHIVE
    offset = partial.stat().st_size if partial.is_file() else 0
    request = Request(URL, headers={"Range": f"bytes={offset}-"} if offset else {})
    try:
        response = urlopen(request, timeout=90)
    except HTTPError as exc:
        if not (exc.code == 416 and offset):
            raise
        response = None  # A previous download may already contain every byte.
    if response is not None:
        with response:
            resumed = response.status == 206
            if resumed and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                raise IOError("下载服务器返回了错误的续传位置。")
            done = offset if resumed else 0
            with partial.open("ab" if resumed else "wb") as out:
                last_mb = -100
                while block := response.read(CHUNK):
                    out.write(block)
                    done += len(block)
                    mb = done // (1024 * 1024)
                    if mb - last_mb >= 32:
                        report(f"正在准备 Applio 3.7.2，已下载 {mb} MiB")
                        last_mb = mb
                if response.headers.get("Content-Length") and done != (offset if resumed else 0) + int(response.headers["Content-Length"]):
                    raise IOError("Applio 下载中断，下次启动会继续。")
    try:
        verify(partial)
    except ValueError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(target)
    return target


def obtain_archive(root, report):
    cache = root / "runtime" / "packages"
    places = (cache, root, Path.home() / "Downloads")
    for directory in places:
        candidate = directory / ARCHIVE
        if candidate.is_file():
            report("正在校验已有 Applio 安装包…")
            try:
                verify(candidate)
                return candidate
            except ValueError:
                report(f"跳过校验失败的安装包：{candidate.name}")
    report("正在自动获取 Applio 3.7.2 Windows 包…")
    return fetch_archive(cache, report)


def unpack(archive, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp, ZipFile(archive) as z:
        tmp = Path(tmp)
        files = z.infolist()
        required = sum(f.file_size for f in files)
        if shutil.disk_usage(tmp).free < required:
            raise OSError(f"解压 Applio 需要约 {required / (1024**3):.1f} GiB 可用空间。")
        for f in files:
            parts = f.filename.replace("\\", "/").split("/")
            if not parts[0] or ".." in parts or any(":" in part for part in parts):
                raise ValueError("Applio 压缩包包含无效路径。")
        z.extractall(tmp)
        roots = [p.parent for p in tmp.rglob("core.py") if (p.parent/"env"/"python.exe").is_file()]
        if len(roots) != 1:
            raise ValueError("安装包中无法定位独立版 core.py 和 env/python.exe。")
        roots[0].rename(destination)


def full_file(path):
    return path.is_file() and path.stat().st_size > 0


def locate_engine(root, settings):
    managed = root/"runtime"/"Applio-3.7.2"
    for directory, py in [(settings.get("engine"),settings.get("engine_python")),
                          (managed,None),(root/"Applio",None),(root.parent/"Applio",None),
                          (root/"ApplioV3.7.2",None),(root.parent/"ApplioV3.7.2",None)]:
        if not directory:
            continue
        try:
            return engine.engine_paths(SimpleNamespace(engine=directory,engine_python=py))
        except (ValueError,OSError):
            pass
    return None


def expose_tools(folder):
    os.environ["PATH"] = os.pathsep.join([str(folder),os.environ.get("PATH","")])
    engine.include_winget_links()


def prepare_runtime(root, log, report):
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    for group in ("train","test"):
        (root/"dataset"/group).mkdir(parents=True, exist_ok=True)
    store = Studio(workdir())
    try:
        settings = store.get_setting("runtime", {})
        paths = locate_engine(root, settings)
        if not paths:
            archive = obtain_archive(root, report)
            report("正在解压 Applio 3.7.2…")
            managed = runtime / "Applio-3.7.2"
            if managed.exists():
                managed.rename(managed.with_name(f"Applio-incomplete-{uuid4().hex[:8]}"))
            unpack(archive, managed)
            paths = engine.engine_paths(SimpleNamespace(engine=managed,engine_python=None))
        folder, py = paths
        expose_tools(folder)
        configured = settings.get("split_python")
        split = Path(configured) if configured and full_file(Path(configured)) else root/".splitter"/"Scripts"/"python.exe"
        stamp = runtime/"ready-3.7.2.json"
        try:
            previous = json.loads(stamp.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            previous = {}
        current = dict(engine=str(folder), engine_python=str(py), split_python=str(split))
        def call(args, cwd=root, capture=False):
            result = subprocess.run(args,cwd=cwd,stdin=subprocess.DEVNULL,stderr=log,
                                    stdout=subprocess.PIPE if capture else log,check=True,
                                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            return result.stdout.decode("utf-8",errors="replace").strip() if capture else ""
        if (previous.get("settings")==current and full_file(split)
                and full_file(Path(previous.get("demucs_weight","")))
                and all(full_file(folder/p) for p in REQUIRED_MODELS)
                and all(shutil.which(n) for n in ("ffmpeg","ffprobe"))):
            store.setting("runtime",current)
            return
        report("正在检查 Applio 并准备训练和换声资源…")
        version = call([py,"core.py","--version"],folder,True)
        if not re.search(r"(?<![\w.])v?3\.7\.2(?![\w.-])", version, re.I):
            raise ValueError(f"所选引擎版本不匹配：{version}（需要 Applio 3.7.2）")
        call([py,"-c","import torch"],folder)
        call([py,"core.py","prerequisites"],folder)
        missing = [p for p in REQUIRED_MODELS if not full_file(folder/p)]
        if missing:
            raise ValueError("Applio 缺少基础资源：" + ", ".join(missing))
        report("正在准备 FFmpeg 和 CPU 分轨环境…")
        for name in ("ffmpeg","ffprobe"):
            if not shutil.which(name):
                call(["cmd.exe","/d","/c","setup-splitter.cmd","--batch","ffmpeg"])
                break
        for name in ("ffmpeg","ffprobe"):
            call([engine.tool(name),"-version"])
        if not full_file(split) or subprocess.run([split,"-c","import demucs.separate"],stdout=log,stderr=log,
                                                  creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)).returncode:
            call(["cmd.exe","/d","/c","setup-splitter.cmd","--batch","splitter"])
            split = root/".splitter"/"Scripts"/"python.exe"
            current["split_python"] = str(split)
        report("正在准备 Demucs 人声分离模型…")
        query = ("from pathlib import Path; import torch; from demucs.pretrained import get_model; "
                 "get_model('htdemucs'); print(next((Path(torch.hub.get_dir())/'checkpoints').glob('955717e8-*.th')))")
        weight = call([split,"-X","utf8","-c",query],capture=True).splitlines()[-1]
        if not full_file(Path(weight)):
            raise ValueError("Demucs 模型未完整下载。")
        store.setting("runtime",current)
        pending = stamp.with_suffix(".tmp")
        pending.write_text(json.dumps(dict(settings=current,demucs_weight=weight)),encoding="utf-8")
        pending.replace(stamp)
    finally:
        store.db.close()
