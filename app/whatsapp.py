import os
from twilio.rest import Client

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
from_number = os.getenv("TWILIO_WHATSAPP_FROM")

client = Client(account_sid, auth_token)

def send_whatsapp_message(to, body):
    client.messages.create(
        from_=from_number,
        to=to,
        body=body
    )
