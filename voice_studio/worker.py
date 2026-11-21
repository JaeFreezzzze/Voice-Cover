import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from . import engine
from .store import DATASET, Studio, dataset_files, encode, fresh_zip, uid


def diagnostics(settings):
    root=settings.get("engine","")
    for name in ("ffmpeg","ffprobe"):
        try:
            path=engine.tool(name)
            subprocess.run([path,"-version"],check=True,timeout=15,stdout=subprocess.DEVNULL)
            print(f"{name}：{path}",flush=True)
        except (ValueError,OSError,subprocess.SubprocessError) as e:
            print(f"{name} 未就绪：{e}",flush=True)
    try:
        folder,py=engine.engine_paths(SimpleNamespace(engine=root,engine_python=settings.get("engine_python")))
        print("Applio 解释器：",py,flush=True)
        commands=[[py,"core.py","--version"],[py,"-c",
            "import torch; print('PyTorch',torch.__version__,'CUDA',torch.cuda.is_available())"]]
        for cmd in commands:
            subprocess.run(cmd,cwd=folder,timeout=60,check=True)
        print("Applio：可用",flush=True)
    except (ValueError,OSError,subprocess.SubprocessError) as e:
        print(f"Applio 未就绪：{e}",flush=True)
    try:
        py=engine.splitter_python(settings.get("split_python"))
        check=subprocess.run([py,"-c","import demucs.separate"],timeout=45)
        print("Demucs："+("可用" if check.returncode==0 else "导入失败"),flush=True)
    except (ValueError,OSError,subprocess.TimeoutExpired) as e:
        print(f"Demucs 未就绪：{e}",flush=True)
    print("录音和原生 PCM WAV 管理可独立使用。",flush=True)


def run(store,key):
    job=store.get("jobs",key)
    spec=json.loads(job["spec"])
    kind=job["kind"]
    def stage(text):
        store.job_state(key,"running",text)
        print(text,flush=True)
    stage("准备任务")
    if kind=="setup":
        if os.name!="nt":
            raise ValueError("此依赖安装入口适用于 Windows。")
        component=spec["component"]
        if component not in ("ffmpeg","splitter"):
            raise ValueError("未知安装组件。")
        stage("安装 FFmpeg" if component=="ffmpeg" else "准备 FFmpeg 和 CPU 分轨环境")
        subprocess.run(["cmd.exe","/d","/c","setup-splitter.cmd","--batch",component],
                       cwd=engine.BASE,check=True)
        return {}
    if kind=="assets":
        stage("由 Applio 下载预训练和特征提取资源")
        engine.engine_run(engine.engine_paths(SimpleNamespace(**spec)), "prerequisites")
        return {}
    if kind=="check":
        diagnostics(spec)
        return {}
    if kind in ("ingest","dataset"):
        errors=[]; inserted=0; reused=0
        files=(list(dataset_files(DATASET)) if kind=="dataset" else
               [(p,"holdout" if Path(p).is_relative_to(DATASET/"test") else spec["role"]) for p in spec["paths"]])
        if not files:
            raise ValueError("请先将音频放入 dataset/train 或 dataset/test。")
        for i,(path,role) in enumerate(files,1):
            stage(f"处理音频 {i}/{len(files)} · {Path(path).name}")
            try:
                sample,created=store.ingest(path,role,spec.get("title"))
                if (kind=="dataset" or Path(path).is_relative_to(DATASET/"test")) and not created and role=="holdout" and store.get("audio",sample)["role"]=="train":
                    store.change_audio([sample],role="holdout")
                inserted+=int(created); reused+=int(not created)
                if spec.get("recorded") and Path(path).resolve().parent == (store.root/"recordings").resolve():
                    Path(path).unlink(missing_ok=True)
            except (OSError,ValueError,subprocess.CalledProcessError) as e:
                errors.append(f"{Path(path).name}：{e}")
        print(f"导入 {inserted} 条，已存在 {reused} 条",flush=True)
        if errors:
            raise ValueError("；".join(errors))
        return {"added":inserted,"existing":reused}
    if kind=="model":
        stage("收录模型文件")
        model=(store.import_model(spec["package"]) if spec.get("package") else
               store.add_model(spec["title"],spec["weights"],spec.get("index"),spec["embedder"],{"origin":"外部导入"}))
        return {"model":model}
    if kind=="export":
        stage("写入模型包")
        store.export_model(spec["model"],spec["dest"])
        return {"file":spec["dest"]}
    if kind in ("train","bundle"):
        p=spec["params"]
        samples=[store.get("audio",i) for i in spec["samples"]]
        if not samples:
            raise ValueError("训练集为空。")
        metadata=[{"id":r["id"],"title":r["title"],"sha256":r["digest"],"seconds":r["seconds"]} for r in samples]
        if kind=="bundle":
            stage("打包训练音频和参数")
            with fresh_zip(spec["dest"]) as z:
                z.write(Path(__file__).with_name("engine.py"),"engine.py")
                z.write(Path(__file__).with_name("portable.py"),"train.py")
                z.writestr("training.json",encode({"parameters":p,"samples":metadata}))
                z.writestr("README.txt","解压到独立目录。在安装 Applio 3.7.2 的机器执行：\n"
                           "python train.py --engine /path/to/Applio --device gpu\n"
                           "生成的 .vmodel 可从桌面工作台的「声音模型 → 导入」载入。")
                for row in samples:
                    z.write(row["wav"],"dataset/"+row["id"]+".wav")
            return {"file":spec["dest"]}
        stage("固定本次训练集")
        data=store.root/"jobs"/key/"dataset"
        data.mkdir()
        for row in samples:
            target=data/(row["id"]+".wav")
            try:
                os.link(row["wav"],target)
            except OSError:
                shutil.copyfile(row["wav"],target)
        run_name="vc_"+key[:16]
        args=SimpleNamespace(**dict(p,**spec["settings"],name=run_name,data=data))
        weights,idx=engine.train(args,stage)
        stage("登记推理权重和训练参数")
        mid=store.add_model(p["name"],weights,idx,p["embedder"],dict(p,experiment=run_name,samples=metadata))
        return {"model":mid}
    if kind=="cover":
        model=store.get("models",spec["model"])
        args=SimpleNamespace(**dict(spec["params"],**spec["settings"],song=spec["song"],dry=spec["dry"],
                    out=store.root/"outputs",model=model["weights"],index=model["idx"],embedder=model["embedder"]))
        if not args.dry:
            args.split_python=engine.splitter_python(args.split_python)
        return engine.cover(args,stage)
    raise ValueError(f"未知任务 {kind}")


def main():
    engine.include_winget_links()
    store=Studio(sys.argv[1]); key=sys.argv[2]
    from .jobs import lock_at
    lock=lock_at(store.root,key)
    if not lock.tryLock(0):return 2
    try:
        result=run(store,key)
        store.job_state(key,"done","已完成",result)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        store.job_state(key,"error","执行失败",error=str(exc))
        return 1
    finally:
        store.db.close()
        lock.unlock()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
