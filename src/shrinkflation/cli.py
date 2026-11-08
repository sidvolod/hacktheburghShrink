"""Run acquisition and deterministic preparation from the repository root."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

STAGES = ("open-prices", "evidence", "retail", "catalogue", "commodities", "monthly", "linking", "features", "snack-cases", "evaluation", "app-export", "inventory")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["prepare"])
    parser.add_argument("--offline",action="store_true",help="Use only downloaded raw files; no network calls")
    parser.add_argument("--stages",nargs="+",choices=STAGES,default=STAGES)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "AGENTS.md").exists():
        parser.error("Root must be the shrinkflationTrack project directory")
    for stage in args.stages:
        print(f"Preparing {stage} ...",flush=True)
        module = importlib.import_module("shrinkflation." + stage.replace("-","_"))
        result = module.run(root,fetch=not args.offline)
        print(json.dumps({"stage":stage,"result":result},default=str),flush=True)


if __name__ == "__main__":
    main()
