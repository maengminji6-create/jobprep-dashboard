"""메일 보내기(비밀번호 재설정 링크). 외부 SMTP 서버 호출은 여기서만 합니다.

MAIL_SERVER 가 비어 있으면 메일을 보내지 않습니다. 개발 모드(DEBUG)에서만 내용을 서버 터미널에 찍어
메일 설정 없이도 흐름을 확인할 수 있게 합니다(배포 환경 로그에는 링크를 남기지 않음).
"""
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app


def enabled() -> bool:
    return bool(current_app.config.get("MAIL_SERVER"))


def send_mail(to: str, subject: str, body: str) -> bool:
    """보냈으면 True. 설정이 없거나 실패하면 False(이유는 서버 로그에만 남김)."""
    cfg = current_app.config
    if not enabled():
        if current_app.debug:
            current_app.logger.warning("[메일 미설정 · 개발 모드라 터미널에만 표시]\n받는 사람: %s\n제목: %s\n%s",
                                       to, subject, body)
        else:
            current_app.logger.warning("MAIL_SERVER 가 없어 메일을 보내지 못했어요(제목: %s).", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME")
    msg["To"] = to
    msg.set_content(body)
    port = int(cfg.get("MAIL_PORT") or 587)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg["MAIL_SERVER"], port, timeout=15)
            server.starttls(context=ssl.create_default_context())
        with server:
            if cfg.get("MAIL_USERNAME"):
                server.login(cfg["MAIL_USERNAME"], cfg.get("MAIL_PASSWORD") or "")
            server.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        current_app.logger.error("메일 전송 실패: %s", exc.__class__.__name__)
        return False
