import json
import platform
import stat
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal
import logging

from pydantic import BaseModel, StringConstraints

from .utils import platform_config_dir, download_and_check

OsName = Literal["linux", "darwin", "windows"]
Arch = Literal["aarch64", "x86_64"]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

logger = logging.getLogger(__name__)

class ManifestEntry(BaseModel):
    os: OsName
    arch: Arch
    url: str
    sha256: Sha256


class Manifest(BaseModel):
    version: str
    artifacts: list[ManifestEntry]


def load_manifest() -> Manifest:
    raw = (files("guava") / "webrtc-helper-manifest.json").read_text()
    return Manifest.model_validate(json.loads(raw))


def detect_arch() -> Arch:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    elif machine in ("x86_64", "amd64"):
        return "x86_64"
    else:
        raise RuntimeError(f"Unsupported architecture for WebRTC helper: {machine}")


def detect_os() -> OsName:
    if sys.platform == "linux":
        return "linux"
    elif sys.platform == "darwin":
        return "darwin"
    elif sys.platform == "win32":
        return "windows"
    else:
        raise RuntimeError(f"Unsupported platform for WebRTC helper: {sys.platform}")


def get_or_download_binary() -> Path:
    manifest = load_manifest()
    arch = detect_arch()
    os_name = detect_os()

    entry = next(
        (e for e in manifest.artifacts if e.os == os_name and e.arch == arch),
        None,
    )
    if entry is None:
        raise RuntimeError(f"No WebRTC helper binary available for {os_name}/{arch}")

    exe_suffix = ".exe" if os_name == "windows" else ""
    binary_path = (
        platform_config_dir() / "guava" / "webrtc" / f"guava-webrtc-{manifest.version}{exe_suffix}"
    )

    if not binary_path.exists():
        logger.info("Downloading WebRTC helper to %s...", binary_path)
        download_and_check(entry.url, binary_path, entry.sha256)
        if os_name != "windows":
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return binary_path


def run_webrtc_helper(
    webrtc_code: str,
    base_url: str,
    input_wav: str | None = None,
    output_wav: str | None = None,
) -> None:
    """Run the WebRTC helper to connect to a call.

    Args:
        webrtc_code: The WebRTC code to dial.
        base_url: Base URL of the Guava server.
        input_wav: Optional 16-bit PCM WAV file to inject as the microphone
            instead of the real device. Requires output_wav.
        output_wav: Optional path to write captured far-end audio to instead of
            the speaker. Requires input_wav.
    """
    if (input_wav is None) != (output_wav is None):
        raise ValueError("input_wav and output_wav must be provided together.")

    args = [str(get_or_download_binary()), webrtc_code, "--base-url", base_url]
    if input_wav is not None:
        args += ["--input-wav", input_wav]
    if output_wav is not None:
        args += ["--output-wav", output_wav]
    subprocess.run(args, check=True)
