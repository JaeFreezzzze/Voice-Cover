"""个人歌声模型训练与翻唱。Python 3.11+，模型依赖隔离在各自环境。"""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


BASE = Path(__file__).resolve().parent.parent
RATE = "40000"


def required_file(value):
    path = Path(value).expanduser().absolute()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"文件不存在或为空：{path}")
    return path


def tool(name):
    path = shutil.which(name)
    if not path:
        raise ValueError(f"未找到 {name}。Windows 可在「运行环境」点击「安装 FFmpeg」，或将含 ffmpeg 和 ffprobe 的 bin 目录加入 PATH。")
    return path


def include_winget_links():
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        links = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links"
        if links.is_dir():
            os.environ["PATH"] = os.pathsep.join(filter(None, (os.environ.get("PATH"), str(links))))


def splitter_python(configured):
    if configured:
        return required_file(configured)
    local = BASE / ".splitter" / "Scripts" / "python.exe"
    if local.is_file():
        return local
    raise ValueError("尚未配置 Demucs。整曲分轨时可在「运行环境」点击「安装 CPU 分轨」，或选择已有 Demucs 环境的 python.exe。")


def engine_paths(args):
    if not args.engine:
        raise ValueError("尚未配置 Applio。请在「运行环境」下载并解压 3.7.2 Windows 包，选择含 core.py 的文件夹。")
    root = Path(args.engine).expanduser().resolve()
    if not (root / "core.py").is_file():
        raise ValueError(f"所选目录中找不到 core.py：{root}。请选择解压后的 Applio 引擎目录。")
    required_file(root / "core.py")
    if args.engine_python:
        return root, required_file(args.engine_python)
    for relative in ("env/python.exe", "env/Scripts/python.exe", "env/bin/python",
                     ".venv/Scripts/python.exe", ".venv/bin/python"):
        candidate = root / relative
        if candidate.is_file():
            # Keep the venv launcher path, including symlinks, on POSIX.
            return root, candidate
    raise ValueError("找不到 Applio 的 Python。请用 --engine-python 指定其解释器。")


def verify_device(paths, device):
    if device == "gpu":
        root, python = paths
        result = subprocess.run([python, "-c", "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"], cwd=root)
        if result.returncode:
            raise ValueError("此引擎环境未检测到可用的 CUDA 设备，请选择 CPU 或检查 PyTorch。")


def engine_run(paths, *args, cpu=False):
    root, python = paths
    env = os.environ.copy()
    if cpu:
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    subprocess.run([python, "core.py", *args], cwd=root, env=env, check=True)


def artifacts(folder, pattern):
    return [p for p in folder.glob(pattern) if p.is_file() and p.stat().st_size > 0]


def train(args, stage=print):
    dataset = Path(args.data).expanduser().resolve()
    if not dataset.is_dir() or not any(p.is_file() and p.suffix.lower() == ".wav" for p in dataset.iterdir()):
        raise ValueError("请指定仅包含训练录音的目录，至少需要一个 WAV。")
    if any(p.is_dir() for p in dataset.iterdir()) or any(p.name.startswith("holdout_") for p in dataset.iterdir()):
        raise ValueError("训练输入应是单人的训练文件夹。请将留作试听的 WAV 放到旁边的 holdout 目录。")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.name):
        raise ValueError("实验名支持 1–64 个英文字母、数字、下划线或连字符。")
    if not (1 <= args.epochs <= 10000 and 1 <= args.batch <= 50):
        raise ValueError("epochs 应在 1–10000 之间，batch 应在 1–50 之间。")
    paths = engine_paths(args)
    verify_device(paths, args.device)
    root, python = paths
    query = "from rvc.lib.user_config import get_logs_dir; print(get_logs_dir())"
    logs = subprocess.check_output([python, "-c", query], cwd=root, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"}).strip().splitlines()[-1]
    exp = Path(logs) / args.name
    exp.mkdir(parents=True, exist_ok=False)
    print(f"实验目录：{exp}", flush=True)
    common = ["--model-name", args.name, "--sample-rate", str(args.rate)]
    gpu = "-" if args.device == "cpu" else "0"
    cores = str(args.cores)
    stage("预处理音频")
    engine_run(paths, "preprocess", *common, "--dataset-path", str(dataset), "--cpu-cores", cores)
    if not artifacts(exp / "sliced_audios", "*.wav"):
        raise RuntimeError("预处理未产生人声切片，请检查上方日志和录音电平。")
    stage("提取音高与声音特征")
    engine_run(paths, "extract", *common, "--cpu-cores", cores, "--gpu", gpu,
               "--f0-method", args.f0, "--embedder-model", args.embedder, cpu=args.device == "cpu")
    required_file(exp / "filelist.txt")
    if not artifacts(exp / "extracted", "*.npy") or not artifacts(exp / "f0_voiced", "*.npy"):
        raise RuntimeError("未找到内容特征或音高文件，请检查提取阶段日志。")
    stage("训练权重并生成索引")
    engine_run(paths, "train", *common, "--gpu", gpu, "--batch-size", str(args.batch),
               "--save-every-epoch", str(min(args.interval, args.epochs)), "--total-epoch", str(args.epochs),
               "--save-every-weights", "--pretrained", cpu=args.device == "cpu")
    weights = [p for p in artifacts(exp, "*.pth") if not p.name.startswith(("G_", "D_"))]
    final_pattern = re.compile(rf"_{args.epochs}e_\d+s(?:_best_epoch)?\.pth$", re.I)
    completed = [p for p in weights if final_pattern.search(p.name)]
    if not completed:
        raise RuntimeError("未找到目标轮次的推理权重，保留实验目录，请检查训练日志。")
    if not artifacts(exp, "*.index"):
        engine_run(paths, "index", "--model-name", args.name, "--index-algorithm", "Auto")
    print("推理权重：", completed[0])
    indexes = artifacts(exp, "*.index")
    print("检索索引：", indexes[0] if indexes else "本次没有生成。可省略 --index 试听。")
    return completed[0], indexes[0] if indexes else None


def duration(path):
    info = subprocess.check_output([tool("ffprobe"), "-v", "error", "-select_streams", "a:0",
                                    "-show_entries", "stream=duration:format=duration", "-of", "json", str(path)])
    data = json.loads(info)
    if not data.get("streams"):
        raise ValueError(f"文件中没有音轨：{path}")
    value = data["streams"][0].get("duration")
    if value in (None, "N/A"):
        value = data.get("format", {}).get("duration")
    if value in (None, "N/A"):
        raise ValueError(f"无法读取音频时长：{path}")
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"音频时长异常：{path}")
    return seconds


def ffmpeg(*args):
    subprocess.run([tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-n", *args], check=True)


def mix(vocal, backing, output, gain_db):
    if not math.isfinite(gain_db) or not -30 <= gain_db <= 18:
        raise ValueError("人声增益应在 −30 到 +18 dB 之间。")
    delta = abs(duration(vocal) - duration(backing))
    if delta > 0.35:
        raise ValueError(f"两轨相差 {delta:.2f} 秒，请使用来自同一时间线的完整音轨。")
    graph = (f"[0:a]aresample=44100,aformat=channel_layouts=stereo[b];"
             f"[1:a]aresample=44100,aformat=channel_layouts=stereo,volume={gain_db}dB[v];"
             "[b][v]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.94:level=0:latency=1[out]")
    ffmpeg("-i", str(backing), "-i", str(vocal), "-filter_complex", graph, "-map", "[out]",
           "-c:a", "pcm_s24le", str(output))
    print(f"翻唱文件：{output}")


def cover(args, stage=print):
    path = required_file(args.song)
    model = required_file(args.model)
    if model.suffix.lower() != ".pth" or model.name.startswith(("G_", "D_")):
        raise ValueError("请选择导出的推理 .pth。")
    index = str(required_file(args.index)) if args.index else ""
    if not 0 <= args.start < duration(path):
        raise ValueError("起点超出歌曲时长。")
    if args.seconds is not None and not (math.isfinite(args.seconds) and args.seconds > 0):
        raise ValueError("试听长度须大于零。")
    paths = engine_paths(args)
    verify_device(paths, args.device)
    tool("ffmpeg")
    if not args.dry:
        splitter = required_file(args.split_python) if args.split_python else Path(sys.executable)
        if subprocess.run([splitter, "-c", "import demucs.separate"]).returncode:
            raise ValueError("Demucs 未就绪。运行 setup-splitter.cmd，再在运行环境中选择 .splitter 的解释器。")
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=out))
    print(f"工作目录：{job}", flush=True)
    stage("读取参考音频")
    clip = ["-t", str(args.seconds)] if args.seconds else []
    ffmpeg("-ss", str(args.start), "-i", str(path), *clip, "-map", "0:a:0", "-ac", "2",
           "-ar", "44100", "-c:a", "pcm_f32le", str(job / "song.wav"))
    vocal = job / "song.wav"
    backing = None
    if not args.dry:
        stage("分离人声和伴奏")
        subprocess.run([splitter, "-m", "demucs.separate", "-d", "cpu", "-n", "htdemucs",
                        "--two-stems", "vocals", "--shifts", "0", "--float32",
                        "-o", str(job / "stems"), str(job / "song.wav")], check=True)
        stems = job / "stems" / "htdemucs" / "song"
        vocal = required_file(stems / "vocals.wav")
        backing = required_file(stems / "no_vocals.wav")
    converted = job / "my-vocal.wav"
    stage("转换歌声音色")
    engine_run(paths, "infer", "--input-path", str(vocal), "--output-path", str(converted),
               "--pth-path", str(model), "--index-path", index, "--pitch", str(args.pitch),
               "--index-rate", str(args.index_rate if index else 0), "--protect", str(args.protect),
               "--volume-envelope", str(args.envelope),
               "--embedder-model", args.embedder, "--f0-method", args.f0, "--export-format", "WAV", cpu=args.device == "cpu")
    required_file(converted)
    if abs(duration(converted) - duration(vocal)) > 0.35:
        raise ValueError("转换后音轨时长和输入不符，请检查推理日志。")
    output = converted
    if backing:
        stage("混合人声和伴奏")
        output = job / "cover.wav"
        mix(converted, backing, output, args.vocal_db)
    return {"output": str(output), "reference": str(job / "song.wav"), "vocal": str(converted),
            "backing": str(backing) if backing else None}


def main():
    include_winget_links()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    t = commands.add_parser("train", help="在自己的 GPU 环境微调模型")
    c = commands.add_parser("cover", help="在 CPU 上将歌曲转成自己的声音")
    for p in (t, c):
        p.add_argument("--engine", required=True, help="Applio 3.7.2 独立版根目录")
        p.add_argument("--engine-python", help="Applio 安装环境的 Python")
    for sub in (t, c):
        sub.add_argument("--device", choices=["cpu", "gpu"], default="cpu")
        sub.add_argument("--embedder", default="contentvec")
        sub.add_argument("--f0", choices=["rmvpe", "fcpe", "crepe"], default="rmvpe")
    t.add_argument("--rate", type=int, choices=[32000, 40000, 48000], default=40000)
    t.add_argument("--interval", type=int, default=10)
    t.add_argument("--cores", type=int, default=min(4, os.cpu_count() or 1))
    c.add_argument("--dry", action="store_true", help="输入纯人声，跳过分轨与伴奏混合")
    c.add_argument("--pitch", type=int, default=0)
    c.add_argument("--index-rate", type=float, default=0.5)
    c.add_argument("--protect", type=float, default=0.33)
    c.add_argument("--envelope", type=float, default=1.0)
    t.add_argument("--data", default=BASE / "dataset" / "train")
    t.add_argument("--name", default="MySinger")
    t.add_argument("--epochs", type=int, default=100)
    t.add_argument("--batch", type=int, default=4)
    c.add_argument("song", help="原曲音频文件")
    c.add_argument("--model", required=True)
    c.add_argument("--index")
    c.add_argument("--split-python", help="已安装 Demucs 的 Python，默认为当前解释器")
    c.add_argument("--start", type=float, default=0)
    c.add_argument("--seconds", type=float, help="仅处理指定秒数，省略时处理至曲末")
    c.add_argument("--out", default=BASE / "outputs")
    c.add_argument("--vocal-db", type=float, default=0)
    m = commands.add_parser("mix", help="用已有两轨调整人声音量并重新混音")
    m.add_argument("vocal")
    m.add_argument("backing")
    m.add_argument("output")
    m.add_argument("--vocal-db", type=float, default=0)
    args = parser.parse_args()
    if args.command == "train":
        train(args)
    elif args.command == "cover":
        cover(args)
    else:
        output = Path(args.output).expanduser().resolve()
        if output.suffix.lower() != ".wav":
            raise ValueError("混音输出应使用 .wav。")
        mix(required_file(args.vocal), required_file(args.backing), output, args.vocal_db)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"处理失败：{error}")
