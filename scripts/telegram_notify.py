#!/usr/bin/env python3
import csv
import html
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
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
PERSIAN_WEEKDAYS = [
    "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یک‌شنبه",
]


# ── Utilities ──────────────────────────────────────────────────────────────────

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


def to_persian_digits(value):
    return re.sub(r"[0-9]", lambda m: PERSIAN_DIGITS[int(m.group())], str(value))


def persianize_html_text(text):
    # Only replace digits outside of HTML tags
    parts = re.split(r"(<[^>]+>)", text)
    for i in range(0, len(parts), 2):
        parts[i] = to_persian_digits(parts[i])
    return "".join(parts)


def esc(value):
    """Escape text for safe placement inside rich-message HTML."""
    return html.escape(str(value), quote=False)


# ── Git ────────────────────────────────────────────────────────────────────────

def run_git(args):
    result = subprocess.run(["git"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def get_commit_info():
    return {
        "committer":         run_git(["log", "-1", "--pretty=format:%an"]),
        "commit_date_iso":   run_git(["log", "-1", "--pretty=format:%ci"]),
        "commit_date_short": run_git(["log", "-1", "--pretty=format:%cs"]),
        "commit_date_unix":  run_git(["log", "-1", "--pretty=format:%ct"]),
        "commit_message":    run_git(["log", "-1", "--pretty=format:%s"]),
        "commit_sha":        run_git(["log", "-1", "--pretty=format:%h"]),
    }


# ── Date helpers ───────────────────────────────────────────────────────────────

def jalali_to_gregorian(jy, jm, jd):
    """Convert a Jalali (Solar Hijri) date to a Gregorian datetime."""
    gy = 621 if jy <= 979 else 1600
    jy -= 0 if jy <= 979 else 979
    days = (365 * jy) + (jy // 33 * 8) + ((jy % 33 + 3) // 4) + 78 + jd
    days += (jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186
    gy += 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_days = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return datetime(gy, gm, gd)


def gregorian_to_jalali(gy, gm, gd):
    """Convert Gregorian date to (jy, jm, jd) tuple."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy <= 1600:
        jy = 0
        gy -= 621
    else:
        jy = 979
        gy -= 1600
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        - 80 + gd + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + (days // 31) if days < 186 else 7 + ((days - 186) // 30)
    jd = 1 + (days % 31) if days < 186 else 1 + ((days - 186) % 30)
    return jy, jm, jd


def parse_jalali_date(value):
    """Parse a Jalali date string 'YYYY-M-D' into a datetime object."""
    parts = value.strip().split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid Jalali date: {value!r}")
    jy, jm, jd = (int(p) for p in parts)
    return jalali_to_gregorian(jy, jm, jd)


def get_persian_weekday(dt):
    return PERSIAN_WEEKDAYS[dt.weekday()]


def format_persian_date(dt):
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{to_persian_digits(jd)} {PERSIAN_MONTHS[jm - 1]}"


def days_between(a, b):
    """Ceiling of (a - b) in days. Positive means a is in the future relative to b."""
    return math.ceil((a - b).total_seconds() / SECONDS_IN_DAY)


# ── Tags ───────────────────────────────────────────────────────────────────────

def parse_tags(tag_str):
    """Parse a tag string like \"'جبرانی'\" or \"'تئوری','عملی'\" into a list."""
    if not tag_str or not tag_str.strip():
        return []
    return [
        t.strip().strip("'\"` ")
        for t in tag_str.split(",")
        if t.strip().strip("'\"` ")
    ]


# ── CSV ────────────────────────────────────────────────────────────────────────

def parse_exam_rows(path):
    if not os.path.exists(path):
        eprint(f"CSV not found: {path}")
        return []

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            name      = (row.get("title") or row.get("name") or "").strip()
            exam_time = (row.get("time") or "").strip()
            date_str  = (row.get("date") or "").strip()
            tags      = parse_tags(row.get("tags") or "")

            if not (name and date_str):
                continue

            try:
                exam_dt = parse_jalali_date(date_str)
                # Apply time if provided
                if exam_time:
                    h, m = map(int, exam_time.split(':'))
                    exam_dt = exam_dt.replace(hour=h, minute=m)
            except (ValueError, TypeError) as exc:
                eprint(f"Skipping row {name!r}: {exc}")
                continue

            rows.append({
                "date":         exam_dt,
                "name":         name,
                "persian_date": format_persian_date(exam_dt),
                "time":         exam_time,
                "day":          get_persian_weekday(exam_dt),
                "tags":         tags,
            })

    # Sort by datetime
    rows.sort(key=lambda x: x["date"])
    return rows


def filter_upcoming(rows, now=None):
    now = now or datetime.now()
    return [row for row in rows if days_between(row["date"], now) >= 0]


# ── Rich message builders ───────────────────────────────────────────────────────

def build_exam_table(rows, now=None):
    """Build an HTML <table> (Telegram rich-message format) of upcoming exams."""
    if not rows:
        return ""

    now = now or datetime.now()

    header = (
        "<tr>"
        "<th align=\"right\">آزمون</th>"
        "<th align=\"right\">روز</th>"
        "<th align=\"right\">تاریخ</th>"
        "<th align=\"right\">ساعت</th>"
        "<th align=\"right\">وضعیت</th>"
        "<th algin=\"right\">تگ‌ها</th>"
        "</tr>"
    )

    body_rows = []
    for i, row in enumerate(rows):
        # First exam: show absolute days remaining
        # Subsequent exams: show gap from the previous exam
        if i == 0:
            days_left = days_between(row["date"], now)
            if days_left > 0:
                remaining = f"{days_left} روز مانده"
            elif days_left == 0:
                remaining = "امروز"
            else:
                remaining = "گذشته"
        else:
            gap = days_between(row["date"], rows[i - 1]["date"])
            remaining = f"{gap} روز بعد" if gap > 0 else "همان روز"

        tags_text = "، ".join(row["tags"]) if row["tags"] else "—"

        body_rows.append(
            "<tr>"
            f"<td align=\"right\">{esc(row['name'])}</td>"
            f"<td align=\"right\">{esc(row['day'])}</td>"
            f"<td align=\"right\">{esc(row['persian_date'])}</td>"
            f"<td align=\"right\">{esc(row['time'])}</td>"
            f"<td align=\"right\">{esc(remaining)}</td>"
            f"<td align=\"right\">{esc(tags_text)}</td>"
            "</tr>"
        )

    table = (
        '<table bordered striped>'
        '<caption>برنامه آزمون‌های پیش رو</caption>'
        f"{header}{''.join(body_rows)}"
        "</table>"
    )

    return f"<details open><summary>📚 جدول آزمون‌های پیش رو</summary>{table}</details>"


def build_commit_block(commit):
    """Render the last-commit info, showing the commit date as a tg-time entity."""
    unix_ts = commit["commit_date_unix"]
    fallback = commit["commit_date_short"]
    # format="R" -> relative time (e.g. "۲ روز پیش"); falls back to `fallback` text
    # on clients that don't support rich messages.
    date_html = f'<tg-time unix="{unix_ts}" format="R">{esc(fallback)}</tg-time>'

    return (
        "<b>🔄 آخرین بروزرسانی:</b><br>"
        f"👤 <b>Committer:</b> {esc(commit['committer'])}<br>"
        f"📅 <b>Date:</b> {date_html}<br>"
        f"📝 <b>Message:</b> {esc(commit['commit_message'])}<br>"
    )


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram_rich_message(bot_token, chat_id, html_content):
    payload = {
        "chat_id": chat_id,
        "rich_message": {
            "html": html_content,
            "is_rtl": True,
        },
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "🌐مشاهده صفحه وب",
                        "url": "https://hojjat-monzavi.github.io/exam/",
                        "style": "primary"
                    }
                ]
            ]
        }
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"https://api.telegram.org/bot{bot_token}/sendRichMessage"
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


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    event_type = get_env("EVENT_TYPE")
    dry_run    = is_truthy(os.getenv("DRY_RUN", ""))
    bot_token  = get_env("BOT_TOKEN", required=not dry_run)
    chat_id    = get_env("CHAT_ID",   required=not dry_run)
    repo_owner = get_env("REPO_OWNER")
    repo_name  = get_env("REPO_NAME")

    exams      = parse_exam_rows("data.csv")
    upcoming   = filter_upcoming(exams)
    table_html = build_exam_table(upcoming)

    if table_html:
        schedule_block = table_html + "<br><br>"
    else:
        schedule_block = "✅ همه آزمون‌ها پشت سر گذاشته شده‌اند یا تاریخ آن‌ها به اتمام رسیده است.<br><br>"

    if event_type == "commit":
        commit  = get_commit_info()
        message = (
            "<b>📚 آپدیت آزمون‌های پیش رو</b><br><br>"
            f"{schedule_block}"
            f"{build_commit_block(commit)}"
        )
    elif event_type == "daily_update":
        message = (
            "<b>📅 زمان‌بندی روزانه آزمون‌های باقیمانده</b><br><br>"
            f"{schedule_block}"
        )
    else:
        eprint(f"Unknown EVENT_TYPE: {event_type!r}")
        sys.exit(1)

    message = persianize_html_text(message)

    if dry_run:
        print("DRY RUN — message that would be sent:")
        print(message)
        return

    send_telegram_rich_message(bot_token, chat_id, message)
    print("Notification sent.")


if __name__ == "__main__":
    main()
