"""
Module for Multi-Channel Enterprise Report Sharing:
- Telegram Bot API: Sends Executive PDF report with formatted caption insight directly to Telegram channels/groups.
- SMTP Email: Sends styled email with attached PDF report and Markdown insight body to stakeholder email lists.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import requests


def send_telegram_report(
    bot_token: str,
    chat_id: str,
    caption: str,
    pdf_bytes: bytes,
    filename: str = "executive_report.pdf"
) -> tuple[bool, str]:
    """
    Gửi file Báo cáo PDF kèm tóm tắt Insight qua Telegram Bot API.
    """
    if not bot_token or not bot_token.strip():
        return False, "Chưa cung cấp Telegram Bot Token."
    if not chat_id or not chat_id.strip():
        return False, "Chưa cung cấp Telegram Chat ID."
    if not pdf_bytes:
        return False, "Dữ liệu file PDF rỗng."

    bot_token = bot_token.strip()
    chat_id = chat_id.strip()

    clean_caption = caption.strip() if caption else "Báo cáo phân tích kinh doanh từ Veraxus for SQL"
    if len(clean_caption) > 950:
        clean_caption = clean_caption[:940] + "...\n(Xem chi tiết trong file PDF đính kèm)"

    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"

    try:
        files = {
            "document": (filename, pdf_bytes, "application/pdf")
        }
        data = {
            "chat_id": chat_id,
            "caption": f"📊 <b>VERAXUS FOR SQL - EXECUTIVE REPORT</b>\n\n{clean_caption}",
            "parse_mode": "HTML"
        }

        resp = requests.post(url, data=data, files=files, timeout=30)
        res_json = resp.json()

        if resp.status_code == 200 and res_json.get("ok"):
            return True, "Gửi báo cáo qua Telegram thành công!"
        else:
            err_desc = res_json.get("description", resp.text)
            return False, f"Telegram API Error: {err_desc}"
    except Exception as e:
        return False, f"Lỗi kết nối Telegram: {str(e)}"


def send_email_report(
    smtp_server: str,
    smtp_port: int,
    sender_email: str,
    sender_password: str,
    receiver_emails: list[str] | str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    filename: str = "executive_report.pdf",
    use_tls: bool = True
) -> tuple[bool, str]:
    """
    Gửi Báo cáo PDF đính kèm qua Email giao thức SMTP (Gmail, Outlook, Custom SMTP).
    """
    if not smtp_server or not sender_email or not sender_password:
        return False, "Vui lòng cấu hình đầy đủ thông tin SMTP (Server, Email gửi, Mật khẩu ứng dụng)."

    if isinstance(receiver_emails, str):
        receivers = [e.strip() for e in receiver_emails.split(",") if e.strip()]
    else:
        receivers = [str(e).strip() for e in receiver_emails if str(e).strip()]

    if not receivers:
        return False, "Chưa cung cấp email người nhận."

    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = ", ".join(receivers)
        msg["Subject"] = subject or "Báo cáo Phân tích Kinh doanh - Veraxus for SQL"

        formatted_body = body_text.replace("\n", "<br>")
        html_content = f"""
        <html>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1E293B; line-height: 1.6; padding: 20px;">
            <div style="max-width: 650px; margin: 0 auto; background: #ffffff; border: 1px solid #E2E8F0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
                <div style="background: #1F4E78; color: #ffffff; padding: 20px 24px;">
                    <h2 style="margin: 0; font-size: 20px;">📊 BÁO CÁO ĐIỀU HÀNH KINH DOANH</h2>
                    <p style="margin: 4px 0 0 0; opacity: 0.85; font-size: 13px;">Được tạo tự động bởi Trợ lý AI Veraxus for SQL</p>
                </div>
                <div style="padding: 24px;">
                    <div style="background: #F8FAFC; border-left: 4px solid #1F4E78; padding: 14px 18px; border-radius: 4px; margin-bottom: 20px;">
                        <h4 style="margin: 0 0 8px 0; color: #1F4E78;">💡 Tóm tắt Nhận định & Đề xuất Chiến lược:</h4>
                        <div style="font-size: 14px; color: #334155;">{formatted_body}</div>
                    </div>
                    <p style="font-size: 13px; color: #64748B;">
                        📎 <i>File báo cáo đầy đủ chi tiết với bảng dữ liệu và biểu đồ trực quan đã được đính kèm bên dưới.</i>
                    </p>
                </div>
                <div style="background: #F1F5F9; padding: 12px 24px; text-align: center; font-size: 12px; color: #94A3B8;">
                    Veraxus for SQL &bull; AI Business Intelligence Platform
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_content, "html"))

        if pdf_bytes:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(pdf_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename=\"{filename}\"")
            msg.attach(part)

        port = int(smtp_port) if smtp_port else 587
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_server, port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_server, port, timeout=20)
            if use_tls:
                server.starttls()

        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receivers, msg.as_string())
        server.quit()

        return True, f"Đã gửi báo cáo thành công tới {len(receivers)} người nhận!"
    except Exception as e:
        return False, f"Lỗi gửi email: {str(e)}"
