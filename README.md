# Guava Python SDK

## Documentation

Full documentation for the Python SDK can be found at [https://docs.goguava.ai/](https://docs.goguava.ai/).


## Installation

Install the Python SDK using your preferred package manager.

*Method 1: pip*
```bash
$ pip install gridspace-guava --extra-index-url https://guava-pypi.gridspace.com
```

*Method 2: uv astral*
```bash
$ uv add gridspace-guava --index guava=https://guava-pypi.gridspace.com
```

*Method 3: poetry*
```bash
$ poetry source add --priority=explicit guava https://guava-pypi.gridspace.com
$ poetry add --source guava gridspace-guava
```

## Running an Example

Set your environment variables.

```bash
$ export GUAVA_API_KEY="..."
$ export GUAVA_AGENT_NUMBER="..."
```

Examples can be found in the `guava.examples` submodule.

```bash
$ python -m guava.examples.scheduling_outbound +1... "John Doe" # Use your own phone number and name to receive a call.
```