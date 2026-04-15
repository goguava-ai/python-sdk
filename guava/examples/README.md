# Examples

- `./property_insurance.py` - An outbound call example using the `CallController` API that answers property insurance policy questions with RAG and the `DocumentQA` class, with bilingual (English/Spanish) support.
- `./thai_palace.py` - An inbound call example using the `CallController` API that acts as a virtual assistant for Thai Palace, collecting caller name, party size, and callback phone number to add them to the restaurant waitlist.
- `./scheduling_inbound.py` - An inbound call example using the `CallController` API that books dental appointments for Bright Smile Dental by collecting the caller's name, date of birth, and a preferred appointment slot using `DatetimeFilter`.
- `./scheduling_outbound.py` - An outbound call example using the `CallController` API that calls a named patient to schedule a dental appointment and sends an SMS confirmation with the confirmed time after the call.
- `./credit_card_activation.py` - An inbound call example using the `CallController` API that walks callers through credit card activation for Harper Valley Bank, verifying SSN, cardholder name, card number, and CVV step by step.
- `./inbound_sip.py` - Starts an inbound SIP listener using the Thai Palace `CallController`, creating a new SIP agent code automatically if one is not provided.
- `./inbound_webrtc.py` - Starts an inbound WebRTC listener using the Thai Palace `CallController`, creating a new WebRTC agent code with a 5-minute TTL if one is not provided.
- `./polling.py` - An outbound campaign example using the `CallController` API that calls a list of contacts to conduct a non-partisan political opinion poll, collecting top issues, governor approval, and voting likelihood, then prints results.
- `./mock_appointments.py` - Helper module (imported by scheduling examples) that generates a list of mock available appointment slots for the next 25 days.

## agent/

These examples use the decorator-based `Agent` API instead of the `CallController` class.

- `./agent/property_insurance.py` - An inbound phone example using the `Agent` API that answers property insurance policy questions using RAG and `DocumentQA`.
- `./agent/restaurant_waitlist.py` - An inbound example using the `Agent` API that adds callers to the Thai Palace restaurant waitlist; supports phone, WebRTC, and local call modes.
- `./agent/help_desk.py` - An inbound phone example using the `Agent` API that serves as a help desk for Clearfield Home & Living, answering questions via RAG and routing callers to Sales, Delivery & Returns, Account Management, or a general representative using intent recognition.
- `./agent/scheduling_outbound.py` - An outbound phone example using the `Agent` API that calls a named patient to schedule a dental appointment at Bright Smile Dental, using `DatetimeFilter` to suggest available slots.
- `./agent/polling_campaign.py` - An outbound campaign example using the `Agent` API that creates a campaign, uploads contacts, and conducts a non-partisan political opinion poll collecting top issues, governor approval, and voting likelihood.
