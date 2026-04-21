# Examples

- [./property_insurance.py](./property_insurance.py) - An inbound phone/WebRTC/local call example where an agent answers property insurance policy questions using RAG via the `DocumentQA` helper class.
- [./help_desk.py](./help_desk.py) - An inbound phone call example where an agent answers product questions via RAG and routes callers to the correct department (Sales, Delivery & Returns, Account Management) using intent recognition.
- [./restaurant_waitlist.py](./restaurant_waitlist.py) - An inbound phone/WebRTC/local call example where an agent collects caller name, party size, and callback number to add them to a restaurant waitlist using `call.set_task(...)`.
- [./cash_advance.py](./cash_advance.py) - An inbound phone call example where an agent handles cash advance requests by greeting callers, classifying intent, collecting account details (name, DOB, last four SSN) for identity verification, and informing them of their eligibility.
- [./scheduling_outbound.py](./scheduling_outbound.py) - An outbound phone call example where an agent calls patients to schedule dental appointments, using a searchable `calendar_slot` field and a `DatetimeFilter` to find available slots.
- [./polling_campaign.py](./polling_campaign.py) - An outbound campaign example where an agent calls a list of contacts to conduct a non-partisan political opinion poll, collecting structured responses via `call.set_task(...)` with multiple-choice and free-text fields.
- [./multiple_agents.py](./multiple_agents.py) - Demonstrates running multiple agents in a single process using `guava.Runner`, with one agent listening on a phone number and another on WebRTC.
