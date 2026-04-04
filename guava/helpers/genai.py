from google import genai
from datetime import date, timedelta
from typing import Optional, Literal
from pydantic import BaseModel, create_model, Field


class IntentRecognizer:
    """Classifies a caller intent string into one of a fixed set of choices.

    The caller is responsible for supplying a configured ``google.genai.Client``.
    Guava helpers never create API clients on your behalf.

    Args:
        intent_choices: List of choice strings, or a dict mapping choice → description.
        client:         A configured ``google.genai.Client`` instance.
    """

    def __init__(self, intent_choices: list[str] | dict[str, str], client: genai.Client):
        self.client = client
        self.intent_choices = intent_choices
        self.choice_model = create_model(
            "ChoiceModel",
            caller_choice=(
                Optional[Literal[tuple([x for x in intent_choices])]],  # type: ignore
                Field(
                    ...,
                    description="The choice in the list best matching the caller's request.",
                ),
            ),
            __config__={"extra": "forbid"},
        )

    def classify(self, intent: str) -> str:
        input_prompt = f"""
Pick the choice in the list of choices that best reflects the given intent.
Intent: "{intent}".
Possible Choices: {[x for x in self.intent_choices]}.
"""
        if isinstance(self.intent_choices, dict):
            description_string = "\n  ".join(
                [f"{key}: {val}" for key, val in self.intent_choices.items()]
            )
            input_prompt += f"""Detailed descriptions of each choice: \n  {description_string}"""

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=input_prompt.strip(),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": self.choice_model.model_json_schema(),
            },
        )
        assert response.text
        result = self.choice_model.model_validate_json(response.text)
        return result.caller_choice  # type: ignore


class _DateRangeModel(BaseModel):
    start_date: date = Field(description="The first date of the range (inclusive).")
    end_date: date = Field(description="The last date of the range (inclusive).")


class DateRangeParser:
    """
    Parses natural-language time expressions into concrete date ranges.

    The caller is responsible for supplying a configured ``google.genai.Client``.
    Guava helpers never create API clients on your behalf.

    Examples:
        "Tuesday April 7"   → (2026-04-07, 2026-04-07)
        "next week"          → (2026-04-06, 2026-04-10)
        "Thursday afternoon" → the nearest Thursday

    Args:
        client: A configured ``google.genai.Client`` instance.
        model:  Gemini model ID to use (default: gemini-2.5-flash).
    """

    def __init__(
        self,
        client: genai.Client,
        model: str = "gemini-2.5-flash",
    ):
        self.client = client
        self.model = model
        self._schema = _DateRangeModel.model_json_schema()

    def parse(self, query: str, buffer_days: int = 1) -> tuple[date, date]:
        """
        Returns (start_date, end_date) for the date range described by *query*.

        buffer_days is added on each side of the parsed range so callers can
        fetch a slightly wider window and offer nearby alternatives.
        """
        today = date.today()
        max_date = today + timedelta(days=365)

        prompt = f"""Extract the date or date range the user is asking about.
If the query mentions a specific day, start_date and end_date should both be that day.
If the query mentions a range like "next week", use the full range.
Dates must be between {today.isoformat()} and {max_date.isoformat()}.
If the query doesn't contain a clear date, default to the next 7 days.

Query: "{query}"
Today's date: {today.isoformat()} ({today.strftime("%A")})"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt.strip(),
            config={
                "response_mime_type": "application/json",
                "response_json_schema": self._schema,
            },
        )
        assert response.text
        result = _DateRangeModel.model_validate_json(response.text)

        start = max(today, min(result.start_date - timedelta(days=buffer_days), max_date))
        end = max(today, min(result.end_date + timedelta(days=buffer_days), max_date))

        return start, end


class _FilterModel(BaseModel):
    matching_appointments: list[str]
    other_appointments: list[str]


class DatetimeFilter:
    """
    Filters a static list of ISO-8601 datetime slots using natural language queries.

    Optimized for repeated calls against the same slot list: the formatted slot
    string and JSON schema are computed once at construction time rather than
    on every filter() call.

    The caller is responsible for supplying a configured ``google.genai.Client``.
    Guava helpers never create API clients on your behalf.

    Args:
        source_list: ISO-8601 datetime strings representing available slots.
        client:      A configured ``google.genai.Client`` instance.
        model:       Gemini model ID to use (default: gemini-2.5-flash).
    """

    def __init__(
        self,
        source_list: list[str],
        client: genai.Client,
        model: str = "gemini-2.5-flash",
    ):
        self.client = client
        self.model = model
        self.source_list = source_list
        # Pre-format the slot list once — it doesn't change between filter() calls.
        self._slots_str = "\n".join(source_list)
        self._schema = _FilterModel.model_json_schema()

    def filter(self, query: str, max_results: int = 5) -> tuple[list[str], list[str]]:
        """
        Returns (matching_slots, fallback_slots) for the given natural-language query.

        matching_slots  - slots from source_list that match the query.
        fallback_slots  - nearby alternatives to suggest when nothing matches.

        Both lists are capped at max_results.
        """
        prompt = f"""Return datetime slots from the list that match the query.
If none match, return close alternatives in other_appointments instead.
Never return datetimes that are not in the list.

Query: {query}
Today's Date: {date.today().strftime("%B %d, %Y")}
Available slots:
{self._slots_str}

Return at most {max_results} items per list."""

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": self._schema,
            },
        )
        assert response.text
        result = _FilterModel.model_validate_json(response.text)
        return result.matching_appointments[:max_results], result.other_appointments[:max_results]
