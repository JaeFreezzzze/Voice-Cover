# 歌声工作台 · Voice Cover Studio 0.3.0

用自己的录音训练 RVC 模型，把指定歌曲换成自己的声音。Windows 桌面应用采用 PyQt5，音频、模型元数据、训练参数和任务历史保存在本机。模型训练与转换调用 Applio 3.7.2，整曲分轨调用 Demucs，混音调用 FFmpeg。

![训练工作区](docs/training.png)

## 启动

Windows 10/11 x64 使用 Python 3.12（含 3.12.10）或 3.11 x64。解压后双击 **VoiceCoverStudio.exe**。若未检测到兼容 Python，启动器会尝试用 WinGet 为当前用户安装 Python 3.12 x64。首次启动会显示准备进度，安装桌面组件，定位、校验并解压 Applio 3.7.2，准备基础权重、FFmpeg / ffprobe 和 CPU 版 Demucs（含 htdemucs 权重），最后自动保存引擎和解释器路径。再次启动复用已有环境。可在「运行环境」查看或调整配置。

- **完整 Windows 发行包**在 [Releases](https://github.com/JaeFreezzzze/Voice-Cover/releases)。将同一版本的所有 `.zip.00*` 分卷放在一起，用 7-Zip 打开第一卷并解压。工程内 `runtime/packages/ApplioV3.7.2.zip` 已包含上游 Windows 包。桌面依赖、CPU 分轨和缺失的模型在首次启动时可能仍需联网。
- **Git 检出或 GitHub Source code ZIP** 可直接启动。先复用已配置的引擎、工程的 `runtime/Applio-3.7.2` 或常见的同级 Applio 文件夹。其次从 `runtime/packages`、项目根目录、用户 Downloads 目录找同名官方包。找不到时从固定的官方版本自动下载，保留下载进度，完成后核对 SHA-256。
- 启动时若下载或安装中断，可先进入音频库和录音，下次启动会重试。首次安装日志在 `%LOCALAPPDATA%/VoiceCoverStudio/logs/startup.log`。选 CPU 即可在没有 NVIDIA 独显的电脑训练或翻唱，也可导出异机训练包。

## 工程数据集

自己的训练录音放在 `dataset/train/`，留作评估的录音和参考歌曲放在 `dataset/test/`。在「音频库」点「导入工程数据集」，支持子目录，按内容去重。测试目录优先，重复样本会标记为评估，训练任务仅使用音频库里标为训练的样本。可用「打开数据集目录」直接放入文件。个人音频默认被 Git 忽略。

## 工作区

| 页面 | 可执行的操作 |
| --- | --- |
| 音频库 | 选择麦克风，录制 PCM WAV，批量导入 WAV/FLAC/MP3/M4A 等；试听、看波形/时长/峰值，搜索、重命名、多选调整训练/评估/归档用途。相同文件按 SHA-256 去重。 |
| 模型训练 | 调整名称、CPU/CUDA、采样率、训练轮数、批大小、保存间隔、线程、音高提取算法和特征编码器。本次采用提交时的训练样本清单，每次训练使用独立实验号。 |
| 声音模型 | 训练结果自动入库，支持导入已有推理权重和对应索引、重命名、查看训练参数、导出或导入模型包。相同显示名称可以保留多个训练版本。 |
| 翻唱制作 | 选择原曲和已登记的模型，生成指定秒数的试听或完整歌曲。可调移调、索引强度、清辅音保护、音量包络、人声增益和音高算法。训练时的特征编码器自动沿用。 |
| 任务与作品 | 查看运行阶段、日志和失败原因，停止进行中的任务，分别播放对齐的参考片段和生成片段，打开作品目录。 |
| 运行环境 | 选择独立引擎及其解释器、保存配置、检查 FFmpeg/PyTorch/CUDA/Demucs，下载 Applio 的基础资源。 |

**第一个听感对照**：挑一首主唱清楚的独唱，先选你自然音域内的 20 秒，移调保持 0。音色相似度可以和你没放入训练集的录音对照；字头、节奏和滑音大多跟随参考演唱。若主要问题出在和声或伴奏串音，先听输出目录的分离人声，再决定要不要重新训练。调高/降低人声半音会改变它与伴奏的音程关系。

## 数据与工程

默认工作目录为 `%LOCALAPPDATA%/VoiceCoverStudio`，也可通过 `VOICE_STUDIO_HOME` 指定。原始音频与训练用 PCM、模型文件、数据库、任务日志、分轨及翻唱输出均在其中。上游另在自己的实验目录保留训练检查点；保留该目录可用于在 Applio 中续训。异机训练包只含本次训练音频、参数和标准库启动程序。声音模型包内有权重、可选索引和模型元数据。请只加载自己训练或来源可信的权重。

| 源码 | 职责 |
| --- | --- |
| `voice_studio/app.py`、`pages.py`、`widgets.py` | 原生桌面窗口、录音与播放、工作区交互 |
| `voice_studio/store.py` | SQLite、音频质检、权重和索引管理 |
| `voice_studio/jobs.py`、`worker.py` | 后台子进程、取消、阶段日志、异常退出恢复 |
| `voice_studio/engine.py`、`portable.py` | Applio/Demucs/FFmpeg 适配、跨机器训练 |
| `tests/` | 样本去重、训练集隔离、模型包往返和音轨时长回归 |

启动异常时，提示框会给出启动日志路径，默认位于 `%LOCALAPPDATA%/VoiceCoverStudio/logs/startup.log`。启动器的 C 源码在 `launcher/`。需要自行重编时，在 Windows 上使用 Visual Studio C++ 工具执行 `cmake -S launcher -B build/launcher -A x64` 和 `cmake --build build/launcher --config Release`，把 Release 产物复制到项目根目录。

开发启动 `python -m pip install -e .` 后执行 `python -m voice_studio`，局部测试执行 `python -m unittest discover -s tests -v`。根目录 `voice_cover.py` 保留命令行训练、换声和混音入口。Windows 录音、播放依赖系统允许应用访问相应音频设备。

## 查过的上游工程

| 项目 | 已核实的能力 | 在本项目中的用途 |
| --- | --- | --- |
| [UtaiSynthesizer](https://github.com/yasoukyoku/UtaiSynthesizer) · [中文手册](https://github.com/yasoukyoku/UtaiSynthesizer/blob/main/docs/user-guide.zh-CN.md) · [Windows 发行版](https://github.com/yasoukyoku/UtaiSynthesizer/releases) | 项目式管理干声、后台 RVC/SoVITS 训练、通用 CPU 训练包、试听训练结果、时间线分轨换声和导出。 | 完整现成工作站，也是训练后直接选模型制作歌曲的交互参照。 |
| [Applio](https://github.com/IAHispano/Applio/tree/3.7.2) · [CLI](https://docs.applio.org/reference/cli/) · [Hugging Face 资源](https://huggingface.co/IAHispano/Applio/tree/main/Resources) | 预处理、音高和内容特征提取、训练、导出权重、检索索引和换声。官方托管 ContentVec 和 RMVPE。 | **实际调用的训练及换声引擎**。CPU 模式对提取和训练显式传入设备标记 `-`。 |
| [Ultimate RVC](https://github.com/JackismyShephard/ultimate-rvc) | 从指定歌曲一键制作翻唱，可管理声音模型和音频。官方本地安装方案侧重 NVIDIA。 | 一键完成整曲转换的交互参照。 |
| [Demucs](https://github.com/facebookresearch/demucs) | 在 CPU 上分离人声与伴奏。 | **实际调用的整曲分轨引擎**。 |

已验证桌面页面切换、真实 WAV 入库、模型包往返和 FFmpeg 两轨混音；训练/推理命令与 3.7.2 参数解析和任务编排用替代计算阶段验证。没有随包附带个人模型。Windows 真机麦克风、实际模型计算和最终音质需要在目标机器上验证。
