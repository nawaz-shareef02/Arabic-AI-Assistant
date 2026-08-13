"""
EmailService — Enterprise Reusable SMTP Email Delivery Service.

Handles asynchronous and synchronous email notification dispatch
with graceful error recovery, configurable SMTP transport, and audit logging.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("app.services.email_service")


class EmailService:
    """
    Enterprise Email Service for password reset notifications and system alerts.
    """

    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_username = settings.SMTP_USERNAME
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL
        self.from_name = settings.SMTP_FROM_NAME
        self.use_tls = settings.SMTP_USE_TLS
        self.frontend_url = settings.FRONTEND_URL

    def send_password_reset_email(self, to_email: str, reset_token: str) -> bool:
        """
        Constructs and dispatches password reset email containing the secure token link.

        Parameters
        ----------
        to_email : str
            Recipient email address.
        reset_token : str
            Raw cryptographically secure reset token.
            NEVER logged or saved in persistent error logs.

        Returns
        -------
        bool
            True if sent successfully, False if SMTP dispatch failed gracefully.
        """
        reset_url = f"{self.frontend_url.rstrip('/')}/reset-password?token={reset_token}"

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

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        try:
            # Connect to SMTP server
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=5)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=5)
                if self.use_tls:
                    server.starttls()

            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)

            server.sendmail(self.from_email, [to_email], msg.as_string())
            server.quit()

            logger.info(
                "AUDIT | Action: reset_email_sent | Recipient: %s | Status: success",
                to_email,
            )
            return True

        except Exception as exc:
            # Never leak reset_token or passwords in error message.
            logger.warning(
                "AUDIT | Action: reset_email_failed | Recipient: %s | Reason: %s (graceful fallback)",
                to_email,
                type(exc).__name__,
            )
            return False
