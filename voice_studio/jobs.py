"""独立任务进程。日志落盘，界面可重开并观察任务。"""
from datetime import datetime
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from PyQt5.QtCore import QLockFile

def lock_at(root,key):
    lock=QLockFile(str(root/"jobs"/key/"worker.lock"))
    lock.setStaleLockTime(0)
    return lock

class Runner:
    def __init__(self,store):
        self.store=store;self.children={}
    def start(self,kind,title,spec):
        if self.active():
            raise RuntimeError("已有任务正在运行，请等待完成。")
        key=self.store.new_job(kind,title,spec);folder=self.store.root/"jobs"/key
        env=dict(os.environ,PYTHONUTF8="1",PYTHONIOENCODING="utf-8",PYTHONUNBUFFERED="1")
        try:
            with (folder/"run.log").open("wb") as log:
                p=subprocess.Popen([sys.executable,"-m","voice_studio.worker",str(self.store.root),key],
                    cwd=Path(__file__).resolve().parent.parent,stdout=log,stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,env=env,start_new_session=os.name!="nt",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            self.children[key]=p
        except Exception as e:
            self.store.job_state(key,"error","启动失败",error=str(e));raise
        return key
    def active(self):
        return self.store.rows("SELECT id,status,created FROM jobs WHERE status IN ('pending','running')")
    def poll(self):
        for key,p in list(self.children.items()):
            if p.poll() is not None:
                self.children.pop(key)
                row=self.store.get("jobs",key)
                if row["status"] in ("running","pending"):
                    self.store.job_state(key,"interrupted","进程已结束",error=f"退出码 {p.returncode}，请查看日志。")
        for r in self.active():
            if r["id"] in self.children:continue
            lock=lock_at(self.store.root,r["id"])
            if (datetime.now()-datetime.fromisoformat(r["created"])).total_seconds()>15 and lock.tryLock(0):
                lock.unlock()
                self.store.job_state(r["id"],"interrupted","进程已中断")
    def stop(self,key):
        row=self.store.get("jobs",key)
        if row["status"] not in ("pending","running"):return
        p=self.children.get(key)
        if p and p.poll() is not None:return
        if p:pid=p.pid
        else:
            lock=lock_at(self.store.root,key);valid,pid,_,_=lock.getLockInfo()
            if not valid:raise RuntimeError("任务进程尚未就绪，请稍后再试。")
        try:
            if os.name=="nt":
                subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],check=True,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(pid,signal.SIGKILL)
            if p:p.wait(timeout=5)
        except ProcessLookupError:
            pass
        if self.store.get("jobs",key)["status"] in ("pending","running"):
            self.store.job_state(key,"interrupted","已手动停止")
