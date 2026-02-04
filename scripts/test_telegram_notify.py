#!/usr/bin/env python3
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from datetime import datetime

import telegram_notify as tn


class TelegramNotifyTests(unittest.TestCase):
    def test_parse_exam_rows_filters_and_sorts(self):
        csv_content = (
            "title,date,time\n"
            "Exam Past,2026-01-01,08:00\n"
            "Exam Today,2026-02-04,09:00\n"
            "Exam Future,2026-02-06,11:00\n"
        )
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = f.name

        try:
            rows = tn.parse_exam_rows(temp_path)
        finally:
            os.unlink(temp_path)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "Exam Past")
        self.assertEqual(rows[1]["name"], "Exam Today")
        self.assertEqual(rows[2]["name"], "Exam Future")

    def test_build_exam_list_text(self):
        fixed_now = datetime(2026, 2, 4, 0, 0, 0)
        rows = [
            {"date": fixed_now, "name": "Exam Today", "persian_date": "1404/11/15", "time": "09:00", "day": "Tue"},
            {"date": fixed_now.replace(day=6), "name": "Exam Future", "persian_date": "1404/11/17", "time": "11:00", "day": "Thu"},
            {"date": fixed_now.replace(day=2), "name": "Exam Past", "persian_date": "1404/11/13", "time": "08:00", "day": "Sun"},
        ]
        upcoming = tn.filter_upcoming(rows, now=fixed_now)
        text = tn.build_exam_list(upcoming, now=fixed_now)

        self.assertIn("Exam Today", text)
        self.assertIn("امروز", text)
        self.assertIn("فاصله تا امتحان بعدی: 2 روز", text)
        self.assertNotIn("Exam Past", text)

    def test_dry_run_skips_telegram_call(self):
        env = {
            "EVENT_TYPE": "daily_update",
            "REPO_OWNER": "example",
            "REPO_NAME": "repo",
            "DRY_RUN": "true",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(tn, "send_telegram_message") as send_mock:
                with redirect_stdout(io.StringIO()) as output:
                    tn.main()

        send_mock.assert_not_called()
        self.assertIn("DRY RUN", output.getvalue())


if __name__ == "__main__":
    unittest.main()
