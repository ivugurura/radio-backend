import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(OSError,),
    retry_backoff=30,
    retry_kwargs={'max_retries': 3},
)
def send_account_email(self, to: str, subject: str, body: str) -> None:
    """Send an already-rendered account email (invite, password reset)."""
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to],
        fail_silently=False,
    )
    logger.info('Sent account email %r to %s', subject, to)
