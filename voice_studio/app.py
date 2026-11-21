import os
import sys
from pathlib import Path
from PyQt5.QtCore import QLockFile,Qt,QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QApplication,QFrame,QHBoxLayout,QLabel,QMainWindow,QMessageBox,QPushButton,
                             QScrollArea,QStackedWidget,QVBoxLayout,QWidget)
from . import __version__
from .jobs import Runner
from .pages import AudioPage,TrainPage,ModelsPage,CoverPage,JobsPage,SettingsPage
from .store import Studio,workdir
from .widgets import Player,label

STYLE="""
QWidget{font-size:14px;color:#213630;background:#f5f7f3}
QFrame#rail,QWidget#rail QLabel{background:#172e29;color:#e3f2ed}
QLabel#brand{font-size:22px;font-weight:700;padding:10px 4px 23px}
QLabel#railfoot{color:#a9c7bc;padding:5px}
QPushButton#nav{background:transparent;color:#c5d9d0;text-align:left;border:none;padding:11px 15px;border-radius:7px}
QPushButton#nav:hover{background:#263f38}QPushButton#nav:checked{background:#34584b;color:white;font-weight:600}
QLabel#title{font-size:29px;font-weight:700;color:#15392b}QLabel#section{font-size:17px;font-weight:600}
QLabel#summary{color:#33634f;font-weight:600}QLabel#muted,QLabel#small{color:#577166}
QLabel#big{font-size:30px;font-weight:700}QFrame#panel,QFrame#panel QLabel{background:#ffffff}
QFrame#panel{border:1px solid #d7e2da;border-radius:9px}
QPushButton{border:1px solid #c7d6cd;border-radius:6px;background:#ffffff;padding:7px 12px}
QPushButton:hover{background:#e3eee6}QPushButton#primary{background:#17674f;color:white;border-color:#17674f;font-weight:600}
QPushButton#primary:hover{background:#165b46}QPushButton:disabled{color:#89968f;background:#ecf0eb;border-color:#dce4dc}
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox{background:white;border:1px solid #c8d5cc;border-radius:5px;padding:5px 8px;min-height:21px}
QTableWidget,QPlainTextEdit{background:white;alternate-background-color:#f5f8f4;border:1px solid #d1ddd4;border-radius:6px;selection-background-color:#cbe6d7;selection-color:#15362a}
QHeaderView::section{background:#e8efe9;color:#435f51;border:none;padding:8px;text-align:left}
QPlainTextEdit#console{background:#1e302a;color:#dce9e1;font-family:Consolas,monospace;border:none;padding:8px}
QSlider::groove:horizontal{height:4px;background:#c6d8cb}QSlider::handle:horizontal{width:13px;margin:-5px 0;background:#347758;border-radius:6px}
QStatusBar{color:#3c6954}QScrollArea{border:0}
"""
class Window(QMainWindow):
    def __init__(self,store):
        super().__init__();self.store=store;self.runner=Runner(store);self.runner.poll();self.prev=None
        self.setWindowTitle("歌声工作台 · Voice Cover Studio");self.resize(1120,760);self.setMinimumSize(820,580)
        root=QWidget();self.setCentralWidget(root);main=QHBoxLayout(root);main.setContentsMargins(0,0,0,0);main.setSpacing(0)
        rail=QFrame();rail.setObjectName("rail");rail.setFixedWidth(170);left=QVBoxLayout(rail);left.setContentsMargins(12,17,12,13);left.setSpacing(5)
        left.addWidget(label("歌声工作台","brand"));self.nav=[]
        for i,title in enumerate(("音频库","模型训练","声音模型","翻唱制作","任务与作品","运行环境")):
            b=QPushButton(title);b.setObjectName("nav");b.setCheckable(True);b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False,n=i:self.goto(n));left.addWidget(b);self.nav.append(b)
        left.addStretch();left.addWidget(label("Voice Cover Studio\nv"+__version__,"railfoot"));main.addWidget(rail)
        right=QVBoxLayout();right.setContentsMargins(0,0,0,4);main.addLayout(right,1)
        self.stack=QStackedWidget();right.addWidget(self.stack,1);self.player=Player();right.addWidget(self.player)
        self.settings=SettingsPage(self);self.audio=AudioPage(self);self.train=TrainPage(self);self.models=ModelsPage(self);self.cover=CoverPage(self);self.jobs=JobsPage(self)
        self.pages=[self.audio,self.train,self.models,self.cover,self.jobs,self.settings]
        for page in self.pages:
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.stack.addWidget(scroll)
        self.setStyleSheet(STYLE);self.goto(0);self.refresh();self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(800)
    def goto(self,i):
        self.stack.setCurrentIndex(i)
        for ix,b in enumerate(self.nav):b.setChecked(i==ix)
    def refresh(self):
        for p in self.pages:
            if hasattr(p,"refresh"):p.refresh()
    def can_submit(self):
        self.runner.poll()
        if self.runner.active():
            QMessageBox.information(self,"已有任务","当前任务正在执行，可以在「任务与作品」查看日志或停止。");return False
        return True
    def engine_ok(self):
        path=self.settings.values()["engine"]
        if not path or not (Path(path)/"core.py").is_file():
            self.goto(5);QMessageBox.information(self,"配置引擎","请选择含 core.py 的 Applio 独立版目录，保存后再运行。");return False
        self.store.setting("runtime",self.settings.values());return True
    def submit(self,kind,title,spec):
        try:
            key=self.runner.start(kind,title,spec)
        except (OSError,RuntimeError) as e:
            QMessageBox.warning(self,"任务未启动",str(e));return
        self.goto(4);self.jobs.refresh();self.jobs.focus(key);return key
    def tick(self):
        self.runner.poll()
        rows=self.store.rows("SELECT id,status FROM jobs ORDER BY rowid DESC LIMIT 1")
        state=tuple(rows[0].values()) if rows else ()
        if self.prev!=state:
            self.prev=state;self.refresh()
        elif self.stack.currentIndex()==4 and self.runner.active():self.jobs.refresh()
    def closeEvent(self,event):
        self.player.media.stop()
        if self.runner.active():self.statusBar().showMessage("后台任务继续执行，重开可查看。")
        super().closeEvent(event)

def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling,True)
    app=QApplication(sys.argv);app.setApplicationName("Voice Cover Studio")
    app.setFont(QFont("Microsoft YaHei UI" if os.name=="nt" else "Noto Sans CJK SC",10))
    root=workdir();root.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(root/"desktop.lock"));lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None,"歌声工作台","这个工作目录已经有一个桌面窗口。");return 0
    store=Studio(root);window=Window(store);window.show()
    try:return app.exec_()
    finally:store.db.close();lock.unlock()
