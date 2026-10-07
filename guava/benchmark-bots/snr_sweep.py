"""SNR sweep benchmark for the information-extraction bot.

Places repeated SIP calls to an info_extraction bot already listening on a
staging number, streaming the same caller utterance mixed with car noise at a
range of signal-to-noise ratios, and scores how many of the ten fields the bot
extracted correctly at each level.

Because the bot is ML-driven and therefore stochastic, each SNR level is called
several times (--trials) and the scores are averaged.

All calls run with concurrency=8 by default, each dialing from its own caller number so
the bot can tell their answers apart. Use --concurrency to change the number of calls that are placed at once.
Each sweep writes to its own timestamped folder under results/; the bot's
per-caller CSV is moved there and scored, so nothing piles up beside the bot.

Assumes:
  - The bot is already running and listening on the number you pass.
  - It writes info_extraction_<caller digits>.csv into this directory
    (override with --bot-dir).
  - The noisy WAVs from tests/e2e/mix_noise.py are named snr<level>.wav
    (snrclean.wav, snr10.wav, snr-5.wav, ...) in --audio-dir.

Usage:
    cd guava/python-sdk/guava/benchmark-bots

    # Single clean call, to check the harness and the recording's pacing
    uv run --no-dev python snr_sweep.py --number +1XXXXXXXXXX --levels clean --trials 1

    # Full sweep: 8 levels x 3 calls
    uv run --no-dev python snr_sweep.py --number +1XXXXXXXXXX
"""

import argparse
import csv
import logging
import re
import shutil
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("snr_sweep")

REPO_ROOT = Path(__file__).resolve().parents[3]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
BOT_DIR = Path(__file__).resolve().parent

STAGING_SIP_HOST = "guava-staging-sip.gridspace.com"
DEFAULT_LEVELS = ["clean", "20", "15", "10", "5", "0", "-5", "-10"]
DEFAULT_AUDIO_DIR = Path(__file__).resolve().parent / "benchmark_noise"

# Mirrors info_extraction.DIGIT_FIELDS; duplicated so the harness doesn't have to
# import the bot module (which constructs an Agent at import time).
DIGIT_FIELDS = {
    "zip_code",
    "phone_number",
    "credit_card_number",
    "household_size",
    "expiration_date",
}

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y",
    "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
]

# Caller numbers count up from here, one per call, so the bot keeps concurrent
# calls apart. The bot names its results file after the caller's digits.
CALLER_NUMBER_BASE = 15550000000

# The bot writes one of these per caller (in its working directory) on session
# end. The sweep moves each one into its results folder.
RESULT_CSV = "info_extraction_{digits}.csv"
TRANSCRIPT_TXT = "transcript_{digits}.txt"


def read_key_value_csv(path: Path) -> dict[str, str]:
    """Read a two-column field,value CSV into a dict."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return {row["field"]: (row["value"] or "") for row in reader}


def normalize_date(value: str) -> str:
    """Normalize a date to ISO format, falling back to its digits."""
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()  # noqa: DTZ007
        except ValueError:
            continue
    return re.sub(r"\D", "", value)


def normalize(field: str, value: str) -> str:
    """Canonicalize a field value so cosmetic differences don't count as errors.

    Args:
        field: The field key (determines the normalization rule).
        value: The raw value from the bot or the answer key.

    Returns:
        A normalized string suitable for equality comparison.
    """
    value = (value or "").strip()
    if field in DIGIT_FIELDS:
        return re.sub(r"\D", "", value)
    if field == "dob":
        return normalize_date(value)
    if field == "email":
        return re.sub(r"\s+", "", value).casefold()
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def score_call(answer_key: dict[str, str], extracted: dict[str, str]) -> dict[str, bool]:
    """Compare extracted values against the answer key, field by field.

    Args:
        answer_key: Ground-truth field/value pairs.
        extracted: Field/value pairs the bot produced.

    Returns:
        Mapping of field key to whether it was extracted correctly. A blank
        value never counts as correct.
    """
    results = {}
    for field, truth in answer_key.items():
        got = extracted.get(field, "")
        results[field] = bool(got.strip()) and normalize(field, got) == normalize(field, truth)
    return results


def place_call(number: str, from_number: str, audio: Path, record: Path,
               sip_host: str, timeout_s: float, label: str) -> bool:
    """Stream a WAV to the bot over SIP via tests/e2e/make_calls.py.

    Args:
        number: E.164 number the bot is listening on.
        from_number: E.164 caller number, unique among calls running at once.
        audio: WAV file to stream as the caller.
        record: Where to save the bot's audio.
        sip_host: SIP host to dial.
        timeout_s: Kill the dialer after this long.
        label: Call name, so parallel log lines say which call they describe.

    Returns:
        True if the dialer exited cleanly.
    """
    cmd = [
        "uv", "run", "python", "make_calls.py",
        "--number", number,
        "--from-number", from_number,
        "--audio", str(audio),
        "--record", str(record),
        "--sip-host", sip_host,
    ]
    try:
        result = subprocess.run(
            cmd, cwd=E2E_DIR, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        logger.error("%s: dialer timed out after %.0fs", label, timeout_s)
        return False
    if result.returncode != 0:
        logger.error("%s: dialer failed (exit %d):\n%s", label, result.returncode,
                     result.stdout + result.stderr)
        return False
    return True


def wait_for_result(result_path: Path, since: float, timeout_s: float = 60.0) -> bool:
    """Wait for the bot to write its results CSV after the call ends.

    Args:
        result_path: Path to the bot's results CSV for this call.
        since: Only a file modified at or after this timestamp counts.
        timeout_s: How long to wait before giving up.

    Returns:
        True if a fresh results file appeared.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if result_path.exists() and result_path.stat().st_mtime >= since:
            time.sleep(0.5)  # let the write finish
            return True
        time.sleep(0.5)
    return False


def run_job(job: tuple[int, str, int], args, answer_key: dict[str, str],
            out_dir: Path, audio_paths: dict[str, Path]) -> tuple[dict, str]:
    """Place one call, wait for the bot's answers, and score them.

    Safe to run from several threads at once: the caller number gives the call
    its own results file, and the paths written carry its level and trial.

    Args:
        job: (1-based call number in the sweep, SNR level, trial number).
        args: Parsed command-line arguments.
        answer_key: Ground-truth field/value pairs.
        out_dir: Where to save this call's recording and answers.
        audio_paths: Caller WAV to stream, keyed by SNR level.

    Returns:
        A results row for this call, and its labelled transcript section.
        Failed calls score zero.
    """
    index, level, trial = job
    label = f"snr{level} trial {trial}/{args.trials}"
    digits = CALLER_NUMBER_BASE + index
    result_path = args.bot_dir / RESULT_CSV.format(digits=digits)
    fields = list(answer_key)
    logger.info("--- %s, dialing as +%d ---", label, digits)

    started = time.time()
    ok = place_call(args.number, f"+{digits}", audio_paths[level],
                    out_dir / f"bot_snr{level}_t{trial}.wav",
                    args.sip_host, args.call_timeout, label)

    extracted: dict[str, str] = {}
    transcript = ""
    if ok and wait_for_result(result_path, since=started):
        # Move, don't copy, so the bot's directory keeps nothing. Score the moved
        # file, so the numbers always match the artifact saved beside them.
        extracted_path = out_dir / f"extracted_snr{level}_t{trial}.csv"
        shutil.move(result_path, extracted_path)
        extracted = read_key_value_csv(extracted_path)
        # The bot wrote this before the CSV, so by now it is complete. It knows
        # the call id but not the SNR level or trial, so it puts the id on the
        # first line and leaves us to write the heading.
        t_path = args.bot_dir / TRANSCRIPT_TXT.format(digits=digits)
        lines = t_path.read_text().splitlines(keepends=True) if t_path.exists() else []
        if lines:
            transcript = (f"===== Call {lines[0].removeprefix('call_id ').strip()} "
                          f"({label}, caller +{digits}) =====\n" + "".join(lines[1:]) + "\n")
    elif ok:
        logger.error("%s: bot wrote no results; scoring 0", label)
    else:
        logger.error("%s: call failed; scoring 0", label)

    per_field = score_call(answer_key, extracted)
    correct = sum(per_field.values())
    missed = ", ".join(f for f, hit in per_field.items() if not hit)
    logger.info("%s: %d/%d correct (%s)", label, correct, len(fields),
                f"missed: {missed}" if missed else "all correct")

    return {
        "snr": level, "trial": trial, "correct": correct, "total": len(fields),
        "call_ok": ok, "from_number": f"+{digits}",
        **{f"f_{f}": int(per_field[f]) for f in fields},
    }, transcript


def plot_curve(stats: list[tuple[str, float, float]], path: Path) -> None:
    """Plot accuracy against noise level and save it as a PNG.

    The numeric levels form the curve, with error bars covering one standard
    deviation across trials. "clean" has no noise to plot against, so it
    becomes a dashed reference line showing the best the bot managed.

    Warns and returns if matplotlib is missing, so a sweep still finishes and
    keeps its CSVs.

    Args:
        stats: (level, mean accuracy, stdev) per level, accuracy as a fraction.
        path: PNG file to write.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # write a file; benchmark hosts have no display
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("No matplotlib, so no %s. Rerun with "
                       "'uv run --with matplotlib' to get the plot.", path.name)
        return

    noisy = sorted((float(lvl), acc, sd) for lvl, acc, sd in stats
                   if lvl.lstrip("-").isdigit())
    clean = next((acc for lvl, acc, _ in stats if lvl == "clean"), None)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    if clean is not None:
        ax.axhline(clean * 100, ls="--", lw=1.5, color="gray", zorder=1,
                   label=f"no noise ({clean:.0%})")
    if noisy:
        ax.errorbar([p[0] for p in noisy], [p[1] * 100 for p in noisy],
                    yerr=[p[2] * 100 for p in noisy], lw=2, marker="o", ms=8,
                    capsize=4, zorder=2, label="with car noise")
        ax.set_xticks([p[0] for p in noisy])
    ax.invert_xaxis()  # read left to right as conditions get worse

    ax.set_xlabel("Signal-to-noise ratio (dB), noisier to the right")
    ax.set_ylabel("Fields correct (%)")
    ax.set_title("Extraction accuracy vs. background noise", pad=12)
    ax.set_ylim(-5, 105)
    ax.grid(lw=0.8, alpha=0.4)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Wrote %s", path)


def main():
    parser = argparse.ArgumentParser(
        description="Run an SNR sweep against an info-extraction bot running on staging."
    )
    parser.add_argument("--number", required=True, metavar="E164",
                        help="Staging number the bot is listening on")
    parser.add_argument("--levels", nargs="*", default=DEFAULT_LEVELS,
                        help=f"SNR suffixes to sweep (default: {' '.join(DEFAULT_LEVELS)})")
    parser.add_argument("--trials", type=int, default=3,
                        help="Calls per SNR level, averaged (default: 3)")
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR,
                        help=f"Directory of snr<level>.wav files (default: {DEFAULT_AUDIO_DIR})")
    parser.add_argument("--answer-key", type=Path, default=BOT_DIR / "answer_key.csv")
    parser.add_argument("--bot-dir", type=Path, default=BOT_DIR,
                        help="Working directory of the running bot, where it writes "
                             "its results CSVs (default: this directory)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Where to write results and per-call artifacts "
                             "(default: ./results/snr_sweep_<timestamp>)")
    parser.add_argument("--sip-host", default=STAGING_SIP_HOST,
                        help=f"SIP host to dial (default: {STAGING_SIP_HOST})")
    parser.add_argument("--call-timeout", type=float, default=300.0,
                        help="Per-call dialer timeout in seconds (default: 300)")
    parser.add_argument("--concurrency", type=int, default=8, metavar="N",
                        help="Calls to run at once (default: 8). Setting this to 0 will run all calls at the same time.")
    parser.add_argument("--stagger-seconds", type=float, default=1.0,
                        help="Gap between call starts (default: 1)")
    args = parser.parse_args()

    out_dir = args.out_dir or (
        Path.cwd() / "results" / f"snr_sweep_{datetime.now().astimezone():%Y%m%d_%H%M%S}")
    out_dir.mkdir(parents=True, exist_ok=True)

    answer_key = read_key_value_csv(args.answer_key)
    fields = list(answer_key)

    # Fail fast on missing audio rather than part-way through the sweep.
    audio_paths = {}
    for level in args.levels:
        path = args.audio_dir / f"snr{level}.wav"
        if not path.is_file():
            raise SystemExit(f"Missing audio for level {level!r}: {path}")
        audio_paths[level] = path

    # The call number gives each call a caller number the bot can tell apart.
    pairs = [(lvl, t) for lvl in args.levels for t in range(1, args.trials + 1)]
    jobs = [(index, lvl, t) for index, (lvl, t) in enumerate(pairs, 1)]
    workers = args.concurrency or len(jobs)
    logger.info("Dialing %s at %s: %d level(s) x %d trial(s) = %d calls, %d at a "
                "time, scoring %d fields", args.number, args.sip_host,
                len(args.levels), args.trials, len(jobs), workers, len(fields))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for job in jobs:
            futures.append(pool.submit(run_job, job, args, answer_key, out_dir,
                                       audio_paths))
            time.sleep(args.stagger_seconds)  # don't dial them all in one instant
        rows, talk = zip(*[f.result() for f in futures])  # job order, so tables sort

    (out_dir / "transcript.txt").write_text("".join(talk))  # calls in table order

    # A call that answered too late leaves its handoff files behind; drop those.
    for index, _level, _trial in jobs:
        for name in (RESULT_CSV, TRANSCRIPT_TXT):
            (args.bot_dir / name.format(digits=CALLER_NUMBER_BASE + index)).unlink(missing_ok=True)

    # Per-call detail.
    detail_path = out_dir / "results.csv"
    with open(detail_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # Per-level summary.
    summary_path = out_dir / "summary.csv"
    stats = []  # (level, mean accuracy, stdev), as fractions, for the plot
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["snr", "trials", "mean_correct", "total", "mean_accuracy", "stdev"])
        print(f"\n{'SNR':>6} {'mean':>10} {'accuracy':>10} {'stdev':>7}")
        for level in args.levels:
            scores = [r["correct"] for r in rows if r["snr"] == level]
            mean = statistics.mean(scores)
            stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
            writer.writerow([level, len(scores), f"{mean:.2f}", len(fields),
                             f"{mean / len(fields):.3f}", f"{stdev:.2f}"])
            print(f"{level:>6} {mean:>6.2f}/{len(fields):<3} {mean / len(fields):>9.1%} {stdev:>7.2f}")
            stats.append((level, mean / len(fields), stdev / len(fields)))

    # Which fields break down first. One row per field, one column per level.
    fields_path = out_dir / "fields.csv"
    with open(fields_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field", *args.levels])
        print(f"\n{'field':>20}" + "".join(f"{lvl:>8}" for lvl in args.levels))
        for field in fields:
            rates = [statistics.mean([r[f"f_{field}"] for r in rows if r["snr"] == level])
                     for level in args.levels]
            writer.writerow([field, *(f"{rate:.3f}" for rate in rates)])
            print(f"{field:>20}" + "".join(f"{rate:>8.0%}" for rate in rates))

    plot_curve(stats, out_dir / "snr_curve.png")
    logger.info("Wrote %s, %s and %s", detail_path, summary_path, fields_path)


if __name__ == "__main__":
    main()
