import json
import time
import wave
from array import array
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtMultimedia import QAudio, QAudioDeviceInfo, QAudioFormat, QAudioInput, QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import (QAbstractItemView,QComboBox,QDialog,QDialogButtonBox,QDoubleSpinBox,QFileDialog,
    QFormLayout,QFrame,QHBoxLayout,QHeaderView,QLabel,QLineEdit,QMessageBox,QProgressBar,QPushButton,
    QSlider,QSpinBox,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget)
from .store import duration_text, uid

def label(text, name=""):
    widget=QLabel(text)
    widget.setObjectName(name)
    return widget

def button(text, action, primary=False):
    b=QPushButton(text);b.setObjectName("primary" if primary else "action")
    b.clicked.connect(action);b.setCursor(Qt.PointingHandCursor)
    return b

def strip(*widgets):
    row=QHBoxLayout();row.setSpacing(9)
    for w in widgets:
        if w is None: row.addStretch()
        else: row.addWidget(w)
    return row

def panel():
    box=QFrame();box.setObjectName("panel")
    lay=QVBoxLayout(box);lay.setContentsMargins(18,16,18,16);lay.setSpacing(11)
    return box,lay

def choices(pairs, value=None):
    c=QComboBox()
    for title,data in pairs: c.addItem(title,data)
    idx=c.findData(value)
    if idx>=0: c.setCurrentIndex(idx)
    return c

def integer(lo,hi,value):
    w=QSpinBox();w.setRange(lo,hi);w.setValue(value)
    return w

def decimal(lo,hi,value,step=0.05):
    w=QDoubleSpinBox();w.setRange(lo,hi);w.setDecimals(2);w.setSingleStep(step);w.setValue(value)
    return w

def fmtform():
    f=QFormLayout();f.setVerticalSpacing(12);f.setHorizontalSpacing(22)
    f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    return f

def table(columns,multi=False):
    t=QTableWidget(0,len(columns));t.setHorizontalHeaderLabels(columns)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers);t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
    t.setShowGrid(False);t.verticalHeader().hide();t.verticalHeader().setDefaultSectionSize(36)
    header=t.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setSectionResizeMode(0,QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    return t

def selected(t):
    return [t.item(r.row(),0).data(Qt.UserRole) for r in t.selectionModel().selectedRows()]

def fill(t, rows):
    keep=set(selected(t));t.blockSignals(True)
    t.setRowCount(0)
    for key,values in rows:
        n=t.rowCount();t.insertRow(n)
        for col,text in enumerate(values):
            item=QTableWidgetItem(str(text));item.setData(Qt.UserRole,key);t.setItem(n,col,item)
        if key in keep:
            t.item(n,0).setSelected(True)
            for col in range(1,len(values)):t.item(n,col).setSelected(True)
    t.blockSignals(False)

class PathField(QWidget):
    def __init__(self, mode="file", pattern="所有文件 (*)", value=""):
        super().__init__();self.mode=mode;self.pattern=pattern
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0)
        self.line=QLineEdit(value);row.addWidget(self.line)
        row.addWidget(button("浏览…",self.pick))
    def pick(self):
        value=(QFileDialog.getExistingDirectory(self,"选择目录",self.line.text()) if self.mode=="dir" else
               QFileDialog.getOpenFileName(self,"选择文件",self.line.text(),self.pattern)[0])
        if value:self.line.setText(value)
    def value(self):return self.line.text().strip().strip('"')

class Waveform(QWidget):
    def __init__(self):
        super().__init__();self.peaks=[];self.setMinimumHeight(60)
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        w,h=self.width(),self.height();y=h/2
        p.setPen(QPen(QColor("#c9d5ce"),1));p.drawLine(1,int(y),w-1,int(y))
        if self.peaks:
            stride=w/len(self.peaks);p.setPen(QPen(QColor("#17856c"),max(1.2,stride*.56),Qt.SolidLine,Qt.RoundCap))
            for i,a in enumerate(self.peaks):
                dy=max(1,a**.65*(h/2-4));x=int((i+.5)*stride);p.drawLine(x,int(y-dy),x,int(y+dy))
        p.end()
    def show_peaks(self, peaks):
        self.peaks=peaks;self.update()

class Player(QWidget):
    def __init__(self):
        super().__init__();self.setObjectName("player")
        self.media=QMediaPlayer(self);self.media.setVolume(85);self.path=None
        self.play=button("播放",self.toggle);self.play.setEnabled(False)
        self.caption=label("未选择试听音频","muted")
        self.slider=QSlider(Qt.Horizontal);self.slider.setRange(0,0);self.slider.setMinimumWidth(75)
        self.slider.sliderMoved.connect(self.media.setPosition)
        self.time=label("00:00 / 00:00","small")
        layout=QHBoxLayout(self);layout.addWidget(self.play);layout.addWidget(self.caption);layout.addWidget(self.slider,1);layout.addWidget(self.time)
        self.media.durationChanged.connect(lambda n:self.slider.setRange(0,n))
        self.media.positionChanged.connect(self.position)
        self.media.stateChanged.connect(lambda state:self.play.setText("暂停" if state==QMediaPlayer.PlayingState else "播放"))
        self.media.error.connect(lambda:self.caption.setText(self.media.errorString() or "音频设备或解码器不可用"))
    def position(self,n):
        if not self.slider.isSliderDown():self.slider.setValue(n)
        self.time.setText(duration_text(n/1000)+" / "+duration_text(self.media.duration()/1000))
    def load(self,path,title,autoplay=False):
        self.media.stop();self.path=path
        self.media.setMedia(QMediaContent(QUrl.fromLocalFile(str(path))) if path else QMediaContent())
        self.caption.setText(title);self.play.setEnabled(bool(path))
        if path and autoplay:self.media.play()
    def toggle(self):
        if self.media.state()==QMediaPlayer.PlayingState:self.media.pause()
        else:self.media.play()

class RecordDialog(QDialog):
    def __init__(self,root,parent=None):
        super().__init__(parent);self.setWindowTitle("录制歌声样本");self.setMinimumWidth(465)
        self.path=Path(root)/"recordings"/(uid()+".wav");self.audio=None;self.io=None;self.writer=None
        self.frames=0;self.pending=b"";self.started=0;self.failed=False
        self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.tick)
        outer=QVBoxLayout(self);outer.addWidget(label("录制干声","section"))
        self.name=QLineEdit("清唱 "+time.strftime("%m-%d %H-%M"));self.role=choices([("训练","train"),("评估","holdout")])
        self.devices=QAudioDeviceInfo.availableDevices(QAudio.AudioInput);self.input=QComboBox()
        for item in self.devices:self.input.addItem(item.deviceName())
        default=QAudioDeviceInfo.defaultInputDevice().deviceName()
        if self.input.findText(default)>=0:self.input.setCurrentText(default)
        f=fmtform();f.addRow("名称",self.name);f.addRow("用途",self.role);f.addRow("输入设备",self.input);outer.addLayout(f)
        self.clock=label("00:00","big");outer.addWidget(self.clock)
        self.level=QProgressBar();self.level.setRange(0,100);self.level.setTextVisible(False);outer.addWidget(self.level)
        self.hint=label("戴耳机录制，避免伴奏进入麦克风。","muted");outer.addWidget(self.hint)
        self.record=button("开始录音",self.toggle,True);self.save=button("保存到音频库",self.accept)
        self.save.setEnabled(False);outer.addLayout(strip(self.record,self.save,None,button("取消",self.reject)))
        if not self.devices:self.hint.setText("未发现输入设备，请连接麦克风并开启录音权限。");self.record.setEnabled(False)
    def toggle(self):
        if self.audio:
            self.stop();return
        device=self.devices[self.input.currentIndex()]
        fmt=QAudioFormat();fmt.setChannelCount(1);fmt.setSampleSize(16);fmt.setCodec("audio/pcm")
        fmt.setByteOrder(QAudioFormat.LittleEndian);fmt.setSampleType(QAudioFormat.SignedInt)
        found=False
        for channels in (1,2):
            fmt.setChannelCount(channels)
            for rate in (48000,44100,32000):
                fmt.setSampleRate(rate)
                if device.isFormatSupported(fmt):
                    found=True
                    break
            if found:break
        if not found:
            QMessageBox.warning(self,"输入格式","设备未提供 32/44.1/48 kHz 的 16 位 PCM 输入。");return
        self.frames=0
        try:
            self.writer=wave.open(str(self.path),"wb");self.writer.setparams((1,2,rate,0,"NONE",""))
            self.audio=QAudioInput(device,fmt,self);self.io=self.audio.start()
            if self.io is None:raise OSError("麦克风启动失败，请检查系统权限。")
            self.io.readyRead.connect(self.drain);self.rate=rate;self.channels=channels;self.frames=0;self.pending=b"";self.failed=False
            self.timer.start();self.record.setText("停止录音");self.input.setEnabled(False);self.save.setEnabled(False)
            self.hint.setText("正在录音，保存前可停止并重新录制。")
        except Exception as exc:
            self.stop();self.hint.setText(str(exc))
    def drain(self):
        if not self.io or not self.writer:return
        raw=self.pending+bytes(self.io.readAll());width=2*self.channels
        n=len(raw)//width*width;self.pending=raw[n:]
        if n:
            samples=array("h",raw[:n])
            if self.channels==2:
                samples=array("h",((a+b)//2 for a,b in zip(samples[::2],samples[1::2])))
            self.writer.writeframesraw(samples.tobytes());self.frames+=len(samples)
            peak=max(abs(s) for s in samples);self.level.setValue(min(100,int(100*(peak/32768)**.5)))
    def tick(self):
        self.clock.setText(duration_text(self.frames/self.rate))
        if self.audio and self.audio.error() not in (QAudio.NoError,QAudio.UnderrunError):
            self.stop();self.hint.setText("输入设备已停止，已采集的片段可以保存。")
    def stop(self):
        self.timer.stop()
        if self.audio:
            self.drain();self.audio.stop();self.audio.deleteLater();self.audio=None;self.io=None
        if self.writer:self.writer.close();self.writer=None
        self.save.setEnabled(self.frames>0);self.record.setText("重新录音");self.input.setEnabled(True)
        self.level.setValue(0);self.hint.setText("录音已停止。")
    def done(self,code):
        self.stop()
        if code!=self.Accepted:self.path.unlink(missing_ok=True)
        super().done(code)
