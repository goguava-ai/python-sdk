import os
import openai
from urllib.parse import urljoin
from guava.utils import get_base_url


def create_openai_client():
    return openai.OpenAI(
        api_key=os.environ["GUAVA_API_KEY"], base_url=urljoin(get_base_url(), "openai/v1")
    )
