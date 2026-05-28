import platform
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .utils import platform_config_dir, download_and_check


@dataclass
class ManifestEntry:
    os: Literal["linux", "darwin", "win32"]
    arch: Literal["aarch64", "x86_64"]
    url: str
    sha256: str

HELPER_VERSION = "0.1.0"


MANIFEST: list[ManifestEntry] = [
    ManifestEntry(
        os="darwin",
        arch="aarch64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.1.0/guava-webrtc-darwin-aarch64",
        sha256="c134efc45820ba50b461fc29918a49a0c4b9d5bf04367be86700a78309211dc5",
    ),
    ManifestEntry(
        os="darwin",
        arch="x86_64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.1.0/guava-webrtc-darwin-x86_64",
        sha256="bbe49b90184a863fcb8215ac4e6f09b827d4efa36ea2ffa958b11cc81422d45a",
    ),
    ManifestEntry(
        os="linux",
        arch="aarch64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.1.0/guava-webrtc-linux-aarch64",
        sha256="4b0f7cf4161e1b18130cfabe2754866eadd787e865bf2e51843688841ae1acf7",
    ),
    ManifestEntry(
        os="linux",
        arch="x86_64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.1.0/guava-webrtc-linux-x86_64",
        sha256="ea2c8a479eacccf6188853bb41f1797c8e4506205ad1a293f392e08d1d11bb86",
    ),
    ManifestEntry(
        os="win32",
        arch="x86_64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.1.0/guava-webrtc-windows-x86_64.exe",
        sha256="4957fa123527a16bf4242569dc7c3d3ca2cd2f6583b07d38d76ae467485fb032",
    ),
]


def detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    elif machine in ("x86_64", "amd64"):
        return "x86_64"
    else:
        raise RuntimeError(f"Unsupported architecture for WebRTC helper: {machine}")


def get_or_download_binary() -> Path:
    arch = detect_arch()

    entry = next((e for e in MANIFEST if e.os == sys.platform and e.arch == arch), None)
    if entry is None:
        raise RuntimeError(f"No WebRTC helper binary available for {sys.platform}/{arch}")

    exe_suffix = ".exe" if sys.platform == "win32" else ""
    binary_path = platform_config_dir() / "guava" / "webrtc" / f"guava-webrtc-{HELPER_VERSION}{exe_suffix}"

    if not binary_path.exists():
        download_and_check(entry.url, binary_path, entry.sha256)
        if sys.platform != "win32":
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return binary_path


def run_webrtc_helper(webrtc_code: str, base_url: str) -> None:
    binary_path = get_or_download_binary()
    subprocess.run([str(binary_path), webrtc_code, "--base-url", base_url], check=True)
