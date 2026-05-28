"""Deprecated factory for an OpenAI client that proxies through the Guava server.

.. deprecated::
    Use `guava.helpers.llm` for the Guava-key-only path (no OpenAI SDK
    needed). For raw OpenAI integration inside Guava callbacks, see
    ``examples/integrations/openai`` in the guava-starter repo.
"""

import os
import warnings
from urllib.parse import urljoin

from guava.utils import get_base_url


def create_openai_client():
    warnings.warn(
        "guava.helpers.beta.create_openai_client() is deprecated and will be removed in a future release. "
        "Please use guava.helpers.llm instead. If you would still like to use OpenAI models, "
        "check the Guava docs for examples on how to configure your own OpenAI client.",
        DeprecationWarning,
        stacklevel=2,
    )
    import openai

    return openai.OpenAI(
        api_key=os.environ["GUAVA_API_KEY"], base_url=urljoin(get_base_url(), "openai/v1")
    )
