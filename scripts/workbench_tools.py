"""Install only pinned official tool archives, preserving existing valid binaries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("workbench-tools.json")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def install(check_only=False):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tools = PROJECT / "workers" / "browser-capture" / "tools"
    cache = PROJECT / "data" / "workbench" / "setup-cache"
    for name, item in manifest.items():
        directory = tools / name
        missing = []
        for filename, hashes in item["files"].items():
            destination = directory / filename
            if not destination.is_file():
                missing.append(filename)
            elif digest(destination) not in hashes:
                raise RuntimeError(f"Unrecognized {destination}; existing files are never overwritten. "
                                   "Back up the file and review scripts/workbench-tools.json before replacement.")
        if not missing:
            print(f"{name}: SHA256 OK (existing version preserved)")
            continue
        if check_only:
            raise RuntimeError(f"Missing {name}: {', '.join(missing)}. Run install-workbench-tools.ps1.")
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / f"{name}-{item['sha256'][:12]}.zip"
        if not archive.is_file() or digest(archive) != item["sha256"]:
            temporary = archive.with_suffix(".part")
            print(f"Downloading pinned {item['release']}", flush=True)
            request = urllib.request.Request(item["url"], headers={"User-Agent": "MediaCrawler-local-setup"})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target)
            if digest(temporary) != item["sha256"]:
                raise RuntimeError(f"Archive SHA256 mismatch: {temporary}")
            temporary.replace(archive)
        # Only extract exact executable names. Never unpack arbitrary archive paths.
        with zipfile.ZipFile(archive) as bundle:
            directory.mkdir(parents=True, exist_ok=True)
            for filename in missing:
                candidates = [entry for entry in bundle.infolist() if Path(entry.filename).name == filename]
                if len(candidates) != 1:
                    raise RuntimeError(f"Expected exactly one {filename} in {archive}")
                temporary = directory / f"{filename}.part"
                with bundle.open(candidates[0]) as source, temporary.open("wb") as target:
                    shutil.copyfileobj(source, target)
                if digest(temporary) not in item["files"][filename]:
                    raise RuntimeError(f"Executable SHA256 mismatch: {temporary}")
                destination = directory / filename
                if destination.exists():
                    raise RuntimeError(f"File appeared during installation; refusing overwrite: {destination}")
                temporary.rename(destination)
        print(f"{name}: installed and SHA256 verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without downloading or changing files")
    install(parser.parse_args().check)
