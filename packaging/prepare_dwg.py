#!/usr/bin/env python3
"""Stage the standalone LibreDWG converter for application bundles.

Run before installing/building the Python package. Downloads happen at build
time only. The converter communicates with Serpentine through temporary DXF
files; it is never loaded into the application's Python process.
"""

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

VERSION = "0.14"
SOURCE = f"libredwg-{VERSION}.tar.xz"
WINDOWS = f"libredwg-{VERSION}-win64.zip"
MUSL_VERSION = "1.2.5"
MUSL = f"musl-{MUSL_VERSION}.tar.gz"
HASHES = {
    SOURCE: "62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275",
    WINDOWS: "1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8",
    MUSL: "a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4",
}
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "serpentine3d" / "_vendor" / "libredwg"
CONFIGURE = ["--disable-shared", "--enable-static", "--disable-bindings",
             "--disable-docs", "--disable-write", "--disable-json"]


def download(cache, name):
    path = cache / name
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == HASHES[name]:
        return path
    url = f"https://github.com/LibreDWG/libredwg/releases/download/{VERSION}/{name}"
    if name == MUSL:
        url = f"https://musl.libc.org/releases/{name}"
    print(f"Downloading {url}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != HASHES[name]:
        raise RuntimeError(f"Checksum mismatch: {name}")
    path.write_bytes(data)
    return path


def build_musl(source, scratch, jobs):
    """Avoid binding the AppImage's helper to the build host's glibc version."""
    with tarfile.open(source) as archive:
        archive.extractall(scratch, filter="data")
    work = scratch / f"musl-{MUSL_VERSION}"
    prefix = scratch / "musl-runtime"
    subprocess.run(["sh", "./configure", "--disable-shared", f"--prefix={prefix}"],
                   cwd=work, check=True)
    subprocess.run(["make", f"-j{jobs}", "install"], cwd=work, check=True)
    return prefix / "bin" / "musl-gcc"


def main():
    system, machine = platform.system(), platform.machine().lower()
    if system not in {"Windows", "Linux", "Darwin"}:
        raise RuntimeError(f"Unsupported DWG build platform: {system}")
    if system == "Windows" and machine not in {"amd64", "x86_64"}:
        raise RuntimeError("The Windows DWG binary requires x86_64")
    cache = Path(os.environ.get("SERP3D_DWG_BUILD_CACHE",
                                Path.home() / ".cache" / "serpentine3d" / "libredwg"))
    cache = cache / VERSION
    cache.mkdir(parents=True, exist_ok=True)
    source = download(cache, SOURCE)
    musl = download(cache, MUSL) if system == "Linux" else None
    # Include the recipe in the key so changed flags cannot reuse old binaries.
    recipe = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    built = cache / f"{system}-{machine}-{recipe}"
    executable = "dwg2dxf.exe" if system == "Windows" else "dwg2dxf"
    if not (built / executable).is_file():
        with tempfile.TemporaryDirectory(dir=cache, prefix="build-") as scratch:
            scratch = Path(scratch)
            stage = scratch / "stage"
            stage.mkdir()
            if system == "Windows":
                with zipfile.ZipFile(download(cache, WINDOWS)) as archive:
                    # These import only Windows system DLLs. Do not ship the
                    # unrelated iconv/PCRE binaries from the upstream archive.
                    for name in (executable, "libredwg-0.dll"):
                        (stage / name).write_bytes(archive.read(name))
            else:
                with tarfile.open(source) as archive:
                    archive.extractall(scratch, filter="data")
                work = scratch / f"libredwg-{VERSION}"
                env = os.environ.copy()
                env.setdefault("CFLAGS", "-O1")
                jobs = str(min(os.cpu_count() or 2, 4))
                if musl is not None:
                    env["CC"] = str(build_musl(musl, scratch, jobs))
                    env["LDFLAGS"] = "-static"
                subprocess.run(["sh", "./configure", *CONFIGURE], cwd=work,
                               env=env, check=True)
                subprocess.run(["make", f"-j{jobs}", "-C", "src", "libredwg.la"],
                               cwd=work, env=env, check=True)
                # libtool's -static means only "prefer static libtool libs";
                # -all-static also links libc and removes the ELF interpreter.
                link_flags = ["LDFLAGS=-all-static"] if musl is not None else []
                subprocess.run(["make", f"-j{jobs}", "-C", "programs", "dwg2dxf", *link_flags],
                               cwd=work, env=env, check=True)
                shutil.copy2(work / "programs" / executable, stage / executable)
            subprocess.run([str(stage / executable), "--version"], check=True)
            if built.exists():
                shutil.rmtree(built)
            shutil.copytree(stage, built)
    # Replace only generated files in this dedicated, ignored directory.
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(built, DEST)
    with tarfile.open(source) as archive:
        for name in ("COPYING", "README"):
            (DEST / name).write_bytes(archive.extractfile(f"libredwg-{VERSION}/{name}").read())
    # Ship corresponding source alongside the standalone GPL program, including
    # upstream build scripts and this exact recipe. No external source offer.
    shutil.copy2(source, DEST / SOURCE)
    if musl is not None:
        shutil.copy2(musl, DEST / MUSL)
        with tarfile.open(musl) as archive:
            (DEST / "COPYRIGHT-musl").write_bytes(
                archive.extractfile(f"musl-{MUSL_VERSION}/COPYRIGHT").read())
    shutil.copy2(__file__, DEST / "prepare_dwg.py")
    (DEST / "build.json").write_text(json.dumps({
        "version": VERSION, "platform": system, "machine": machine,
        "source_sha256": HASHES[SOURCE], "configure": CONFIGURE,
        "recipe": recipe,
    }, indent=2) + "\n")
    print(f"DWG converter staged: {DEST}", flush=True)


if __name__ == "__main__":
    main()
