from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile
from voice_studio import runtime
from voice_studio.store import Studio
from voice_studio.worker import run
import wave


class RuntimeTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
    
    def test_bundled_archive_wins_without_network(self):
        cache = self.root/"runtime"/"packages"
        cache.mkdir(parents=True)
        path = cache/runtime.ARCHIVE
        with ZipFile(path,"w") as z:
            z.writestr("Applio/core.py","print(1)")
            z.writestr("Applio/env/python.exe","test")
        with patch.object(runtime,"SHA256",sha256(path.read_bytes()).hexdigest()), patch.object(runtime,"urlopen",side_effect=AssertionError):
            archive = runtime.obtain_archive(self.root,lambda msg: None)
            target = cache.parent/"Applio-3.7.2"
            runtime.unpack(archive,target)
            self.assertEqual(runtime.locate_engine(self.root,{}),(target,target/"env"/"python.exe"))

    def test_resume_and_verify(self):
        data=b"sample archive"; cache=self.root/"cache";cache.mkdir()
        (cache/(runtime.ARCHIVE+".part")).write_bytes(data[:3])
        response=BytesIO(data[3:]);response.status=206
        response.headers={"Content-Range":"bytes 3-13/14","Content-Length":str(len(data)-3)}
        with patch.object(runtime,"urlopen",return_value=response) as op, patch.object(runtime,"SHA256",sha256(data).hexdigest()):
            self.assertEqual(runtime.fetch_archive(cache,lambda s:None).read_bytes(),data)
        self.assertEqual(op.call_args.args[0].headers["Range"],"bytes=3-")

    def test_ready_restart_reuses_config_without_install(self):
        project=self.root/"project";managed=project/"runtime"/"Applio-3.7.2"
        py=managed/"env"/"python.exe"
        split=project/".splitter"/"Scripts"/"python.exe"; weight=self.root/"weight.th"
        for p in (managed/"core.py",py,split,weight,*(managed/n for n in runtime.REQUIRED_MODELS)):
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"test")
        settings=dict(engine=str(managed),engine_python=str(py),split_python=str(split))
        (managed.parent/"ready-3.7.2.json").write_text(json.dumps(dict(settings=settings,demucs_weight=str(weight))))
        with patch.dict(os.environ,VOICE_STUDIO_HOME=str(self.root/"store")),patch.object(runtime.shutil,"which",return_value="ffmpeg"),patch.object(runtime.subprocess,"run",side_effect=AssertionError):
            runtime.prepare_runtime(project,None,lambda msg: None)
            store=Studio(self.root/"store")
            try:self.assertEqual(store.get_setting("runtime",{}),settings)
            finally:store.db.close()
        self.assertTrue((project/"dataset"/"test").is_dir())

    def test_cold_start_with_upstream_version_banner(self):
        project=self.root/"project"; managed=project/"runtime"/"Applio-3.7.2"
        py=managed/"env"/"python.exe"; split=project/".splitter"/"Scripts"/"python.exe"
        weight=self.root/"955717e8-test.th"
        for p in (managed/"core.py",py,split,weight,*(managed/n for n in runtime.REQUIRED_MODELS)):
            p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b"test")
        from subprocess import CompletedProcess
        def invoke(cmd,**kwargs):
            output=b"Applio v3.7.2\n" if "--version" in cmd else b""
            if "get_model(" in str(cmd[-1]):output=str(weight).encode()+b"\n"
            return CompletedProcess(cmd,0,output)
        with patch.dict(os.environ,VOICE_STUDIO_HOME=str(self.root/"store")),patch.object(runtime.shutil,"which",return_value="ffmpeg"),patch.object(runtime.subprocess,"run",side_effect=invoke):
            runtime.prepare_runtime(project,None,lambda msg:None)
        self.assertEqual(json.loads((managed.parent/"ready-3.7.2.json").read_text())["demucs_weight"],str(weight))

    def test_holdout_wins_across_folders_and_existing_library(self):
        ds=self.root/"dataset"
        for group in ("train","test"):
            p=ds/group/"take.wav";p.parent.mkdir(parents=True)
            with wave.open(str(p),"wb") as w:
                w.setparams((1,2,16000,0,"NONE",""));w.writeframes(b"\0\0"*800)
        store=Studio(self.root/"library")
        self.addCleanup(store.db.close)
        store.ingest(ds/"train"/"take.wav","train")
        with patch("voice_studio.worker.DATASET",ds):
            for _ in range(2):
                run(store,store.new_job("dataset","import",{}))
        self.assertEqual([a["role"] for a in store.audio()],["holdout"])
