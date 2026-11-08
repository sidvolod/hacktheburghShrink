"""Build and serve the committed demo; optionally refresh its research inputs."""
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from node_runtime import ensure_node

ROOT = Path(__file__).resolve().parents[1]


def validate_demo_snapshot(root: Path) -> Path:
    """Fail before installing runtimes when a published demo is incomplete."""
    public = (root / "data/app-public").resolve()
    demo = public / "data/demo.json"
    repair = "Restore the committed data/app-public snapshot, or run ./run.sh --refresh-data to rebuild it from research inputs."
    try:
        document = json.loads(demo.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Cannot read the demo snapshot ({demo}): {error}. {repair}") from error
    if (not isinstance(document, dict) or document.get("schema_version") != 1
        or any(not isinstance(document.get(key), list) for key in ("cases", "histories", "comparisons"))):
        raise RuntimeError(f"The demo snapshot has an unsupported structure. {repair}")
    reports = ["evaluation.json", "monthly-audit.json", "source-registry.json"]
    for key in ("category_forecast", "category_tuning", "category_policy_tuning"):
        if document.get(key) is not None:
            reports.append(key.replace("_", "-") + ".json")
    for name in reports:
        try:
            report = json.loads((public / "data" / name).read_text())
        except (OSError, ValueError) as error:
            raise RuntimeError(f"Missing or invalid demo report data/{name}. {repair}") from error
        if not isinstance(report, dict):
            raise RuntimeError(f"Invalid demo report data/{name}. {repair}")

    def check_assets(value: object) -> None:
        if isinstance(value, dict):
            asset = value.get("local_path")
            if asset is not None:
                if not isinstance(asset, str) or not asset.startswith("/"):
                    raise RuntimeError(f"Invalid local demo asset path. {repair}")
                path = (public / asset.lstrip("/")).resolve()
                if not path.is_relative_to(public) or not path.is_file():
                    raise RuntimeError(f"Missing or invalid demo asset {asset}. {repair}")
            for child in value.values():
                check_assets(child)
        elif isinstance(value, list):
            for child in value:
                check_assets(child)

    check_assets(document)
    return demo


def refresh_research_data(root: Path, env: dict[str, str]) -> None:
    """Keep large data acquisition an explicit choice, separate from demo launch."""
    required=("retail_prices.parquet","monthly_targets.parquet","commodity_weekly.parquet","catalogue_products.parquet",
        "retail_monthly.parquet","commodity_monthly_features.parquet","family_members.parquet",
        "reported_changes.parquet","retail_catalogue_candidates.parquet")
    required_reports=("retail-audit.json","catalogue-audit.json","commodity-audit.json","monthly-audit.json")
    if (any(not (root/"data/processed"/name).exists() for name in required)
        or any(not (root/"data/reports"/name).exists() for name in required_reports)):
        print("Preparing missing research inputs under data/…",flush=True)
        subprocess.run([sys.executable,"-m","shrinkflation","prepare"],env=env,check=True)
    from shrinkflation.snack_cases import run as prepare_snacks
    from shrinkflation.evaluation import run as evaluate
    from shrinkflation.app_export import run as export_app
    prepare_snacks(root,fetch=False)
    evaluate(root,fetch=False)
    print("Exporting documented cases and dated prices…",flush=True)
    print(export_app(root),flush=True)


def prepare_demo(root: Path, env: dict[str, str], *, refresh_data: bool = False) -> Path:
    if refresh_data:
        refresh_research_data(root, env)
    return validate_demo_snapshot(root)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=4173)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only",action="store_true",help="Validate the demo and build, then exit without starting a server")
    mode.add_argument("--browser-check",action="store_true",help="Build, verify desktop/phone behavior in local headless Chromium, then exit")
    parser.add_argument("--check",action="store_true",help="Run meaningful data/calculation checks before launch")
    parser.add_argument("--refresh-data",action="store_true",help="Rebuild the demo from research inputs; missing raw data can require several GB of downloads")
    args=parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    os.chdir(ROOT)
    for path in (ROOT/"data/tmp",ROOT/"data/.cache/npm"):
        path.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.update({"TMPDIR":str(ROOT/"data/tmp"),"NPM_CONFIG_CACHE":str(ROOT/"data/.cache/npm"),
        "NPM_CONFIG_AUDIT":"false","NPM_CONFIG_FUND":"false","PYTHONPATH":str(ROOT/"src"),
        "PLAYWRIGHT_BROWSERS_PATH":str(ROOT/"data/.cache/playwright")})
    try:
        prepare_demo(ROOT, env, refresh_data=args.refresh_data)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    node_bin=ensure_node(ROOT)
    env["PATH"]=str(node_bin)+os.pathsep+env.get("PATH","")
    npm=str(node_bin/"npm")
    installed=subprocess.run([npm,"ls","--depth=0"],cwd=ROOT/"web",env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    if not installed:
        subprocess.run([npm,"ci" if (ROOT/"web/package-lock.json").exists() else "install"],cwd=ROOT/"web",env=env,check=True)
    if args.check:
        subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-v"],env=env,check=True)
        subprocess.run([npm,"test"],cwd=ROOT/"web",env=env,check=True)
    subprocess.run([npm,"run","build"],cwd=ROOT/"web",env=env,check=True)
    if args.prepare_only:
        print("Build complete: data/app-dist/",flush=True)
        return
    if args.browser_check:
        subprocess.run([str(node_bin/"node"),str(ROOT/"web/node_modules/playwright/cli.js"),"install","chromium"],
            cwd=ROOT/"web",env=env,check=True)
    handler=functools.partial(SimpleHTTPRequestHandler,directory=str(ROOT/"data/app-dist"))
    try:
        server=ThreadingHTTPServer(("127.0.0.1",args.port),handler)
    except OSError as error:
        raise SystemExit(f"Cannot bind local port {args.port}: {error}. Choose another port with --port 4174.") from error
    if args.browser_check:
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        env["PLAYWRIGHT_BASE_URL"]=f"http://127.0.0.1:{args.port}"
        try:
            subprocess.run([npm,"run","test:browser"],cwd=ROOT/"web",env=env,check=True)
        finally:
            server.shutdown()
            server.server_close()
        print("Desktop/phone browser checks complete; artifacts: data/reports/browser/",flush=True)
        return
    print(f"\nshrincflationTrack → http://127.0.0.1:{args.port}\nPress Ctrl+C to stop.\n",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLocal demo stopped.",flush=True)
    finally:
        server.server_close()


if __name__=="__main__":
    main()
