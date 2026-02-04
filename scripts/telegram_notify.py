#!/usr/bin/env python3
import csv
import json
import os
import re
import subprocess
import sys
import math
from datetime import datetime
from urllib import request

SECONDS_IN_DAY = 86400
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
PERSIAN_MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]
PERSIAN_WEEKDAYS = [
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنجشنبه",
    "جمعه",
    "شنبه",
    "یک‌شنبه",
]


def eprint(*args):
    print(*args, file=sys.stderr)


def is_truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def get_env(name, required=True, default=None):
    value = os.getenv(name, default)
    if required and not value:
        eprint(f"Missing required env var: {name}")
        sys.exit(1)
    return value


def run_git(args):
    result = subprocess.run(["git"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def get_commit_info():
    return {
        "committer": run_git(["log", "-1", "--pretty=format:%an"]),
        "commit_date_iso": run_git(["log", "-1", "--pretty=format:%ci"]),
        "commit_date_short": run_git(["log", "-1", "--pretty=format:%cs"]),
        "commit_message": run_git(["log", "-1", "--pretty=format:%s"]),
        "commit_sha": run_git(["log", "-1", "--pretty=format:%h"]),
    }


def parse_exam_rows(path):
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            name = (row.get("title") or row.get("name") or "").strip()
            exam_time = (row.get("time") or "").strip()
            gregorian_date = (row.get("date") or row.get("gregorianDate") or "").strip()
            if not (name and gregorian_date):
                continue

            try:
                exam_dt = parse_gregorian_date(gregorian_date)
            except ValueError:
                continue

            day = get_persian_weekday(exam_dt)
            persian_date = format_persian_date(exam_dt)

            rows.append(
                {
                    "date": exam_dt,
                    "name": name,
                    "persian_date": persian_date,
                    "time": exam_time,
                    "day": day,
                }
            )

    return rows


def parse_gregorian_date(value):
    parts = value.strip().split("-")
    if len(parts) != 3:
        raise ValueError("Invalid date format")
    year, month, day = (int(p) for p in parts)
    return datetime(year, month, day)


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy <= 1600:
        jy = 0
        gy -= 621
    else:
        jy = 979
        gy -= 1600

    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def get_persian_weekday(date_value):
    return PERSIAN_WEEKDAYS[date_value.weekday()]


def format_persian_date(date_value):
    jy, jm, jd = gregorian_to_jalali(date_value.year, date_value.month, date_value.day)
    return f"{to_persian_digits(jd)} {PERSIAN_MONTHS[jm - 1]}"


def days_between(a, b):
    return math.ceil((a - b).total_seconds() / SECONDS_IN_DAY)


def filter_upcoming(rows, now=None):
    now = now or datetime.now()
    return [row for row in rows if days_between(row["date"], now) >= 0]


def build_exam_list(rows, now=None):
    if not rows:
        return ""

    now = now or datetime.now()
    out_lines = []
    prev_date = None
    for row in rows:
        if prev_date is not None:
            gap = days_between(row["date"], prev_date)
            if gap > 0:
                remaining = f"{gap} روز بعد"
        else:
            days_left = days_between(row["date"], now)
            if days_left > 0:
                remaining = f"{days_left} روز مانده"
            elif days_left == 0:
                remaining = "امروز"
            else:
                remaining = "گذشته"
                
        prev_date = row["date"]

        out_lines.append(
            f"\n• <b>{row['name']}</b>\n {row['day']} | {row['persian_date']} | {row['time']} | {remaining}\n"
        )
    return "".join(out_lines)


def send_telegram_message(bot_token, chat_id, message):
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with request.urlopen(req) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to send Telegram request: {exc}")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError(f"Unexpected Telegram response: {body}")

    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram API error: {body}")


def to_persian_digits(value):
    text = str(value)
    return re.sub(r"[0-9]", lambda m: PERSIAN_DIGITS[int(m.group())], text)


def persianize_html_text(html):
    parts = re.split(r"(<[^>]+>)", html)
    for i in range(0, len(parts), 2):
        parts[i] = to_persian_digits(parts[i])
    return "".join(parts)


def main():
    event_type = get_env("EVENT_TYPE")
    dry_run = is_truthy(os.getenv("DRY_RUN", ""))
    bot_token = get_env("BOT_TOKEN", required=not dry_run)
    chat_id = get_env("CHAT_ID", required=not dry_run)
    repo_owner = get_env("REPO_OWNER")
    repo_name = get_env("REPO_NAME")

    exams = parse_exam_rows("data.csv")
    upcoming = filter_upcoming(exams)
    exam_list = build_exam_list(upcoming)
    pages_url = f"https://{repo_owner}.github.io/{repo_name}"

    if event_type == "commit":
        commit = get_commit_info()
        if exam_list:
            schedule_block = f"<blockquote expandable>{exam_list}</blockquote>\n\n"
        else:
            schedule_block = "✅ همه آزمون‌ها پشت سر گذاشته شده‌اند یا تاریخ آن‌ها به اتمام رسیده است.\n\n"

        message = (
            "<b>📚آپدیت آزمون‌های پیش رو</b>\n\n"
            f"{schedule_block}"
            "<b>🔄 آخرین بروزرسانی:</b>\n"
            f"👤 <b>Commiter:</b> {commit['committer']}\n"
            f"📅 <b>Date:</b> {commit['commit_date_short']}\n"
            f"📝 <b>Message:</b> {commit['commit_message']}\n\n"
            f"🌐 <a href='{pages_url}'>مشاهده صفحه وب</a>"
        )
    elif event_type == "daily_update":
        if exam_list:
            schedule_block = f"<blockquote expandable>{exam_list}</blockquote>\n\n"
        else:
            schedule_block = "✅ همه آزمون‌ها پشت سر گذاشته شده‌اند یا تاریخ آن‌ها به اتمام رسیده است.\n\n"

        message = (
            "<b>📅 زمان‌بندی روزانه آزمون‌های باقیمانده</b> \n\n"
            f"{schedule_block}"
            f"🌐 <a href='{pages_url}'>مشاهده صفحه وب</a>"
        )
    else:
        eprint(f"Unknown EVENT_TYPE: {event_type}")
        sys.exit(1)

    message = persianize_html_text(message)

    if dry_run:
        print("DRY RUN: message would be sent.")
        print(message)
        return

    send_telegram_message(bot_token, chat_id, message)
    print("Notification sent.")


if __name__ == "__main__":
    main()
