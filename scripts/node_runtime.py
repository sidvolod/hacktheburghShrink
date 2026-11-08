"""Install the pinned Node runtime locally; archives and binaries stay in data/."""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen

VERSION = "v26.13.0"


def download(url: str, path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    request = Request(url, headers={"User-Agent":"shrinkflationTrack-local-runtime/1.0"})
    with urlopen(request, timeout=120) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    partial.replace(path)


def ensure_node(root: Path) -> Path:
    system = {"Darwin":"darwin", "Linux":"linux"}.get(platform.system())
    architecture = {"arm64":"arm64", "aarch64":"arm64", "x86_64":"x64", "AMD64":"x64"}.get(platform.machine())
    if not system or not architecture:
        raise RuntimeError("Use Node 22.12+ on this platform; the local bootstrap supports macOS/Linux arm64/x64.")
    filename = f"node-{VERSION}-{system}-{architecture}"
    cache = root / "data/.cache/node"
    binary = cache / filename / "bin/node"
    if binary.exists():
        subprocess.run([str(binary),"--version"],check=True,stdout=subprocess.DEVNULL)
        return binary.parent
    print(f"Preparing project-local Node {VERSION}…",file=sys.stderr)
    archive = cache / (filename + ".tar.gz")
    sums = cache / (VERSION + "-SHASUMS256.txt")
    base = f"https://nodejs.org/dist/{VERSION}"
    download(f"{base}/SHASUMS256.txt",sums)
    download(f"{base}/{archive.name}",archive)
    expected = next(line.split()[0] for line in sums.read_text().splitlines() if line.split()[-1] == archive.name)
    with archive.open("rb") as handle:
        actual = hashlib.file_digest(handle,"sha256").hexdigest()
    if actual != expected:
        archive.unlink()
        raise ValueError("Node archive checksum mismatch; rerun to download it again")
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not (cache / member.name).resolve().is_relative_to(cache.resolve()):
                raise ValueError("Unexpected runtime archive path")
        tar.extractall(cache,filter="data")
    return binary.parent


if __name__ == "__main__":
    print(ensure_node(Path(__file__).resolve().parents[1]))
