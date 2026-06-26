"""Notifier"""
import logging, smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import httpx
logger = logging.getLogger("notifier")

class Notifier:
    def __init__(self, telegram_token=None, telegram_chat_id=None, email_sender=None, email_password=None, email_receiver=None):
        self.tg_token = telegram_token
        self.tg_chat = telegram_chat_id
        self.email_from = email_sender
        self.email_pass = email_password
        self.email_to = email_receiver

    async def send_alert(self, sub, entry, reason):
        msg = "Ticket Alert: {} -> {} NT${} {}".format(sub["origin"], sub["destination"], entry["price"], reason)
        if self.tg_token and self.tg_chat:
            await self._telegram(msg)
        if self.email_from and self.email_pass and self.email_to:
            subj = "[Ticket Alert] {} -> {} NT${}".format(sub["origin"], sub["destination"], entry["price"])
            self._email(subj, msg)

    async def _telegram(self, msg):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://api.telegram.org/bot{}/sendMessage".format(self.tg_token), json={"chat_id": self.tg_chat, "text": msg})
                logger.info("Telegram: {}".format(r.status_code))
        except Exception as ex:
            logger.error("Telegram failed: {}".format(ex))

    def _email(self, subject, body):
        m = MIMEMultipart("alternative")
        m["Subject"] = subject
        m["From"] = self.email_from
        m["To"] = self.email_to
        m.attach(MIMEText(body, "plain", "utf-8"))
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
                s.login(self.email_from, self.email_pass)
                s.sendmail(self.email_from, self.email_to, m.as_string())
            logger.info("Email sent")
        except Exception as ex:
            logger.error("Email failed: {}".format(ex))
