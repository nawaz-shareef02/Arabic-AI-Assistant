"""
NotificationService — Reusable Notification Dispatcher.

Maintains backward-compatible alias to EmailService.
"""

from typing import Optional
from app.services.email_service import EmailService, EmailProvider, ConsoleEmailProvider


class NotificationService:
    def __init__(self, provider: Optional[EmailProvider] = None):
        self.email_service = EmailService(provider=provider)

    def send_organization_invitation(
        self,
        to_email: str,
        org_name: str,
        invitation_link: str,
        role_name: str,
        inviter_name: str = "",
    ) -> bool:
        return self.email_service.send_organization_invitation(
            to_email=to_email,
            org_name=org_name,
            invitation_link=invitation_link,
            role_name=role_name,
            inviter_name=inviter_name,
        )
