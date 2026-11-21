import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from voice_studio import engine
from voice_studio.engine import duration, mix
from voice_studio.store import Studio, TRAIN_DEFAULT
from voice_studio.worker import diagnostics, run

def tone(path,frames=9600,value=2400):
    with wave.open(str(path),"wb") as w:
        w.setparams((1,2,48000,0,"NONE",""));w.writeframes(struct.pack("<h",value)*frames)
    return path

class Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.s=Studio(self.root/"workspace");self.addCleanup(self.s.db.close)
    def test_unconfigured_runtime(self):
        log=StringIO()
        with patch.object(engine,"BASE",self.root), patch.object(shutil,"which",return_value=None), redirect_stdout(log):
            diagnostics({})
        for expected in ("安装 FFmpeg","尚未配置 Applio","尚未配置 Demucs"):
            self.assertIn(expected,log.getvalue())
        self.assertNotIn("文件不存在或为空",log.getvalue())
        with self.assertRaisesRegex(ValueError,"所选目录中找不到 core.py"):
            engine.engine_paths(SimpleNamespace(engine=str(self.root),engine_python=None))

    def test_splitter_detected_after_setup(self):
        with patch.object(engine,"BASE",self.root):
            with self.assertRaisesRegex(ValueError,"安装 CPU 分轨"):
                engine.splitter_python("")
            local=self.root/".splitter"/"Scripts"/"python.exe"
            local.parent.mkdir(parents=True);local.write_bytes(b"fixture")
            self.assertEqual(engine.splitter_python(""),local)
            with self.assertRaises(ValueError):
                engine.splitter_python(self.root/"missing.exe")
            custom=self.root/"custom.exe";custom.write_bytes(b"fixture")
            self.assertEqual(engine.splitter_python(custom),custom)
    def test_audio_identity_and_training_bundle(self):
        train=tone(self.root/"verse.wav");hold=tone(self.root/"unused.wav",value=2100)
        key,new=self.s.ingest(train,"train");self.assertTrue(new)
        same,new=self.s.ingest(train,"holdout");self.assertFalse(new);self.assertEqual(same,key)
        hold_key,_=self.s.ingest(hold,"holdout")
        self.s.change_audio([hold_key],role="archived")
        rows=self.s.audio();self.assertEqual(len(rows),2);self.assertTrue(all(len(json.loads(r["peaks"]))==88 for r in rows))
        params=dict(TRAIN_DEFAULT,epochs=2);dest=self.root/"train.zip"
        spec=dict(samples=[r["id"] for r in rows if r["role"]=="train"],params=params,dest=str(dest))
        run(self.s,self.s.new_job("bundle","测试",spec))
        with ZipFile(dest) as z:
            self.assertEqual([f for f in z.namelist() if f.endswith(".wav")],["dataset/"+key+".wav"])
            self.assertEqual(json.loads(z.read("training.json"))["parameters"]["epochs"],2)
        with self.assertRaises(FileExistsError):run(self.s,self.s.new_job("bundle","重复导出",spec))
    def test_model_round_trip(self):
        weights=self.root/"voice.pth";weights.write_bytes(b"fixture only -- no inference")
        idx=self.root/"test.index";idx.write_bytes(b"test index")
        key=self.s.add_model("样本声线",weights,idx,"contentvec",{"epochs":2})
        packed=self.root/"backup.vmodel";self.s.export_model(key,packed)
        new_key=self.s.import_model(packed);row=self.s.get("models",new_key)
        self.assertNotEqual(key,new_key);self.assertEqual(Path(row["idx"]).read_bytes(),idx.read_bytes())
        self.assertEqual(json.loads(row["params"]),{"epochs":2})
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"requires FFmpeg")
    def test_mix_and_timing(self):
        a=tone(self.root/"a.wav");b=tone(self.root/"b.wav");dst=self.root/"out.wav"
        mix(a,b,dst,-2);self.assertAlmostEqual(duration(dst),.2,places=4)
        with self.assertRaises(ValueError):mix(a,tone(b,48000),self.root/"bad.wav",0)
