"""Run acquisition and deterministic preparation from the repository root."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

STAGES = ("open-prices", "evidence", "retail", "catalogue", "commodities", "monthly", "linking", "features", "snack-cases", "evaluation", "app-export", "inventory")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["prepare", "personal-inflation"])
    parser.add_argument("csv_path",nargs="?",type=Path,help="Bank statement CSV for personal-inflation")
    parser.add_argument("--indices",type=Path,help="Optional local price-index bundle; never downloads data")
    parser.add_argument("--json",action="store_true",help="Return structured personal-inflation results")
    parser.add_argument("--offline",action="store_true",help="Use only downloaded raw files; no network calls")
    parser.add_argument("--stages",nargs="+",choices=STAGES,default=STAGES)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "AGENTS.md").exists():
        parser.error("Root must be the shrinkflationTrack project directory")
    if args.command == "personal-inflation":
        from .personal_inflation import PersonalInflationError, personal_inflation
        if args.csv_path is None:
            parser.error("personal-inflation requires a CSV path")
        try:
            result = personal_inflation(args.csv_path,args.indices,root=root)
        except PersonalInflationError as error:
            parser.exit(2,f"Error: {error}\n")
        if args.json:
            print(json.dumps(result,indent=2,ensure_ascii=False))
        else:
            print(result["summary"])
            for warning in result["warnings"]:
                print(f"Warning: {warning}")
        return
    if args.csv_path is not None:
        parser.error("prepare does not take a CSV path")
    for stage in args.stages:
        print(f"Preparing {stage} ...",flush=True)
        module = importlib.import_module("shrinkflation." + stage.replace("-","_"))
        result = module.run(root,fetch=not args.offline)
        print(json.dumps({"stage":stage,"result":result},default=str),flush=True)


if __name__ == "__main__":
    main()
