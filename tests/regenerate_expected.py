import json
import os

from support import ROOT, read_demo, engine


def foto_demo():
    cfg = read_demo()
    output = {}
    for p in cfg["productos"]:
        movs = [m for m in cfg["movimientos"] if m["producto"] == p["id"]]
        if not movs:
            continue
        r = engine.apply_movements(dict(p, corto=p.get("corto") or p["id"]), movs)
        output[p["id"]] = {
            "movimientos": len(movs),
            "unidades": round(sum(e[1] for e in r["eventos"]), 6),
            "aportado": round(sum(e[2] for e in r["eventos"]), 2),
            "realizado": round(r["realizado"], 2),
            "comisiones": round(r["comisiones"], 2),
        }
    return output


if __name__ == "__main__":
    path = os.path.join(ROOT, "tests", "fixtures", "expected-demo.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(foto_demo(), f, ensure_ascii=False, indent=1)
    print("Guardado", path)
