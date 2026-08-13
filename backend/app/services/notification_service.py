"""
NotificationService — Refinement #11: Abstract Email Provider & Notification Service.

Provides pluggable EmailProvider interface (Console/Log provider initially;
ready for SendGrid, AWS SES, Mailgun, or SMTP without business logic churn).
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("app.services.notification_service")


class EmailProvider(ABC):
    @abstractmethod
    def send_email(self, to_email: str, subject: str, body_html: str) -> bool:
        pass


class ConsoleEmailProvider(EmailProvider):
    """Development / Testing Email Provider logging email payloads."""
    def send_email(self, to_email: str, subject: str, body_html: str) -> bool:
        logger.info(
            f"EMAIL_DISPATCH | To: {to_email} | Subject: {subject} |\n"
            f"--- Body ---\n{body_html}\n------------"
        )
        return True


class NotificationService:
    def __init__(self, provider: EmailProvider = None):
        self.provider = provider or ConsoleEmailProvider()

    def send_organization_invitation(
        self,
        to_email: str,
        org_name: str,
        invitation_link: str,
        role_name: str,
    ) -> bool:
        subject = f"You've been invited to join {org_name} on ArabIQ"
        html = (
            f"<h2>Organization Invitation</h2>"
            f"<p>You have been invited to join <strong>{org_name}</strong> as <strong>{role_name}</strong> on ArabIQ AI platform.</p>"
            f"<p><a href='{invitation_link}'>Click here to accept your invitation</a></p>"
            f"<p>Link: {invitation_link}</p>"
        )
        return self.provider.send_email(to_email, subject, html)
