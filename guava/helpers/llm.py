import json
from datetime import date, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, Field, create_model

from guava.agent import SuggestedAction
from guava.telemetry import telemetry_client
from guava.utils import check_response
from guava import Client


def generate(prompt: str, *, json_schema: dict | None = None) -> str:
    """Public wrapper around the Guava LLM endpoint.

    Prefer this over the underscore-prefixed :func:`_generate` when calling
    from outside :mod:`guava.helpers.llm` — it keeps the implementation
    private to the package while giving external callers a stable entry point.

    See :func:`_generate` for parameter and return-value details.
    """
    return _generate(prompt, json_schema=json_schema)


def _generate(prompt: str, *, json_schema: dict | None = None) -> str:
    """Call the Guava server LLM endpoint and return the raw response text.

    Reads GUAVA_API_KEY (required) and GUAVA_BASE_URL (optional) from the
    environment. When json_schema is provided, the server constrains the
    model output to match it, and the returned text is a JSON document the
    caller is responsible for parsing.

    Args:
        prompt: The user prompt to send to the model.
        json_schema: Optional JSON schema dict used to constrain the model
            output to a structured response.

    Returns:
        The text field of the server response.
    """
    payload: dict = {"prompt": prompt}
    if json_schema is not None:
        payload["json_schema"] = json_schema

    client = Client()

    r = httpx.post(
        client.get_http_url("v1/llm/generate"),
        json=payload,
        headers=client._get_headers(),
        timeout=60.0,
    )
    check_response(r)
    return r.json()["text"]


@telemetry_client.track_class()
class IntentRecognizer:
    """Match a caller intent string against a fixed set of choices.

    Calls the Guava server LLM endpoint with a JSON-schema constraint so the
    model is forced to return only choices from the provided list.

    Args:
        intent_choices: List of choice strings, or a dict mapping each choice
            to a longer description that helps the model disambiguate between
            similar-sounding options. When a dict is provided, descriptions are
            attached to the returned SuggestedActions so the dialog engine can
            use them when disambiguating multiple matches with the caller.
    """

    def __init__(self, intent_choices: list[str] | dict[str, str]):
        self.intent_choices = intent_choices
        choice_list = [x for x in intent_choices]
        self._schema = create_model(
            "ChoiceModel",
            possible_matches=(
                list[Literal[tuple(choice_list)]],  # type: ignore
                Field(
                    ...,
                    description="Choices that could match the caller's intent, ordered by likelihood. Include all plausible matches.",
                ),
            ),
            __config__={"extra": "forbid"},
        ).model_json_schema()

    def classify(self, intent: str) -> list[SuggestedAction] | None:
        """Return the SuggestedActions that plausibly match the given intent.

        Args:
            intent: Free-form text describing what the caller wants.

        Returns:
            A list of SuggestedActions drawn from self.intent_choices, ordered
            by likelihood, or ``None`` if no choice plausibly matches. Use
            ``result[0]`` if you only want the single best match, or return the
            list as-is to let the dialog engine disambiguate automatically.
        """
        input_prompt = f"""
Classify the intent below into the most appropriate choice(s) from the list.

Intent: <intent>{intent}</intent>
Available Choices: {[x for x in self.intent_choices]}

Rules:
- Default to returning a single choice — the one that best matches the intent.
- Only return additional choices when the intent is genuinely ambiguous: a reasonable person reading it would be unable to decide which category it belongs to. Thematic overlap or partial relevance is NOT enough — do not include weakly or tangentially related choices.
- Order matches by likelihood (most likely first).
- If no choice plausibly matches, return an empty list.
"""
        if isinstance(self.intent_choices, dict):
            description_string = "\n  ".join(
                [f"{key}: {val}" for key, val in self.intent_choices.items()]
            )
            input_prompt += f"""\n\nDetailed descriptions of each choice:\n  {description_string}"""

        text = _generate(input_prompt.strip(), json_schema=self._schema)
        keys = json.loads(text)["possible_matches"]
        if not keys:
            return None
        if isinstance(self.intent_choices, dict):
            return [SuggestedAction(key=k, description=self.intent_choices[k]) for k in keys]
        return [SuggestedAction(key=k) for k in keys]


class _FilterModel(BaseModel):
    matching_appointments: list[str]
    other_appointments: list[str]


@telemetry_client.track_class()
class DatetimeFilter:
    """Filter a list of ISO-8601 datetime slots using natural language queries.

    Args:
        source_list: ISO-8601 datetime strings representing available slots.
    """

    def __init__(self, source_list: list[str]):
        self.source_list = source_list
        self._slots_str = "\n".join(source_list)
        self._schema = _FilterModel.model_json_schema()

    def filter(self, query: str, max_results: int = 5) -> tuple[list[str], list[str]]:
        """Return (matching_slots, fallback_slots) for the given query.

        Args:
            query: Natural language description of the desired time(s).
            max_results: Maximum number of items to return per list.

        Returns:
            A tuple of two lists drawn from self.source_list: slots that
            match the query, and nearby alternatives to offer when nothing
            matches. Both lists are capped at max_results.
        """
        prompt = f"""Return datetime slots from the list that match the query.
If none match, return close alternatives in other_appointments instead.
Never return datetimes that are not in the list.

Query: <query>{query}</query>
Today's Date: {date.today().strftime("%B %d, %Y")}
Available slots:
{self._slots_str}

Return at most {max_results} items per list."""

        text = _generate(prompt, json_schema=self._schema)
        result = _FilterModel.model_validate_json(text)
        return (
            result.matching_appointments[:max_results],
            result.other_appointments[:max_results],
        )


class _DateRangeModel(BaseModel):
    start_date: date = Field(description="The first date of the range (inclusive).")
    end_date: date = Field(description="The last date of the range (inclusive).")


@telemetry_client.track_class()
class DateRangeParser:
    """Parse natural-language time expressions into concrete date ranges.

    Resolves expressions like "next Tuesday" or "the week of the 15th" into
    a pair of dates relative to today. Output is clamped to the next year.
    """

    def __init__(self):
        self._schema = _DateRangeModel.model_json_schema()

    def parse(self, query: str, buffer_days: int = 1) -> tuple[date, date]:
        """Return (start_date, end_date) for the date range described by query.

        Args:
            query: Natural language description of a date or date range.
            buffer_days: Number of days to extend on each side of the parsed
                range so callers can offer nearby alternatives.

        Returns:
            Inclusive start and end dates, clamped to the window between
            today and one year from today.
        """
        today = date.today()
        max_date = today + timedelta(days=365)

        prompt = f"""Extract the date or date range the user is asking about.
If the query mentions a specific day, start_date and end_date should both be that day.
If the query mentions a range like "next week", use the full range.
Dates must be between {today.isoformat()} and {max_date.isoformat()}.
If the query doesn't contain a clear date, default to the next 7 days.

Query: <query>{query}</query>
Today's date: {today.isoformat()} ({today.strftime("%A")})"""

        text = _generate(prompt.strip(), json_schema=self._schema)
        result = _DateRangeModel.model_validate_json(text)

        start = max(today, min(result.start_date - timedelta(days=buffer_days), max_date))
        end = max(today, min(result.end_date + timedelta(days=buffer_days), max_date))

        return start, end
