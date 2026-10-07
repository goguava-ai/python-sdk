# Benchmark bots

This module measures how well a Guava agent understands callers through background noise. It calls a bot many times with the same recording of a caller, mixing in car noise at a different loudness each time, then scores how many of the caller's ten details the bot wrote down correctly.

Signal-to-noise ratio (SNR) is the gap between the caller's volume and the noise, in decibels. Higher is cleaner. At 0 dB the two are equally loud.

## Quickstart

Start the bot in one terminal. It answers on `GUAVA_AGENT_NUMBER`, or on the first number in your account:

```bash
cd guava/python-sdk/guava/benchmark-bots
uv run --no-dev python info_extraction.py
```

Then run the sweep in a second terminal. Pass it the number the bot answers on:

```bash
cd guava/python-sdk/guava/benchmark-bots

# Start with one clean call, to check the setup works
uv run --no-dev python snr_sweep.py --number +1XXXXXXXXXX --levels clean --trials 1

# Full sweep: 8 noise levels, 3 calls each, 8 calls at a time
uv run --no-dev python snr_sweep.py --number +1XXXXXXXXXX
```

A full sweep places 24 calls and takes a few minutes. Useful flags:
`--concurrency N` (default 8; 0 places every call at once), `--levels`, `--trials`, `--bot-dir`, and `--out-dir`. Run with `--help` for the rest.

**Raise `--concurrency` carefully.** Many calls at once slow the bot down. The recording plays on a fixed schedule and cannot wait for it, so the bot's answers drift onto the wrong questions and scores fall for reasons that have nothing to do with noise. If a clean call scores 10/10 on its own but much lower inside a sweep, you are measuring load, not noise. Drop to `--concurrency 8`.

## What you get

The test prints two tables when it finishes.

The first table gives accuracy at each noise level, averaged over three calls:

```
   SNR       mean   accuracy   stdev
 clean   9.67/10      96.7%    0.58
    20   9.00/10      90.0%    1.00
    15   9.33/10      93.3%    0.58
    10   9.67/10      96.7%    0.58
     5   7.67/10      76.7%    2.31
     0   3.67/10      36.7%    1.53
    -5   0.00/10       0.0%    0.00
   -10   0.00/10       0.0%    0.00
```

The second table shows which details the bot loses first:

```
               field   clean      20      15      10       5       0      -5     -10
          first_name    100%    100%    100%    100%    100%    100%      0%      0%
           last_name    100%    100%    100%    100%     67%      0%      0%      0%
                 dob    100%    100%    100%    100%    100%      0%      0%      0%
               state    100%    100%    100%    100%    100%     67%      0%      0%
            zip_code    100%    100%    100%    100%    100%     67%      0%      0%
               email    100%    100%    100%    100%     67%      0%      0%      0%
      household_size    100%     33%    100%    100%      0%      0%      0%      0%
        phone_number    100%    100%    100%     67%    100%     67%      0%      0%
  credit_card_number     67%     67%     33%    100%     67%      0%      0%      0%
     expiration_date    100%    100%    100%    100%     67%     67%      0%      0%
```

The test saves both tables as CSV files (`summary.csv` and `fields.csv`, respectively), alongside a recording of the bot's half of every call. It also draws the first table as a graph, `snr_curve.png`, with error bars covering one standard deviation across the three calls at each level.

The graph needs matplotlib, which is not a dependency of the SDK. Without it the sweep still writes every CSV and just skips the picture. To get it:

```bash
uv run --with matplotlib python snr_sweep.py --number +1XXXXXXXXXX
```

## How it works

```
snr_sweep.py ──dials──> make_calls.py ──SIP──> bot (info_extraction.py)
     ^                  (one per call)                    |
     |                                                    | writes 2 files
     └────── collects them into results/ ─────────────────┘
```

Every call dials from its own caller number, counting up from `+15550000001`.
The bot names its output file after those digits, so calls running at the same
time never overwrite each other's answers. The sweep waits for the file to
appear, moves it into the run's results folder, and scores it there.

Before comparing an answer to the answer key, the sweep tidies both sides so
that cosmetic differences don't count as mistakes. Digit fields keep only the
characters `0` through `9`, so `(808) 427-6139` matches `8084276139`. Dates
become `YYYY-MM-DD`. Everything else loses its capitals, spaces, and
punctuation. A blank answer never counts as correct.

### Files

Each run creates `results/snr_sweep_<timestamp>/` holding:

| File | Contents |
|---|---|
| `summary.csv` | Average accuracy and standard deviation per noise level |
| `fields.csv` | Success rate per field per noise level, as fractions |
| `snr_curve.png` | The accuracy curve, if matplotlib is installed |
| `results.csv` | One row per call: score, which fields it got, caller number |
| `transcript.txt` | Every call's dialogue, each headed by call id, SNR and trial |
| `extracted_snr<level>_t<trial>.csv` | What the bot heard on that call |
| `bot_snr<level>_t<trial>.wav` | Recording of the bot's half of that call |

### Temporary files

The bot is a separate, long-running process. It knows the caller's number and
the call id, but not which sweep it is serving, which SNR level the call used,
or where the results folder is. So it drops two files per call in its own
directory, named after the caller's digits, and lets the sweep process collect them:

| File | Becomes |
|---|---|
| `info_extraction_<caller digits>.csv` | `extracted_snr<level>_t<trial>.csv` |
| `transcript_<caller digits>.txt` | One section of `transcript.txt` |

The bot writes the transcript first, so the CSV's arrival tells the sweep both
files are ready. The sweep waits for the CSV, moves it, then reads the
transcript and adds a heading naming the SNR level and trial — which only the
sweep knows — alongside the call id, which only the bot knows.

Both files are deleted either way, including any that arrive too late to be
scored, so nothing piles up beside the bot.

### Inputs

`answer_key.csv` holds the correct answers for the recorded caller. The noisy
recordings in `benchmark_noise/` are named `snr<level>.wav`. We made them from
`signal.wav` and `car_noise.wav` with `tests/e2e/mix_noise.py`:

```bash
uv run python mix_noise.py --signal signal.wav --noise car_noise.wav \
    --snr-db 10 --out snr10.wav
```
