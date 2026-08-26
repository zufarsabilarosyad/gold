"""Calendars, business days and billing periods."""

import datetime
import unittest

from strongback.core.dates import (
    add_days,
    add_months,
    date_range,
    days_between,
    days_in_month,
    format_date,
    month_end,
    nth_weekday_of_month,
    parse_date,
)
from strongback.core.period import BillingPeriod, PeriodSchedule, monthly_schedule
from strongback.core.workcalendar import WorkCalendar, calendar_named, federal_holidays
from strongback.errors import InputError, ParseError, PeriodError


class DateArithmeticTest(unittest.TestCase):
    """Month arithmetic clamps rather than overflowing."""

    def test_adding_a_month_to_the_thirty_first_clamps(self):
        self.assertEqual(add_months("2024-01-31", 1), datetime.date(2024, 2, 29))

    def test_subtracting_months_works(self):
        self.assertEqual(add_months("2024-03-31", -1), datetime.date(2024, 2, 29))

    def test_month_end_knows_leap_years(self):
        self.assertEqual(month_end("2024-02-10"), datetime.date(2024, 2, 29))
        self.assertEqual(days_in_month(2023, 2), 28)

    def test_inclusive_and_exclusive_day_counts_differ_by_one(self):
        self.assertEqual(days_between("2024-09-01", "2024-09-30"), 29)
        self.assertEqual(days_between("2024-09-01", "2024-09-30", inclusive=True), 30)

    def test_a_bad_date_is_a_parse_error(self):
        self.assertRaises(ParseError, parse_date, "2024-13-01")

    def test_date_range_is_inclusive_at_both_ends(self):
        days = [format_date(day) for day in date_range("2024-09-01", "2024-09-03")]
        self.assertEqual(days, ["2024-09-01", "2024-09-02", "2024-09-03"])

    def test_nth_weekday_is_computed_not_looked_up(self):
        self.assertEqual(nth_weekday_of_month(2024, 1, 0, 3), datetime.date(2024, 1, 15))


class WorkCalendarTest(unittest.TestCase):
    """Business days skip weekends and holidays, and only those."""

    def setUp(self):
        self.calendar = calendar_named("us-federal")

    def test_federal_holidays_are_eleven_a_year(self):
        self.assertEqual(len(federal_holidays(2024)), 11)

    def test_thanksgiving_is_not_a_workday(self):
        self.assertFalse(self.calendar.is_workday("2024-11-28"))

    def test_the_day_after_thanksgiving_is(self):
        self.assertTrue(self.calendar.is_workday("2024-11-29"))

    def test_business_days_skip_the_holiday(self):
        self.assertEqual(
            format_date(self.calendar.add_business_days("2024-11-27", 1)), "2024-11-29"
        )

    def test_counting_business_days_excludes_the_start(self):
        self.assertEqual(self.calendar.business_days_between("2024-11-25", "2024-12-02"), 4)

    def test_a_seven_day_calendar_has_no_weekend(self):
        self.assertTrue(calendar_named("seven-day").is_workday("2024-09-15"))

    def test_a_negative_count_walks_backwards(self):
        self.assertEqual(
            format_date(self.calendar.add_business_days("2024-11-29", -1)), "2024-11-27"
        )

    def test_an_unknown_calendar_is_refused(self):
        self.assertRaises(InputError, calendar_named, "lunar")


class BillingPeriodTest(unittest.TestCase):
    """A period has an end and a measurement cutoff, and they differ."""

    def test_the_through_date_defaults_to_the_period_end(self):
        period = BillingPeriod(1, "2024-09-01", "2024-09-30")
        self.assertEqual(period.through, period.end)

    def test_work_after_the_cutoff_belongs_to_the_next_period(self):
        period = BillingPeriod(1, "2024-09-01", "2024-09-30", through="2024-09-25")
        self.assertTrue(period.contains("2024-09-28"))
        self.assertFalse(period.covers_work_on("2024-09-28"))

    def test_a_cutoff_outside_the_period_is_refused(self):
        self.assertRaises(
            PeriodError, BillingPeriod, 1, "2024-09-01", "2024-09-30", "2024-10-05"
        )

    def test_a_period_ending_before_it_starts_is_refused(self):
        self.assertRaises(PeriodError, BillingPeriod, 1, "2024-09-30", "2024-09-01")

    def test_schedules_are_gapless_and_ordered(self):
        schedule = monthly_schedule("2024-09-01", 3)
        self.assertEqual([period.number for period in schedule], [1, 2, 3])
        self.assertEqual(format_date(schedule.period(3).end), "2024-11-30")

    def test_a_schedule_with_a_hole_is_refused(self):
        first = BillingPeriod(1, "2024-09-01", "2024-09-30")
        third = BillingPeriod(3, "2024-11-01", "2024-11-30")
        self.assertRaises(PeriodError, PeriodSchedule, [first, third])

    def test_overlapping_periods_are_refused(self):
        first = BillingPeriod(1, "2024-09-01", "2024-10-05")
        second = BillingPeriod(2, "2024-10-01", "2024-10-31")
        self.assertRaises(PeriodError, PeriodSchedule, [first, second])

    def test_a_cutoff_day_is_clamped_to_short_months(self):
        schedule = monthly_schedule("2024-01-01", 2, through_day=31)
        self.assertEqual(format_date(schedule.period(2).through), "2024-02-29")

    def test_extending_a_schedule_adds_months(self):
        schedule = monthly_schedule("2024-09-01", 1).extend(2)
        self.assertEqual(len(schedule), 3)

    def test_the_period_covering_a_date_is_found(self):
        schedule = monthly_schedule("2024-09-01", 3)
        self.assertEqual(schedule.period_covering("2024-10-15").number, 2)


if __name__ == "__main__":
    unittest.main()
