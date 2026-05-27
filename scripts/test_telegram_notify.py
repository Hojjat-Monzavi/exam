#!/usr/bin/env python3
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock

import telegram_notify as tn


class ParseTagsTests(unittest.TestCase):
    def test_single_quoted_tag(self):
        self.assertEqual(tn.parse_tags("'جبرانی'"), ["جبرانی"])

    def test_multiple_tags(self):
        self.assertEqual(tn.parse_tags("'تئوری','عملی'"), ["تئوری", "عملی"])

    def test_empty_string(self):
        self.assertEqual(tn.parse_tags(""), [])

    def test_none(self):
        self.assertEqual(tn.parse_tags(None), [])

    def test_whitespace_only(self):
        self.assertEqual(tn.parse_tags("   "), [])


class JalaliDateTests(unittest.TestCase):
    def test_known_conversions(self):
        cases = [
            ((1405, 3, 2),  datetime(2026, 5, 23)),
            ((1405, 3, 5),  datetime(2026, 5, 26)),
            ((1405, 4, 26), datetime(2026, 7, 17)),
            ((1404, 1, 1),  datetime(2025, 3, 21)),  # Nowruz
        ]
        for jalali, expected in cases:
            with self.subTest(jalali=jalali):
                self.assertEqual(tn.jalali_to_gregorian(*jalali), expected)

    def test_parse_jalali_date_valid(self):
        self.assertEqual(tn.parse_jalali_date("1405-3-2"), datetime(2026, 5, 23))

    def test_parse_jalali_date_invalid_format(self):
        with self.assertRaises(ValueError):
            tn.parse_jalali_date("not-a-date")

    def test_parse_jalali_date_too_few_parts(self):
        with self.assertRaises(ValueError):
            tn.parse_jalali_date("1405-3")


class ParseExamRowsTests(unittest.TestCase):
    def _write_csv(self, content):
        f = tempfile.NamedTemporaryFile(
            "w", delete=False, encoding="utf-8", suffix=".csv"
        )
        f.write(content)
        f.close()
        return f.name

    def test_parses_jalali_dates_and_tags(self):
        path = self._write_csv(
            "title,date,time,tags\n"
            "مقدمات کلیه,1405-3-2,10:30,\n"
            "فیزیک پزشکی,1405-3-5,12:00,'جبرانی'\n"
        )
        try:
            rows = tn.parse_exam_rows(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(rows), 2)

        self.assertEqual(rows[0]["name"], "مقدمات کلیه")
        self.assertEqual(rows[0]["date"], datetime(2026, 5, 23))
        self.assertEqual(rows[0]["tags"], [])
        self.assertEqual(rows[0]["time"], "10:30")

        self.assertEqual(rows[1]["name"], "فیزیک پزشکی")
        self.assertEqual(rows[1]["date"], datetime(2026, 5, 26))
        self.assertEqual(rows[1]["tags"], ["جبرانی"])

    def test_skips_rows_with_invalid_dates(self):
        path = self._write_csv(
            "title,date,time,tags\n"
            "Good,1405-3-2,10:00,\n"
            "Bad,not-a-date,10:00,\n"
        )
        try:
            rows = tn.parse_exam_rows(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Good")

    def test_skips_rows_missing_name_or_date(self):
        path = self._write_csv(
            "title,date,time,tags\n"
            ",1405-3-2,10:00,\n"         # no name
            "No Date,,10:00,\n"          # no date
            "Valid,1405-3-5,12:00,\n"
        )
        try:
            rows = tn.parse_exam_rows(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Valid")

    def test_missing_file_returns_empty(self):
        rows = tn.parse_exam_rows("/nonexistent/path/data.csv")
        self.assertEqual(rows, [])


class FilterUpcomingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 5, 24)
        self.rows = [
            {"date": datetime(2026, 5, 23), "name": "Past"},    # 1 day ago  → excluded
            {"date": datetime(2026, 5, 24), "name": "Today"},   # today (0)  → included
            {"date": datetime(2026, 5, 26), "name": "Future"},  # 2 days out → included
        ]

    def test_excludes_past(self):
        names = [r["name"] for r in tn.filter_upcoming(self.rows, now=self.now)]
        self.assertNotIn("Past", names)

    def test_includes_today_and_future(self):
        names = [r["name"] for r in tn.filter_upcoming(self.rows, now=self.now)]
        self.assertIn("Today", names)
        self.assertIn("Future", names)


class BuildExamListTests(unittest.TestCase):
    def _row(self, dt, name, tags=None):
        return {
            "date": dt,
            "name": name,
            "persian_date": "۱ خرداد",
            "time": "10:00",
            "day": "شنبه",
            "tags": tags or [],
        }

    def test_empty_rows_returns_empty_string(self):
        self.assertEqual(tn.build_exam_list([]), "")

    def test_first_exam_shows_days_remaining(self):
        now = datetime(2026, 5, 22)
        rows = [self._row(datetime(2026, 5, 24), "Exam A")]
        text = tn.build_exam_list(rows, now=now)
        self.assertIn("2 روز مانده", text)

    def test_first_exam_today_shows_امروز(self):
        now = datetime(2026, 5, 23)
        rows = [self._row(datetime(2026, 5, 23), "Exam Today")]
        text = tn.build_exam_list(rows, now=now)
        self.assertIn("امروز", text)

    def test_first_exam_past_shows_گذشته(self):
        now = datetime(2026, 5, 25)
        rows = [self._row(datetime(2026, 5, 23), "Exam Past")]
        text = tn.build_exam_list(rows, now=now)
        self.assertIn("گذشته", text)

    def test_subsequent_exam_shows_gap_from_previous(self):
        now = datetime(2026, 5, 20)
        rows = [
            self._row(datetime(2026, 5, 23), "Exam A"),
            self._row(datetime(2026, 5, 26), "Exam B"),  # 3 days after A
        ]
        text = tn.build_exam_list(rows, now=now)
        # Second exam shows gap from A, not absolute days from today
        self.assertIn("3 روز بعد", text)
        self.assertNotIn("6 روز مانده", text)

    def test_same_day_exams_show_همان_روز(self):
        now = datetime(2026, 5, 20)
        rows = [
            self._row(datetime(2026, 5, 23), "Exam A"),
            self._row(datetime(2026, 5, 23), "Exam B"),
        ]
        text = tn.build_exam_list(rows, now=now)
        self.assertIn("همان روز", text)

    def test_tags_appear_in_output(self):
        now = datetime(2026, 5, 20)
        rows = [self._row(datetime(2026, 5, 23), "فیزیک پزشکی", tags=["جبرانی"])]
        text = tn.build_exam_list(rows, now=now)
        self.assertIn("جبرانی", text)

    def test_no_tags_no_pipe(self):
        now = datetime(2026, 5, 20)
        rows = [self._row(datetime(2026, 5, 23), "مقدمات کلیه", tags=[])]
        text = tn.build_exam_list(rows, now=now)
        # Should have exactly 3 pipes (day | date | time | remaining), not 4
        first_line = [l for l in text.splitlines() if "|" in l][0]
        self.assertEqual(first_line.count("|"), 3)


class DryRunTests(unittest.TestCase):
    def test_dry_run_skips_telegram_and_prints_message(self):
        env = {
            "EVENT_TYPE": "daily_update",
            "REPO_OWNER": "example",
            "REPO_NAME":  "repo",
            "DRY_RUN":    "true",
        }
        # parse_exam_rows returns [] when data.csv is absent — fine for this test
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(tn, "send_telegram_message") as send_mock:
                with redirect_stdout(io.StringIO()) as output:
                    tn.main()

        send_mock.assert_not_called()
        self.assertIn("DRY RUN", output.getvalue())

    def test_commit_event_dry_run(self):
        env = {
            "EVENT_TYPE": "commit",
            "REPO_OWNER": "example",
            "REPO_NAME":  "repo",
            "DRY_RUN":    "true",
        }
        fake_commit = {
            "committer":         "Test User",
            "commit_date_iso":   "2026-05-23 10:00:00 +0330",
            "commit_date_short": "2026-05-23",
            "commit_message":    "update exams",
            "commit_sha":        "abc1234",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(tn, "get_commit_info", return_value=fake_commit):
                with mock.patch.object(tn, "send_telegram_message") as send_mock:
                    with redirect_stdout(io.StringIO()) as output:
                        tn.main()

        send_mock.assert_not_called()
        out = output.getvalue()
        self.assertIn("DRY RUN", out)
        self.assertIn("Test User", out)
        self.assertIn("update exams", out)

    def test_unknown_event_type_exits(self):
        env = {
            "EVENT_TYPE": "unknown_event",
            "REPO_OWNER": "example",
            "REPO_NAME":  "repo",
            "DRY_RUN":    "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(SystemExit) as ctx:
                tn.main()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()