"""
EmailService — Enterprise Pluggable Email Delivery Architecture.

Supports:
- Pluggable EmailProvider (ConsoleEmailProvider for dev/tests, SMTPEmailProvider for production)
- Organization Invitation Emails (configurable FRONTEND_URL / INVITATION_BASE_URL)
- Password Reset Emails
- Zero raw credential / token leakage in audit logs
"""

import logging
import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("app.services.email_service")


class EmailProvider(ABC):
    """Abstract Base Class for Email Delivery Providers."""

    @abstractmethod
    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> bool:
        """Dispatches an email. Returns True on success, False on failure."""
        pass


class ConsoleEmailProvider(EmailProvider):
    """
    Console / Mock Email Provider for local development, staging without SMTP,
    and automated unit testing.
    """

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> bool:
        sender = f"{from_name or settings.SMTP_FROM_NAME} <{from_email or settings.SMTP_FROM_EMAIL}>"
        logger.info(
            "EMAIL_DISPATCH [ConsoleProvider] | From: %s | To: %s | Subject: %s |\n"
            "--- Body (Text) ---\n%s\n--------------------",
            sender,
            to_email,
            subject,
            body_text,
        )
        return True


class SMTPEmailProvider(EmailProvider):
    """
    Production SMTP Email Provider supporting TLS / SSL and authentication.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: Optional[bool] = None,
    ):
        self.host = host if host is not None else settings.SMTP_HOST
        self.port = port if port is not None else settings.SMTP_PORT
        self.username = username if username is not None else settings.SMTP_USERNAME
        self.password = password if password is not None else settings.SMTP_PASSWORD
        self.use_tls = use_tls if use_tls is not None else settings.SMTP_USE_TLS

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> bool:
        sender_email = from_email or settings.SMTP_FROM_EMAIL
        sender_name = from_name or settings.SMTP_FROM_NAME

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{sender_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        try:
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=5)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=5)
                if self.use_tls:
                    server.starttls()

            if self.username and self.password:
                server.login(self.username, self.password)

            server.sendmail(sender_email, [to_email], msg.as_string())
            server.quit()

            logger.info(
                "AUDIT | Action: email_sent | Recipient: %s | Subject: %s | Status: success",
                to_email,
                subject,
            )
            return True

        except Exception as exc:
            # Never leak reset_token, invitation_token, or SMTP passwords in error logs.
            logger.warning(
                "AUDIT | Action: email_failed | Recipient: %s | Reason: %s (graceful fallback)",
                to_email,
                type(exc).__name__,
            )
            return False


def get_default_email_provider() -> EmailProvider:
    """
    Factory resolving active EmailProvider based on settings.
    """
    if settings.EMAIL_PROVIDER == "smtp":
        return SMTPEmailProvider()
    elif settings.EMAIL_PROVIDER == "console":
        return ConsoleEmailProvider()
    else:
        # "auto": use SMTP if configured and not pointing to localhost, else Console
        if settings.SMTP_HOST and settings.SMTP_HOST not in ("localhost", "127.0.0.1"):
            return SMTPEmailProvider()
        return ConsoleEmailProvider()


class EmailService:
    """
    Enterprise Email Service orchestrating transactional emails.
    """

    def __init__(self, provider: Optional[EmailProvider] = None):
        self.provider = provider or get_default_email_provider()
        self.frontend_url = settings.resolved_invitation_base_url

    def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        """
        Constructs and dispatches password reset email containing the secure token link.
        """
        reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={reset_token}"
        subject = "Reset Your ArabIQ Password"
        body_text = (
            f"Hello,\n\n"
            f"We received a request to reset your password for your ArabIQ account.\n\n"
            f"Please click the link below or copy it into your browser to reset your password:\n"
            f"{reset_url}\n\n"
            f"This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.\n"
            f"If you did not request a password reset, please ignore this email.\n\n"
            f"Regards,\n"
            f"ArabIQ Security Team"
        )
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f5; margin: 0; padding: 20px; }}
                .card {{ background-color: #ffffff; border-radius: 8px; max-width: 550px; margin: 0 auto; padding: 30px; border: 1px solid #e4e4e7; }}
                .btn {{ display: inline-block; background-color: #18181b; color: #ffffff !important; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 14px; margin: 20px 0; }}
                .footer {{ font-size: 12px; color: #71717a; margin-top: 25px; border-top: 1px solid #f4f4f5; padding-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Reset Your ArabIQ Password</h2>
                <p>Hello,</p>
                <p>We received a request to reset your password for your ArabIQ account.</p>
                <p><a href="{reset_url}" class="btn">Reset Password</a></p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="font-size: 12px; word-break: break-all; color: #3f3f46;">{reset_url}</p>
                <p>This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.</p>
                <p>If you did not request this, you can safely ignore this message.</p>
                <div class="footer">
                    &copy; ArabIQ Enterprise SaaS — Secure Document Intelligence
                </div>
            </div>
        </body>
        </html>
        """
        return self.provider.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

    def send_organization_invitation(
        self,
        to_email: str,
        org_name: str,
        invitation_link: str,
        role_name: str,
        inviter_name: str = "",
    ) -> bool:
        """
        Constructs and dispatches organization invitation email.
        """
        subject = f"You've been invited to join {org_name} on ArabIQ"
        inviter_text = f" by {inviter_name}" if inviter_name else ""

        body_text = (
            f"Hello,\n\n"
            f"You have been invited{inviter_text} to join {org_name} as a {role_name} on ArabIQ.\n\n"
            f"Please click the link below to accept your invitation:\n"
            f"{invitation_link}\n\n"
            f"This link will expire in {settings.INVITATION_TOKEN_EXPIRE_HOURS // 24} days.\n"
            f"If you were not expecting this invitation, you can ignore this email.\n\n"
            f"Regards,\n"
            f"ArabIQ Team"
        )

        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #09090b; color: #f4f4f5; margin: 0; padding: 20px; }}
                .card {{ background-color: #18181b; border-radius: 12px; max-width: 550px; margin: 0 auto; padding: 32px; border: 1px solid #27272a; }}
                .badge {{ display: inline-block; background-color: #3b82f6; color: #ffffff; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; }}
                .btn {{ display: inline-block; background-color: #2563eb; color: #ffffff !important; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; margin: 24px 0; }}
                .footer {{ font-size: 12px; color: #71717a; margin-top: 25px; border-top: 1px solid #27272a; padding-top: 15px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>Organization Invitation</h2>
                <p>Hello,</p>
                <p>You have been invited{inviter_text} to join <strong>{org_name}</strong> as an enterprise <strong>{role_name}</strong> on ArabIQ AI Platform.</p>
                <p><a href="{invitation_link}" class="btn">Accept Invitation</a></p>
                <p style="font-size: 13px; color: #a1a1aa;">Or copy and paste this link into your browser:</p>
                <p style="font-size: 12px; word-break: break-all; color: #60a5fa;">{invitation_link}</p>
                <p style="font-size: 12px; color: #71717a;">This invitation expires in {settings.INVITATION_TOKEN_EXPIRE_HOURS // 24} days.</p>
                <div class="footer">
                    &copy; ArabIQ Enterprise SaaS — Document Intelligence & RAG
                </div>
            </div>
        </body>
        </html>
        """

        return self.provider.send_email(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
