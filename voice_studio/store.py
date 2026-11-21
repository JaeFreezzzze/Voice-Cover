import array
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid
import wave
from zipfile import ZipFile

from .engine import ffmpeg, required_file

ROLES = {"train": "训练", "holdout": "评估", "archived": "归档"}
EMBEDDERS = ["contentvec", "chinese-hubert-base", "spin", "spin-v2"]
TYPES = {"ingest": "导入音频", "train": "模型训练", "model": "导入模型", "cover": "歌声转换",
         "assets": "下载基础资源", "bundle": "导出训练包", "export": "导出声音模型", "check": "检查环境",
         "setup": "安装运行组件"}
STATUS = {"pending": "待执行", "running": "运行中", "done": "已完成", "error": "失败", "interrupted": "已中断"}
TRAIN_DEFAULT = dict(name="我的歌声", device="cpu", rate=40000, epochs=100, batch=2, interval=10,
                     cores=min(os.cpu_count() or 1, 4), f0="rmvpe", embedder="contentvec")
COVER_DEFAULT = dict(device="cpu", pitch=0, index_rate=0.5, protect=0.33, envelope=1.0,
                     vocal_db=0.0, f0="rmvpe", start=0, seconds=20)

def now():
    return datetime.now().isoformat(timespec="seconds")

def encode(obj):
    return json.dumps(obj, ensure_ascii=False)

def uid():
    return uuid.uuid4().hex

def workdir():
    default = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VoiceCoverStudio"
    return Path(os.environ.get("VOICE_STUDIO_HOME") or default).expanduser().absolute()

def duration_text(value):
    seconds = int(value)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"

def pcm_info(path):
    with wave.open(str(path), "rb") as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1 or audio.getnframes() == 0:
            raise ValueError("需要非空的单声道 PCM16 录音。")
        rate, frames = audio.getframerate(), audio.getnframes()
        bins, peak, clipped, seen = [0] * 88, 0, 0, 0
        while chunk := audio.readframes(8192):
            values = array.array("h", chunk)
            if sys.byteorder != "little":
                values.byteswap()
            for offset, raw in enumerate(values):
                amp = abs(raw)
                slot = min(87, (seen + offset) * 88 // frames)
                if amp > bins[slot]:
                    bins[slot] = amp
                if amp >= 32700:
                    clipped += 1
            seen += len(values)
        if seen != frames:
            raise ValueError("WAV 的数据长度与文件头不一致。")
        peak = max(bins)
        return frames/rate, rate, round(20*math.log10(max(1,peak)/32768),1), clipped, [n/32768 for n in bins]


class Studio:
    def __init__(self, root):
        self.root = Path(root).absolute()
        for child in ("audio","models","jobs","recordings","outputs"):
            (self.root/child).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root/"studio.sqlite3", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS audio(id TEXT PRIMARY KEY, digest TEXT UNIQUE, title TEXT, role TEXT,
             original TEXT, wav TEXT, seconds REAL, rate INTEGER, peak REAL, clipped INTEGER, peaks TEXT, created TEXT);
          CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY, title TEXT, weights TEXT, idx TEXT,
             embedder TEXT, params TEXT, created TEXT);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, title TEXT, status TEXT, stage TEXT,
             spec TEXT, result TEXT, error TEXT, created TEXT, finished TEXT);
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def audio(self):
        return self.rows("SELECT * FROM audio ORDER BY created DESC,rowid DESC")

    def models(self):
        return self.rows("SELECT * FROM models ORDER BY created DESC,rowid DESC")

    def jobs(self):
        return self.rows("SELECT * FROM jobs ORDER BY created DESC,rowid DESC")

    def get(self, table, key):
        if table not in ("audio","models","jobs"):
            raise ValueError(table)
        rows = self.rows(f"SELECT * FROM {table} WHERE id=?", (key,))
        if not rows:
            raise ValueError("此记录已不存在，请刷新。")
        return rows[0]

    def get_setting(self, key, default):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def setting(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key,encode(value)))

    def ingest(self, path, role, title=None):
        if role not in ROLES:
            raise ValueError("未知音频用途")
        path = required_file(path)
        key = uid()
        folder = self.root/"audio"/key
        folder.mkdir()
        try:
            original=folder/("source"+path.suffix.lower())
            shutil.copyfile(path,original)
            with original.open("rb") as source:
                digest=hashlib.file_digest(source,"sha256").hexdigest()
            old=self.db.execute("SELECT id FROM audio WHERE digest=?", (digest,)).fetchone()
            if old:
                shutil.rmtree(folder)
                return old[0], False
            wav=folder/"sample.wav"
            native=False
            try:
                with wave.open(str(original)) as w:
                    native = w.getsampwidth()==2 and w.getnchannels()==1 and w.getcomptype()=="NONE"
            except (wave.Error, EOFError):
                pass
            if native:
                try:
                    os.link(original,wav)
                except OSError:
                    shutil.copyfile(original,wav)
            else:
                ffmpeg("-i",str(original),"-map","0:a:0","-vn","-ac","1","-ar","48000","-c:a","pcm_s16le",str(wav))
            secs,rate,peak,clipped,peaks=pcm_info(wav)
            with self.db:
                self.db.execute("INSERT INTO audio VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key,digest,title or path.stem,role,str(original),str(wav),secs,rate,peak,clipped,encode(peaks),now()))
        except Exception:
            shutil.rmtree(folder,ignore_errors=True)
            raise
        return key, True

    def change_audio(self, keys, role=None, title=None):
        if role is not None and role not in ROLES:
            raise ValueError("未知音频用途")
        with self.db:
            for key in keys:
                if role:
                    self.db.execute("UPDATE audio SET role=? WHERE id=?", (role,key))
                if title and title.strip():
                    self.db.execute("UPDATE audio SET title=? WHERE id=?", (title.strip(),key))

    def add_model(self, name, weights, idx, embedder, params):
        weights=required_file(weights)
        if weights.suffix.lower()!=".pth" or weights.name.startswith(("G_","D_")):
            raise ValueError("请选择推理权重 .pth，训练检查点不能用于翻唱。")
        if idx:
            idx=required_file(idx)
            if idx.suffix.lower()!=".index":
                raise ValueError("索引扩展名应为 .index。")
        if embedder not in EMBEDDERS or not str(name).strip():
            raise ValueError("请填写模型名并选择受支持的特征编码器。")
        key=uid()
        folder=self.root/"models"/key
        folder.mkdir()
        try:
            w=folder/"voice.pth"
            shutil.copyfile(weights,w)
            i=folder/"voice.index" if idx else None
            if i:
                shutil.copyfile(idx,i)
            with self.db:
                self.db.execute("INSERT INTO models VALUES(?,?,?,?,?,?,?)",
                    (key,name,str(w),str(i) if i else "",embedder,encode(params),now()))
        except Exception:
            shutil.rmtree(folder,ignore_errors=True)
            raise
        return key

    def export_model(self,key,dest):
        model=self.get("models",key)
        meta={"format":1,"title":model["title"],"embedder":model["embedder"],"params":json.loads(model["params"])}
        with fresh_zip(dest) as z:
            z.writestr("model.json",encode(meta))
            z.write(required_file(model["weights"]),"voice.pth")
            if model["idx"]:
                z.write(required_file(model["idx"]),"voice.index")

    def import_model(self,path):
        with tempfile.TemporaryDirectory(dir=self.root/"models") as folder, ZipFile(path) as z:
            meta=json.loads(z.read("model.json"))
            if meta.get("format")!=1 or not isinstance(meta.get("params"),dict):
                raise ValueError("不支持的模型包格式。")
            for name in ("voice.pth","voice.index"):
                if name=="voice.index" and name not in z.namelist():
                    continue
                with z.open(name) as src, (Path(folder)/name).open("wb") as dst:
                    shutil.copyfileobj(src,dst)
            idx=Path(folder)/"voice.index"
            return self.add_model(meta["title"],Path(folder)/"voice.pth",idx if idx.exists() else None,
                                  meta["embedder"],meta["params"])

    def new_job(self,kind,title,spec):
        key=uid()
        (self.root/"jobs"/key).mkdir()
        with self.db:
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (key,kind,title,"pending","等待启动",encode(spec),"{}","",now(),None))
        return key

    def job_state(self,key,status,stage, result=None,error=""):
        with self.db:
            self.db.execute("UPDATE jobs SET status=?,stage=?,result=?,error=?,finished=? WHERE id=?",
                (status,stage,encode(result or {}),error,now() if status in ("done","error","interrupted") else None,key))


@contextmanager
def fresh_zip(dest):
    """先在目标目录生成完整包，再发布它；已有同名交付件会保留。"""
    dest=Path(dest)
    if dest.exists():
        raise FileExistsError(f"文件已存在，请换一个文件名：{dest}")
    tmp=dest.with_name("."+uid()+".partial")
    try:
        with ZipFile(tmp,"w",allowZip64=True) as z:
            yield z
        # Same filesystem. The exclusive publish also guards simultaneous exports.
        try:
            os.link(tmp,dest)
        except FileExistsError:
            raise
        except OSError:
            with dest.open("xb") as out:
                try:
                    with tmp.open("rb") as inp:
                        shutil.copyfileobj(inp,out)
                except Exception:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise
    finally:
        tmp.unlink(missing_ok=True)
