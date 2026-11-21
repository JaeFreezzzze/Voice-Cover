"""在已装 Applio 3.7.2 的训练机器运行。包内仅使用 Python 标准库。"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import uuid
from zipfile import ZipFile

def run():
    import engine
    here=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser()
    parser.add_argument("--engine", required=True)
    parser.add_argument("--engine-python")
    parser.add_argument("--device", choices=["gpu","cpu"], default="gpu")
    args=parser.parse_args()
    config=json.loads((here/"training.json").read_text(encoding="utf-8"))
    p=dict(config["parameters"],device=args.device)
    experiment="vc_"+uuid.uuid4().hex[:16]
    weights,idx=engine.train(SimpleNamespace(**dict(p,name=experiment,data=here/"dataset",
                          engine=args.engine,engine_python=args.engine_python)))
    result=here/(experiment+".vmodel")
    partial=result.with_suffix(".partial")
    try:
        with ZipFile(partial,"x") as z:
            meta={"format":1,"title":config["parameters"]["name"],"embedder":p["embedder"],
                  "params":dict(p,samples=config["samples"],experiment=experiment)}
            z.writestr("model.json", json.dumps(meta,ensure_ascii=False))
            z.write(weights,"voice.pth")
            if idx:
                z.write(idx,"voice.index")
        partial.replace(result)
    finally:
        partial.unlink(missing_ok=True)
    print("可导入工作台的模型：",result)

if __name__=="__main__":
    run()
