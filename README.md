# Guava Python SDK
[![PyPI - Version](https://img.shields.io/pypi/v/guava-sdk)](https://pypi.org/project/guava-sdk/)


## Documentation

Full documentation for the Python SDK can be found at [https://docs.goguava.ai/](https://docs.goguava.ai/). Examples can be found under [./guava/examples/](/guava/examples/).


## Installation

Install the SDK using your preferred package manager.

```bash
$ pip install guava-sdk
$ uv add guava-sdk
$ poetry add guava-sdk
```

## Running an Example

Set your environment variables.

```bash
$ export GUAVA_API_KEY="..."
$ export GUAVA_AGENT_NUMBER="..."
```

Examples can be run using the `guava.examples` submodule.

```bash
$ python -m guava.examples.scheduling_outbound +1... "John Doe" # Use your own phone number and name to receive a call.
```