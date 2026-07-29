# Guava Python SDK
[![PyPI - Version](https://img.shields.io/pypi/v/guava-sdk)](https://pypi.org/project/guava-sdk/)


## Documentation

Full documentation for the Python SDK can be found at [https://goguava.ai/docs](https://goguava.ai/docs). SDK examples can be found under [./examples/](https://github.com/goguava-ai/python-sdk/tree/main/examples).


## Installation

Install the SDK using your preferred package manager. We recommend using [`uv`](https://docs.astral.sh/uv/).

```bash
$ uv add guava-sdk
$ pip install guava-sdk
$ poetry add guava-sdk
```

We also recommend using a typechecker, [`ty`](https://docs.astral.sh/ty/) in particular, though [`mypy`](https://mypy-lang.org/) and others are also supported.

## Authentication

Log in using the [Guava CLI](https://goguava.ai/docs/quickstart):

```shell
guava login
```

Alternatively, provide an API key through an environment variable.

```shell
$ export GUAVA_API_KEY="..." # Your API key for authentication.
```

## Running an Example

Examples can be run directly using the `guava.examples` submodule.

```bash
$ python -m guava.examples.scheduling_outbound +1... "John Doe" # Use your own phone number and name to receive a call.
```