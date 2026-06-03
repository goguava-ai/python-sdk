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

HELPER_VERSION = "0.2.0"


MANIFEST: list[ManifestEntry] = [
    ManifestEntry(
        os="darwin",
        arch="aarch64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.2.0/guava-webrtc-darwin-aarch64",
        sha256="4f42f9d75fe1b78b9e4f794a475d6d01d6f18c0865d65b4ad14368d28a7e0b95",
    ),
    ManifestEntry(
        os="darwin",
        arch="x86_64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.2.0/guava-webrtc-darwin-x86_64",
        sha256="0532f8a895142d9e4331f4a5552aae15d82fa7652725fdce08c46ba643c147df",
    ),
    ManifestEntry(
        os="linux",
        arch="aarch64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.2.0/guava-webrtc-linux-aarch64",
        sha256="0abaeb725a9c809474adbbe88ee0dc5e6866ebdec724fa87fb44be4433a2f386",
    ),
    ManifestEntry(
        os="linux",
        arch="x86_64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.2.0/guava-webrtc-linux-x86_64",
        sha256="08dc989beb09058185f93e7f5dd4d92a4fb54419f7ba88be17dbaa6e5649ba4b",
    ),
    ManifestEntry(
        os="win32",
        arch="x86_64",
        url="https://storage.googleapis.com/gridspace-guava-cli/webrtc/0.2.0/guava-webrtc-windows-x86_64.exe",
        sha256="3bef8753605a2b84f2c33f4b9760dc084e1cc12f55b886a2a2983e061f4c30bb",
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
