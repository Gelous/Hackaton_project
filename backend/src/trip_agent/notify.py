"""Best-effort email delivery via Amazon SES.

This is genuinely optional: the in-app notification inbox (see db.py /
GET /api/notifications) is the reliable path that always works. Email is a
bonus channel for reaching someone who isn't looking at the app — it requires
SES_SENDER_EMAIL to be set AND verified in the AWS SES console (SES sandbox
mode also requires the recipient address to be verified). If it's not
configured or the send fails for any reason, this quietly no-ops rather than
breaking the monitoring sweep.
"""

import logging
import os

logger = logging.getLogger(__name__)

SENDER_EMAIL = os.environ.get("SES_SENDER_EMAIL")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")


def send_email_notification(to_email: str, message: str, booking_link: str | None) -> bool:
    if not SENDER_EMAIL or not to_email:
        return False

    try:
        import boto3

        body = message + (f"\n\nView real current options: {booking_link}" if booking_link else "")
        client = boto3.client("ses", region_name=AWS_REGION)
        client.send_email(
            Source=SENDER_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": "Trip Planner Agent — update on your trip"},
                "Body": {"Text": {"Data": body}},
            },
        )
        return True
    except Exception:
        logger.exception("SES email notification failed; falling back to in-app inbox only")
        return False
