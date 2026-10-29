from datetime import datetime

from pydantic import BaseModel, Field


class SMSMessage(BaseModel):
    """An inbound SMS message received on one of your organization's numbers."""

    id: str = Field(description="Unique ID of the message.", examples=["6710a3f2c1e4b5a6d7e8f901"])
    from_number: str = Field(description="Sender, in E.164 format.", examples=["+14155550123"])
    to_number: str = Field(
        description="Your organization's number that received the message, in E.164 format.",
        examples=["+14155550100"],
    )
    content: str = Field(description="Message body.", examples=["Yes, 3pm works for me."])
    received_at: datetime = Field(description="When Guava received the message, in UTC.")
    direction: str = Field(description="Always `inbound`.", examples=["inbound"])
