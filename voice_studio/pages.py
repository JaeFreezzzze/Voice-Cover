import json
import os
from pathlib import Path

from PyQt5.QtCore import Qt,QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog,QDialogButtonBox,QFileDialog,QHBoxLayout,QInputDialog,QLabel,
        QLineEdit,QMessageBox,QPlainTextEdit,QSplitter,QVBoxLayout,QWidget)
from .store import COVER_DEFAULT,DATASET,EMBEDDERS,ROLES,STATUS,TRAIN_DEFAULT,TYPES,duration_text
from .widgets import (PathField,RecordDialog,Waveform,button,choices,decimal,fill,fmtform,integer,
                      label,panel,selected,strip,table)

AUDIO_FILTER="音频 (*.wav *.flac *.mp3 *.m4a *.ogg *.aac *.aiff *.opus *.wma);;所有文件 (*)"
def pairs(values):
    return [(s,s) for s in values]

class Page(QWidget):
    def __init__(self,window,title):
        super().__init__();self.w=window;self.store=window.store
        self.body=QVBoxLayout(self);self.body.setContentsMargins(26,22,26,16);self.body.setSpacing(13)
        self.body.addWidget(label(title,"title"))
    def warn(self,msg):
        QMessageBox.information(self,"歌声工作台",msg)
    def ready(self):
        return self.w.can_submit()

class AudioPage(Page):
    def __init__(self,w):
        super().__init__(w,"音频库")
        self.summary=label("","summary");self.body.addWidget(self.summary)
        self.search=QLineEdit();self.search.setPlaceholderText("搜索样本名称")
        self.role=choices([("全部用途","all")]+[(v,k) for k,v in ROLES.items()])
        self.body.addLayout(strip(self.search,self.role,button("导入音频",self.add),button("录制样本",self.record,True)))
        self.body.addLayout(strip(button("打开数据集目录",self.open_dataset),button("导入工程数据集",self.import_dataset),None))
        self.t=table(["名称","用途","时长","采样率","峰值 dBFS"],True);self.body.addWidget(self.t,1)
        self.body.addLayout(strip(button("重命名",self.rename),button("设为训练",lambda:self.mark("train")),
                                  button("设为评估",lambda:self.mark("holdout")),button("归档",lambda:self.mark("archived")),None))
        box,l=panel();self.desc=label("选择一条录音查看波形，双击试听。","muted")
        self.wave=Waveform();l.addWidget(self.desc);l.addWidget(self.wave);self.body.addWidget(box)
        self.t.itemSelectionChanged.connect(self.detail);self.t.itemDoubleClicked.connect(lambda *a:self.listen())
        self.search.textChanged.connect(self.refresh);self.role.currentIndexChanged.connect(self.refresh)
    def refresh(self,*_):
        rows=self.store.audio()
        self.summary.setText(f"共 {len(rows)} 条录音    ·    训练 {duration_text(sum(r['seconds'] for r in rows if r['role']=='train'))}    ·    评估 {duration_text(sum(r['seconds'] for r in rows if r['role']=='holdout'))}")
        filt=self.role.currentData();q=self.search.text().strip().lower()
        fill(self.t,[(r["id"],[r["title"],ROLES[r["role"]],duration_text(r["seconds"]),f"{r['rate']} Hz",r["peak"]])
            for r in rows if (filt=="all" or filt==r["role"]) and q in r["title"].lower()])
        self.detail()
    def row(self):
        ids=selected(self.t)
        return self.store.get("audio",ids[0]) if ids else None
    def detail(self):
        row=self.row()
        self.wave.show_peaks(json.loads(row["peaks"]) if row else [])
        if row:
            self.desc.setText(f"{row['title']}    ·    峰值 {row['peak']} dBFS    ·    接近满幅 {row['clipped']} 个采样点")
            if self.w.stack.currentIndex()==0 and self.w.player.path!=row["wav"]:
                self.w.player.load(row["wav"],row["title"])
        else:self.desc.setText("选择录音可查看波形和峰值，双击试听。")
    def listen(self):
        row=self.row()
        if row:self.w.player.load(row["wav"],row["title"],True)
    def add(self):
        if not self.ready():return
        paths=QFileDialog.getOpenFileNames(self,"导入录音","",AUDIO_FILTER)[0]
        if paths:
            self.w.submit("ingest",f"导入 {len(paths)} 条音频",{"paths":paths,"role":"train"})
    def open_dataset(self):
        for group in ("train","test"):
            (DATASET/group).mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATASET)))
    def import_dataset(self):
        if self.ready():self.w.submit("dataset","导入工程数据集",{})
    def record(self):
        if not self.ready():return
        self.w.player.media.stop()
        dialog=RecordDialog(self.store.root,self)
        if dialog.exec_()==QDialog.Accepted:
            self.w.submit("ingest",dialog.name.text() or "麦克风录音",
                {"paths":[str(dialog.path)],"title":dialog.name.text() or "麦克风录音","role":dialog.role.currentData(),"recorded":True})
    def rename(self):
        row=self.row()
        if not row:return self.warn("请先选择录音。")
        name,ok=QInputDialog.getText(self,"重命名录音","名称",text=row["title"])
        if ok and name.strip():self.store.change_audio([row["id"]],title=name);self.w.refresh()
    def mark(self,role):
        keys=selected(self.t)
        if not keys:return self.warn("请先选择一条或多条录音。")
        self.store.change_audio(keys,role=role);self.w.refresh()

class TrainPage(Page):
    def __init__(self,w):
        super().__init__(w,"模型训练")
        p=dict(TRAIN_DEFAULT,**self.store.get_setting("training",{}));self.stats=label("","summary")
        self.body.addWidget(self.stats);self.name=QLineEdit(p["name"])
        self.device=choices([("CPU · 本机","cpu"),("CUDA · 设备 0","gpu")],p["device"])
        self.rate=choices([(str(v)+" Hz",v) for v in (32000,40000,48000)],p["rate"])
        self.epochs=integer(1,10000,p["epochs"]);self.batch=integer(1,50,p["batch"]);self.interval=integer(1,100,p["interval"])
        self.cores=integer(1,64,p["cores"]);self.f0=choices(pairs(["rmvpe","fcpe","crepe"]),p["f0"])
        self.embedder=choices(pairs(EMBEDDERS),p["embedder"])
        card,l=panel();l.addWidget(label("训练配置","section"));line=QHBoxLayout()
        left=fmtform();right=fmtform()
        for k,v in [("模型名称",self.name),("训练设备",self.device),("采样率",self.rate),("音高提取",self.f0),("特征编码器",self.embedder)]:left.addRow(k,v)
        for k,v in [("训练轮数",self.epochs),("批大小",self.batch),("每几轮保存",self.interval),("CPU 线程",self.cores)]:right.addRow(k,v)
        line.addLayout(left,1);line.addSpacing(20);line.addLayout(right,1);l.addLayout(line);self.body.addWidget(card)
        self.body.addWidget(label("本次只使用标记为「训练」的录音。训练完成后，权重和参数会登记到声音模型库。","muted"))
        self.body.addLayout(strip(button("开始本机训练",lambda:self.launch(False),True),button("导出异机训练包",lambda:self.launch(True)),None))
        self.body.addStretch()
    def refresh(self):
        samples=[r for r in self.store.audio() if r["role"]=="train"]
        self.stats.setText(f"训练数据集    {len(samples)} 条录音    ·    {duration_text(sum(r['seconds'] for r in samples))}")
    def params(self):
        return dict(name=self.name.text().strip(),device=self.device.currentData(),rate=self.rate.currentData(),
            epochs=self.epochs.value(),batch=self.batch.value(),interval=self.interval.value(),cores=self.cores.value(),
            f0=self.f0.currentData(),embedder=self.embedder.currentData())
    def launch(self,portable):
        if not self.ready():return
        p=self.params();ids=[r["id"] for r in self.store.audio() if r["role"]=="train"]
        if not ids or not p["name"]:return self.warn("请填写模型名称，并在音频库中至少设一条训练样本。")
        spec={"params":p,"samples":ids,"settings":self.w.settings.values()}
        if portable:
            dest=QFileDialog.getSaveFileName(self,"导出异机训练包","training.zip","训练包 (*.zip)")[0]
            if not dest:return
            spec["dest"]=dest
        elif not self.w.engine_ok():return
        self.store.setting("training",p);self.w.submit("bundle" if portable else "train",p["name"],spec)

class ModelsPage(Page):
    def __init__(self,w):
        super().__init__(w,"声音模型")
        self.body.addLayout(strip(label("推理权重与模型版本","summary"),None,button("导入模型",self.add,True),button("导出模型包",self.export)))
        self.t=table(["模型名称","特征编码器","检索索引","登记时间"]);self.body.addWidget(self.t,1)
        self.info=QPlainTextEdit();self.info.setReadOnly(True);self.info.setMaximumHeight(138)
        self.body.addWidget(self.info);self.body.addLayout(strip(button("用此模型翻唱",self.use,True),button("重命名",self.rename),None))
        self.t.itemSelectionChanged.connect(self.detail);self.t.itemDoubleClicked.connect(lambda *_:self.use())
    def refresh(self):
        fill(self.t,[(r["id"],[r["title"],r["embedder"],"有" if r["idx"] else "无",r["created"].replace("T"," ")])
                     for r in self.store.models()]);self.detail()
    def row(self):
        keys=selected(self.t)
        return self.store.get("models",keys[0]) if keys else None
    def detail(self):
        r=self.row()
        if not r:self.info.setPlainText("选择模型查看权重、索引和训练参数。");return
        p=json.loads(r["params"]);samples=p.pop("samples",[])
        self.info.setPlainText(f"权重    {r['weights']}\n索引    {r['idx'] or '无'}\n"+
            (f"训练样本    {len(samples)} 条\n" if samples else "")+json.dumps(p,ensure_ascii=False,indent=2))
    def use(self):
        row=self.row()
        if not row:return self.warn("请先选择模型。")
        self.w.goto(3);self.w.cover.model.setCurrentIndex(self.w.cover.model.findData(row["id"]))
    def rename(self):
        row=self.row()
        if not row:return self.warn("请先选择模型。")
        name,ok=QInputDialog.getText(self,"重命名模型","名称",text=row["title"])
        if ok and name.strip():
            with self.store.db:self.store.db.execute("UPDATE models SET title=? WHERE id=?",(name.strip(),row["id"]))
            self.w.refresh()
    def add(self):
        if not self.ready():return
        path=QFileDialog.getOpenFileName(self,"导入自己训练或信任的模型","","声音模型 (*.pth *.vmodel)")[0]
        if not path:return
        if path.lower().endswith(".vmodel"):
            self.w.submit("model",Path(path).stem,{"package":path});return
        d=QDialog(self);d.setWindowTitle("登记声音模型");f=fmtform();d.setLayout(f)
        title=QLineEdit(Path(path).stem);idx=PathField(pattern="索引 (*.index)")
        emb=choices(pairs(EMBEDDERS));f.addRow("名称",title);f.addRow("配套索引（可选）",idx);f.addRow("训练时的编码器",emb)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);f.addRow(buttons)
        if d.exec_()==QDialog.Accepted:
            self.w.submit("model",title.text(),dict(title=title.text(),weights=path,index=idx.value(),embedder=emb.currentData()))
    def export(self):
        if not self.ready():return
        r=self.row()
        if not r:return self.warn("请先选择模型。")
        dest=QFileDialog.getSaveFileName(self,"导出模型包","voice.vmodel","声音模型包 (*.vmodel)")[0]
        if dest:self.w.submit("export",r["title"],dict(model=r["id"],dest=dest))

class CoverPage(Page):
    def __init__(self,w):
        super().__init__(w,"翻唱制作")
        p=dict(COVER_DEFAULT,**self.store.get_setting("conversion",{}))
        self.song=PathField(pattern=AUDIO_FILTER);self.model=choices([]);self.mode=choices([("整首歌曲 · 分轨并混音",False),("纯人声 · 直接换声",True)])
        card,l=panel();l.addWidget(label("歌曲与声音","section"));f=fmtform()
        f.addRow("参考音频",self.song);f.addRow("声音模型",self.model);f.addRow("输入类型",self.mode);l.addLayout(f);self.body.addWidget(card)
        self.pitch=integer(-24,24,p["pitch"]);self.index=decimal(0,1,p["index_rate"]);self.protect=decimal(0,.5,p["protect"],.01)
        self.envelope=decimal(0,1,p["envelope"]);self.gain=decimal(-30,18,p["vocal_db"],1)
        self.device=choices([("CPU","cpu"),("CUDA · 设备 0","gpu")],p["device"]);self.f0=choices(pairs(["rmvpe","fcpe","crepe"]),p["f0"])
        card,l=panel();l.addWidget(label("声音参数","section"));a=fmtform();b=fmtform()
        for k,v in [("音高偏移（半音）",self.pitch),("索引强度",self.index),("清辅音保护",self.protect),("音量包络",self.envelope)]:a.addRow(k,v)
        for k,v in [("换声设备",self.device),("音高提取",self.f0),("混音人声增益（dB）",self.gain)]:b.addRow(k,v)
        row=QHBoxLayout();row.addLayout(a,1);row.addSpacing(18);row.addLayout(b,1);l.addLayout(row);self.body.addWidget(card)
        self.mode.currentIndexChanged.connect(lambda:self.gain.setEnabled(not self.mode.currentData()))
        self.start=integer(0,86400,p["start"]);self.length=integer(1,600,p["seconds"] or 20)
        self.body.addLayout(strip(label("试听起点（秒）"),self.start,label("长度（秒）"),self.length,None))
        self.body.addLayout(strip(button("生成片段试听",lambda:self.launch(True)),button("生成完整作品",lambda:self.launch(False),True),None))
        self.body.addStretch()
    def refresh(self):
        prev=self.model.currentData();self.model.clear()
        for r in self.store.models():self.model.addItem(r["title"]+" · "+r["id"][:6],r["id"])
        ix=self.model.findData(prev)
        if ix>=0:self.model.setCurrentIndex(ix)
    def launch(self,preview):
        if not self.ready():return
        path=self.song.value();mid=self.model.currentData()
        if not mid or not Path(path).is_file():return self.warn("请选择歌曲文件和一个已登记的声音模型。")
        if not self.w.engine_ok():return
        p=dict(device=self.device.currentData(),f0=self.f0.currentData(),pitch=self.pitch.value(),index_rate=self.index.value(),
            protect=self.protect.value(),envelope=self.envelope.value(),vocal_db=self.gain.value(),start=self.start.value(),seconds=self.length.value())
        self.store.setting("conversion",p)
        if not preview:p=dict(p,start=0,seconds=None)
        self.w.submit("cover",Path(path).stem+(" · 试听" if preview else " · 完整作品"),
            dict(song=path,model=mid,params=p,settings=self.w.settings.values(),dry=self.mode.currentData()))

class SettingsPage(Page):
    def __init__(self,w):
        super().__init__(w,"运行环境")
        s=self.store.get_setting("runtime",{});card,l=panel();l.addWidget(label("本机引擎","section"));f=fmtform()
        self.engine=PathField("dir",value=s.get("engine",""))
        self.engine.line.setPlaceholderText("选择解压后含 core.py 的 Applio 文件夹")
        self.py=PathField(value=s.get("engine_python",""));self.split=PathField(value=s.get("split_python",""))
        self.split.line.setPlaceholderText("留空时使用项目下的 .splitter 环境")
        self.py.line.setPlaceholderText("留空时自动探测 Applio 的 Python 环境")
        f.addRow("Applio 3.7.2 目录",self.engine);f.addRow("引擎解释器",self.py);f.addRow("Demucs 解释器",self.split);l.addLayout(f)
        l.addLayout(strip(button("保存配置",self.save,True),button("检查环境",self.check),button("下载引擎基础资源",self.assets),None));self.body.addWidget(card)
        info=label("训练用 Applio，纯人声换声另需 FFmpeg。带伴奏的歌曲还需安装 CPU 分轨。","muted")
        info.setWordWrap(True);self.body.addWidget(info)
        if os.name=="nt":
            self.body.addLayout(strip(button("安装 FFmpeg",lambda:self.install("ffmpeg")),
                                      button("安装 CPU 分轨",lambda:self.install("splitter")),None))
        self.body.addLayout(strip(button("下载 Applio 3.7.2 Windows 包",lambda:QDesktopServices.openUrl(QUrl("https://huggingface.co/IAHispano/Applio/resolve/main/Compiled/Windows/ApplioV3.7.2.zip"))),
              button("Hugging Face 模型资源",lambda:QDesktopServices.openUrl(QUrl("https://huggingface.co/IAHispano/Applio/tree/main/Resources"))),None))
        box,l=panel();l.addWidget(label("工作目录","section"));path=label(str(self.store.root),"muted");path.setTextInteractionFlags(Qt.TextSelectableByMouse);l.addWidget(path)
        l.addLayout(strip(button("打开工作目录",lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))),None))
        self.body.addWidget(box);self.body.addStretch()
    def values(self):
        return dict(engine=self.engine.value(),engine_python=self.py.value(),split_python=self.split.value())
    def save(self):
        self.store.setting("runtime",self.values());self.w.statusBar().showMessage("运行环境已保存",4500)
    def install(self,component):
        if self.ready():
            title="安装 FFmpeg" if component=="ffmpeg" else "安装 CPU 分轨"
            self.w.submit("setup",title,dict(component=component))
    def assets(self):
        if self.ready() and self.w.engine_ok():
            self.w.submit("assets","下载上游基础资源", self.values())
    def check(self):
        if self.ready():
            self.save();self.w.submit("check","运行环境诊断",self.values())

class JobsPage(Page):
    def __init__(self,w):
        super().__init__(w,"任务与作品")
        self.t=table(["名称","任务","状态","当前阶段","创建时间"])
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setObjectName("console")
        split=QSplitter(Qt.Vertical);split.addWidget(self.t);split.addWidget(self.log);split.setSizes([260,180]);self.body.addWidget(split,1)
        self.original=button("听参考片段",lambda:self.play_file("reference"))
        self.result=button("听生成结果",lambda:self.play_file("output"),True)
        self.folder=button("打开文件位置",self.open_dir);self.cancel=button("停止任务",self.abort)
        self.body.addLayout(strip(self.original,self.result,self.folder,None,self.cancel))
        self.t.itemSelectionChanged.connect(self.detail);self.last_log=None
    def focus(self,key):
        for row in range(self.t.rowCount()):
            if self.t.item(row,0).data(Qt.UserRole)==key:
                self.t.selectRow(row);self.detail();return
    def refresh(self):
        rows=self.store.jobs()
        fill(self.t,[(r["id"],[r["title"],TYPES[r["kind"]],STATUS[r["status"]],r["stage"],r["created"].replace("T"," ")]) for r in rows])
        if self.t.rowCount() and not selected(self.t):self.t.selectRow(0)
        self.detail()
    def row(self):
        ids=selected(self.t);return self.store.get("jobs",ids[0]) if ids else None
    def detail(self):
        row=self.row();res=json.loads(row["result"]) if row else {}
        self.original.setEnabled(bool(res.get("reference")));self.result.setEnabled(bool(res.get("output")))
        self.folder.setEnabled(bool(row));self.cancel.setEnabled(bool(row and row["status"] in ("running","pending")))
        if not row:self.log.setPlainText("尚无任务记录。");return
        folder=self.store.root/"jobs"/row["id"];p=folder/"run.log";size=p.stat().st_size if p.exists() else 0
        stamp=(row["id"],size,row["status"])
        if stamp!=self.last_log:
            tail=""
            if size:
                with p.open("rb") as f:
                    f.seek(max(0,size-32768));tail=f.read().decode("utf-8",errors="replace")
            if row["error"]:tail+="\n"+row["error"]
            self.log.setPlainText(tail or row["stage"])
            bar=self.log.verticalScrollBar();bar.setValue(bar.maximum());self.last_log=stamp
    def play_file(self,field):
        row=self.row()
        if row:
            path=json.loads(row["result"]).get(field)
            if path:self.w.player.load(path,("参考 · " if field=="reference" else "生成 · ")+row["title"],True)
    def open_dir(self):
        row=self.row()
        if not row:return
        res=json.loads(row["result"]);dest=res.get("output") or res.get("file")
        if res.get("model"):dest=self.store.get("models",res["model"])["weights"]
        folder=Path(dest).parent if dest else self.store.root/"jobs"/row["id"]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    def abort(self):
        row=self.row()
        if row and QMessageBox.question(self,"停止任务","停止当前任务及其子进程？已生成的中间文件将保留。")==QMessageBox.Yes:
            try:self.w.runner.stop(row["id"])
            except (OSError,RuntimeError) as e:self.warn(str(e))
            self.refresh()
