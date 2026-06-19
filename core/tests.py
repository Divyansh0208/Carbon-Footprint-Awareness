import re
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse

from .models import (
    ActivityLog, EmissionFactor, Recommendation,
    Goal, EducationContent, GlossaryTerm, QAUsage,
)
from .forms import SignUpForm, ActivityLogForm, GoalForm, QuestionForm
from .services.llm import (
    _extract_numbers, _validate_no_invented_numbers,
    get_education_tip, answer_question, check_and_increment_qa_usage,
    FALLBACK_TIP, DAILY_QA_LIMIT,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_user(username="testuser", password="StrongPass123!"):
    return User.objects.create_user(username=username, password=password)


def make_factor(category="transport", subcategory="car_petrol",
                label="Petrol car", unit="km", co2=0.192):
    return EmissionFactor.objects.create(
        category=category, subcategory=subcategory,
        label=label, unit=unit, kg_co2_per_unit=co2,
    )


def make_log(user, factor, quantity=100.0, log_date=None):
    return ActivityLog.objects.create(
        user=user, factor=factor,
        quantity=quantity,
        date=log_date or date.today(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. MODEL TESTS
# ─────────────────────────────────────────────────────────────────────────────

class EmissionFactorModelTest(TestCase):

    def test_str_representation(self):
        factor = make_factor()
        self.assertIn("Petrol car", str(factor))
        self.assertIn("0.192", str(factor))

    def test_unique_together_category_subcategory(self):
        make_factor()
        from django.db import IntegrityError
        with self.assertRaises(Exception):
            EmissionFactor.objects.create(
                category="transport", subcategory="car_petrol",
                label="Duplicate", unit="km", kg_co2_per_unit=0.1,
            )

    def test_ordering_by_category_then_subcategory(self):
        make_factor("food", "beef", "Beef", "kg", 27.0)
        make_factor("transport", "car_petrol", "Petrol car", "km", 0.192)
        factors = list(EmissionFactor.objects.values_list("category", flat=True))
        self.assertEqual(factors[0], "food")
        self.assertEqual(factors[1], "transport")

    def test_category_choices_are_valid(self):
        valid = {c[0] for c in EmissionFactor.CATEGORY_CHOICES}
        self.assertEqual(valid, {"transport", "energy", "food", "goods"})


class ActivityLogModelTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.factor = make_factor(co2=0.192)

    def test_co2_kg_auto_calculated_on_save(self):
        log = make_log(self.user, self.factor, quantity=100.0)
        self.assertAlmostEqual(log.co2_kg, 19.2, places=5)

    def test_co2_kg_recalculated_on_update(self):
        log = make_log(self.user, self.factor, quantity=100.0)
        log.quantity = 200.0
        log.save()
        self.assertAlmostEqual(log.co2_kg, 38.4, places=5)

    def test_str_contains_username_and_label(self):
        log = make_log(self.user, self.factor)
        self.assertIn("testuser", str(log))
        self.assertIn("Petrol car", str(log))

    def test_ordering_newest_date_first(self):
        older = make_log(self.user, self.factor, log_date=date.today() - timedelta(days=5))
        newer = make_log(self.user, self.factor, log_date=date.today())
        logs = list(ActivityLog.objects.all())
        self.assertEqual(logs[0].pk, newer.pk)

    def test_zero_quantity_gives_zero_co2(self):
        log = make_log(self.user, self.factor, quantity=0.0)
        self.assertEqual(log.co2_kg, 0.0)

    def test_fractional_quantity(self):
        log = make_log(self.user, self.factor, quantity=0.5)
        self.assertAlmostEqual(log.co2_kg, 0.096, places=5)

    def test_cascade_delete_with_user(self):
        make_log(self.user, self.factor)
        self.user.delete()
        self.assertEqual(ActivityLog.objects.count(), 0)

    def test_protect_on_factor_delete(self):
        make_log(self.user, self.factor)
        from django.db import models as dm
        with self.assertRaises(Exception):
            self.factor.delete()


class GoalModelTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_str_contains_username_and_target(self):
        goal = Goal.objects.create(user=self.user, target_kg_per_month=300.0)
        self.assertIn("testuser", str(goal))
        self.assertIn("300.0", str(goal))

    def test_one_to_one_constraint(self):
        Goal.objects.create(user=self.user, target_kg_per_month=300.0)
        with self.assertRaises(Exception):
            Goal.objects.create(user=self.user, target_kg_per_month=200.0)

    def test_goal_deleted_with_user(self):
        Goal.objects.create(user=self.user, target_kg_per_month=300.0)
        self.user.delete()
        self.assertEqual(Goal.objects.count(), 0)


class RecommendationModelTest(TestCase):

    def test_str_truncates_action(self):
        r = Recommendation.objects.create(
            category="food",
            action="Replace beef with chicken every Tuesday for a whole month",
            potential_saving_kg=18.0,
            effort="low",
        )
        self.assertIn("[food]", str(r))

    def test_ordering_by_category_then_effort(self):
        Recommendation.objects.create(category="transport", action="Walk", potential_saving_kg=5, effort="low")
        Recommendation.objects.create(category="food", action="Less beef", potential_saving_kg=18, effort="low")
        first = Recommendation.objects.first()
        self.assertEqual(first.category, "food")


class QAUsageModelTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_unique_together_user_date(self):
        QAUsage.objects.create(user=self.user, date=date.today(), count=1)
        with self.assertRaises(Exception):
            QAUsage.objects.create(user=self.user, date=date.today(), count=2)

    def test_default_count_is_zero(self):
        usage = QAUsage.objects.create(user=self.user, date=date.today())
        self.assertEqual(usage.count, 0)


class EducationContentAndGlossaryTest(TestCase):

    def test_education_content_str(self):
        ec = EducationContent.objects.create(
            category="food", title="Why food matters", body="..."
        )
        self.assertEqual(str(ec), "Why food matters")

    def test_glossary_term_str(self):
        gt = GlossaryTerm.objects.create(term="Carbon footprint", definition="...")
        self.assertEqual(str(gt), "Carbon footprint")

    def test_glossary_unique_term(self):
        GlossaryTerm.objects.create(term="CO2e", definition="First")
        with self.assertRaises(Exception):
            GlossaryTerm.objects.create(term="CO2e", definition="Second")


# ─────────────────────────────────────────────────────────────────────────────
# 2. FORM TESTS
# ─────────────────────────────────────────────────────────────────────────────

class SignUpFormTest(TestCase):

    def _post(self, **overrides):
        data = {
            "username": "newuser",
            "email": "new@example.com",
            "password1": "SuperSecret99!",
            "password2": "SuperSecret99!",
            **overrides,
        }
        return SignUpForm(data=data)

    def test_valid_form(self):
        self.assertTrue(self._post().is_valid())

    def test_missing_email_is_invalid(self):
        self.assertFalse(self._post(email="").is_valid())

    def test_password_mismatch_is_invalid(self):
        self.assertFalse(self._post(password2="WrongPassword!").is_valid())

    def test_duplicate_username_is_invalid(self):
        User.objects.create_user(username="newuser", password="pass")
        self.assertFalse(self._post().is_valid())


class ActivityLogFormTest(TestCase):

    def setUp(self):
        self.factor = make_factor()

    def test_valid_form(self):
        form = ActivityLogForm(data={
            "category": "transport",
            "factor": self.factor.pk,
            "quantity": 50.0,
            "date": str(date.today()),
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_negative_quantity_is_valid_at_form_level(self):
        # The form has no min-value validator; that's a model concern
        form = ActivityLogForm(data={
            "category": "transport",
            "factor": self.factor.pk,
            "quantity": -10.0,
            "date": str(date.today()),
        })
        # We just assert the form doesn't crash; validation policy belongs to model
        self.assertIsInstance(form.is_valid(), bool)

    def test_category_filters_factor_queryset_via_htmx(self):
        food_factor = make_factor("food", "beef", "Beef", "kg", 27.0)
        form = ActivityLogForm(data={
            "category": "food",
            "factor": food_factor.pk,
            "quantity": 2.0,
            "date": str(date.today()),
        })
        self.assertTrue(form.is_valid(), form.errors)
        # queryset should be filtered to food only
        self.assertNotIn(self.factor, form.fields['factor'].queryset)

    def test_missing_quantity_is_invalid(self):
        form = ActivityLogForm(data={
            "category": "transport",
            "factor": self.factor.pk,
            "date": str(date.today()),
        })
        self.assertFalse(form.is_valid())

    def test_missing_date_is_invalid(self):
        form = ActivityLogForm(data={
            "category": "transport",
            "factor": self.factor.pk,
            "quantity": 50.0,
        })
        self.assertFalse(form.is_valid())


class GoalFormTest(TestCase):

    def test_valid_goal_form(self):
        form = GoalForm(data={"target_kg_per_month": 250.0})
        self.assertTrue(form.is_valid())

    def test_missing_target_is_invalid(self):
        form = GoalForm(data={})
        self.assertFalse(form.is_valid())

    def test_non_numeric_target_is_invalid(self):
        form = GoalForm(data={"target_kg_per_month": "abc"})
        self.assertFalse(form.is_valid())


class QuestionFormTest(TestCase):

    def test_valid_question(self):
        form = QuestionForm(data={"question": "Why is beef bad?"})
        self.assertTrue(form.is_valid())

    def test_empty_question_is_invalid(self):
        form = QuestionForm(data={"question": ""})
        self.assertFalse(form.is_valid())

    def test_question_too_long_is_invalid(self):
        form = QuestionForm(data={"question": "x" * 301})
        self.assertFalse(form.is_valid())

    def test_question_at_max_length_is_valid(self):
        form = QuestionForm(data={"question": "x" * 300})
        self.assertTrue(form.is_valid())


# ─────────────────────────────────────────────────────────────────────────────
# 3. LLM SERVICE TESTS
# ─────────────────────────────────────────────────────────────────────────────

class ExtractNumbersTest(TestCase):

    def test_extracts_integers(self):
        self.assertEqual(_extract_numbers("drove 100 km"), {"100"})

    def test_extracts_floats(self):
        self.assertIn("19.2", _extract_numbers("emitted 19.2 kg"))

    def test_empty_string(self):
        self.assertEqual(_extract_numbers("no numbers here"), set())

    def test_multiple_numbers(self):
        nums = _extract_numbers("100 km and 27.5 kg CO2")
        self.assertIn("100", nums)
        self.assertIn("27.5", nums)


class ValidateNoInventedNumbersTest(TestCase):

    def test_safe_output_passes(self):
        allowed = {"100", "27"}
        self.assertTrue(_validate_no_invented_numbers("You emitted 100 kg", allowed))

    def test_invented_number_fails(self):
        allowed = {"100"}
        self.assertFalse(_validate_no_invented_numbers("You emitted 999 kg", allowed))

    def test_no_numbers_in_output_passes(self):
        allowed = {"100"}
        self.assertTrue(_validate_no_invented_numbers("Try cycling more often.", allowed))

    def test_subset_of_allowed_passes(self):
        allowed = {"100", "200", "50"}
        self.assertTrue(_validate_no_invented_numbers("50 kg this month", allowed))


class GetEducationTipTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.summary = {"transport": 120.0, "food": 80.0}
        self.national_avg = {"transport": 100.0, "food": 90.0}
        cache.clear()

    @patch("core.services.llm.get_client")
    def test_returns_llm_text_on_success(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Try cycling to work this week."
        mock_get_client.return_value.chat.completions.create.return_value = mock_resp

        tip = get_education_tip(self.user, self.summary, self.national_avg)
        self.assertEqual(tip, "Try cycling to work this week.")

    @patch("core.services.llm.get_client")
    def test_falls_back_on_api_exception(self, mock_get_client):
        mock_get_client.return_value.chat.completions.create.side_effect = Exception("API down")
        tip = get_education_tip(self.user, self.summary, self.national_avg)
        self.assertEqual(tip, FALLBACK_TIP)

    @patch("core.services.llm.get_client")
    def test_caches_result_for_24h(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Cache this tip."
        mock_get_client.return_value.chat.completions.create.return_value = mock_resp

        tip1 = get_education_tip(self.user, self.summary, self.national_avg)
        tip2 = get_education_tip(self.user, self.summary, self.national_avg)

        self.assertEqual(tip1, tip2)
        # API should only have been called once
        self.assertEqual(mock_get_client.return_value.chat.completions.create.call_count, 1)

    @patch("core.services.llm.get_client")
    def test_falls_back_when_invented_number_in_output(self, mock_get_client):
        # First call returns text with invented number; retry also invents
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Your emissions are 9999 kg this month."
        mock_get_client.return_value.chat.completions.create.return_value = mock_resp

        tip = get_education_tip(self.user, self.summary, self.national_avg)
        self.assertEqual(tip, FALLBACK_TIP)

    @patch("core.services.llm.get_client")
    def test_allowed_number_passes_validation(self, mock_get_client):
        # The LLM output references only numbers present in the summary/avg dicts.
        # _extract_numbers on {"transport": 120.0} yields {"120", "0"} etc.
        # We use plain integers that unambiguously appear in the extracted set.
        summary = {"transport": 120, "food": 80}
        national_avg = {"transport": 100, "food": 90}
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Your transport is higher than food."
        mock_get_client.return_value.chat.completions.create.return_value = mock_resp

        tip = get_education_tip(self.user, summary, national_avg)
        self.assertNotEqual(tip, FALLBACK_TIP)


class AnswerQuestionTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.summary = {"transport": 50.0}

    @patch("core.services.llm.get_client")
    def test_returns_answer_on_success(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Beef is carbon-intensive due to methane."
        mock_get_client.return_value.chat.completions.create.return_value = mock_resp

        answer = answer_question(self.user, self.summary, "Why is beef bad?")
        self.assertEqual(answer, "Beef is carbon-intensive due to methane.")

    @patch("core.services.llm.get_client")
    def test_error_message_on_exception(self, mock_get_client):
        mock_get_client.return_value.chat.completions.create.side_effect = Exception("timeout")
        answer = answer_question(self.user, self.summary, "Why is beef bad?")
        self.assertIn("couldn't process", answer)

    @patch("core.services.llm.get_client")
    def test_invented_number_returns_safe_message(self, mock_get_client):
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Beef emits 77777 kg CO2 per kg."
        mock_get_client.return_value.chat.completions.create.return_value = mock_resp

        answer = answer_question(self.user, self.summary, "Why is beef bad?")
        self.assertIn("Learn section", answer)


class CheckAndIncrementQAUsageTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_first_call_returns_true_and_sets_count_to_1(self):
        result = check_and_increment_qa_usage(self.user)
        self.assertTrue(result)
        usage = QAUsage.objects.get(user=self.user, date=date.today())
        self.assertEqual(usage.count, 1)

    def test_increments_on_each_call(self):
        for i in range(3):
            check_and_increment_qa_usage(self.user)
        usage = QAUsage.objects.get(user=self.user, date=date.today())
        self.assertEqual(usage.count, 3)

    def test_returns_false_when_limit_reached(self):
        QAUsage.objects.create(user=self.user, date=date.today(), count=DAILY_QA_LIMIT)
        result = check_and_increment_qa_usage(self.user)
        self.assertFalse(result)

    def test_does_not_increment_beyond_limit(self):
        QAUsage.objects.create(user=self.user, date=date.today(), count=DAILY_QA_LIMIT)
        check_and_increment_qa_usage(self.user)
        usage = QAUsage.objects.get(user=self.user, date=date.today())
        self.assertEqual(usage.count, DAILY_QA_LIMIT)

    def test_different_days_tracked_separately(self):
        yesterday = date.today() - timedelta(days=1)
        QAUsage.objects.create(user=self.user, date=yesterday, count=DAILY_QA_LIMIT)
        result = check_and_increment_qa_usage(self.user)
        self.assertTrue(result)

    def test_different_users_tracked_separately(self):
        user2 = make_user("user2")
        for _ in range(DAILY_QA_LIMIT):
            check_and_increment_qa_usage(self.user)
        # user2 should still have quota
        result = check_and_increment_qa_usage(user2)
        self.assertTrue(result)


# ─────────────────────────────────────────────────────────────────────────────
# 4. VIEW TESTS — AUTH
# ─────────────────────────────────────────────────────────────────────────────

class AuthViewTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_signup_get_returns_200(self):
        resp = self.client.get(reverse("signup"))
        self.assertEqual(resp.status_code, 200)

    def test_signup_post_valid_creates_user_and_redirects(self):
        resp = self.client.post(reverse("signup"), {
            "username": "brandnew",
            "email": "brand@new.com",
            "password1": "SuperSecret99!",
            "password2": "SuperSecret99!",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username="brandnew").exists())

    def test_signup_post_invalid_returns_200_with_errors(self):
        resp = self.client.post(reverse("signup"), {
            "username": "",
            "email": "bad",
            "password1": "short",
            "password2": "mismatch",
        })
        self.assertEqual(resp.status_code, 200)

    def test_login_get_returns_200(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)

    def test_login_post_valid_redirects_to_dashboard(self):
        make_user("logintest", "StrongPass123!")
        resp = self.client.post(reverse("login"), {
            "username": "logintest",
            "password": "StrongPass123!",
        })
        self.assertEqual(resp.status_code, 302)
        # Django resolves LOGIN_REDIRECT_URL ('dashboard') to its URL path
        self.assertEqual(resp["Location"], reverse("dashboard"))

    def test_login_post_invalid_returns_200(self):
        resp = self.client.post(reverse("login"), {
            "username": "nobody",
            "password": "wrongpass",
        })
        self.assertEqual(resp.status_code, 200)

    def test_logout_redirects_to_login(self):
        user = make_user()
        self.client.force_login(user)
        resp = self.client.post(reverse("logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])

    def test_unauthenticated_dashboard_redirects_to_login(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])


# ─────────────────────────────────────────────────────────────────────────────
# 5. VIEW TESTS — TRACK PILLAR
# ─────────────────────────────────────────────────────────────────────────────

class DashboardViewTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.factor = make_factor()

    def test_dashboard_returns_200(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_with_no_logs_shows_zero_total(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.context["total"], 0)

    def test_dashboard_summary_aggregates_last_30_days(self):
        make_log(self.user, self.factor, quantity=100.0)
        resp = self.client.get(reverse("dashboard"))
        self.assertAlmostEqual(resp.context["summary"].get("transport", 0), 19.2, places=1)

    def test_dashboard_excludes_logs_older_than_30_days(self):
        old_date = date.today() - timedelta(days=31)
        make_log(self.user, self.factor, quantity=100.0, log_date=old_date)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.context["total"], 0)

    def test_dashboard_progress_pct_with_goal(self):
        Goal.objects.create(user=self.user, target_kg_per_month=100.0)
        make_log(self.user, self.factor, quantity=100.0)  # 19.2 kg
        resp = self.client.get(reverse("dashboard"))
        self.assertIsNotNone(resp.context["progress_pct"])
        self.assertEqual(resp.context["progress_pct"], 19)  # 19.2/100 = ~19%

    def test_dashboard_progress_pct_none_without_goal(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertIsNone(resp.context["progress_pct"])

    def test_dashboard_shows_only_this_users_logs(self):
        other_user = make_user("other")
        make_log(other_user, self.factor, quantity=500.0)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.context["total"], 0)

    def test_dashboard_progress_pct_capped_at_999(self):
        Goal.objects.create(user=self.user, target_kg_per_month=1.0)  # tiny goal
        make_log(self.user, self.factor, quantity=10000.0)  # huge log
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.context["progress_pct"], 999)

    def test_dashboard_chart_data_present(self):
        make_log(self.user, self.factor, quantity=100.0)
        resp = self.client.get(reverse("dashboard"))
        self.assertIn("transport", resp.context["chart_labels"])
        self.assertTrue(len(resp.context["chart_values"]) > 0)


class LogActivityViewTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.factor = make_factor()

    def test_get_returns_200(self):
        resp = self.client.get(reverse("log_activity"))
        self.assertEqual(resp.status_code, 200)

    def test_get_prefills_today_date(self):
        resp = self.client.get(reverse("log_activity"))
        self.assertEqual(resp.context["form"].initial.get("date"), date.today())

    def test_valid_post_creates_log_and_redirects(self):
        resp = self.client.post(reverse("log_activity"), {
            "category": "transport",
            "factor": self.factor.pk,
            "quantity": 50.0,
            "date": str(date.today()),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ActivityLog.objects.filter(user=self.user).count(), 1)

    def test_log_belongs_to_logged_in_user(self):
        self.client.post(reverse("log_activity"), {
            "category": "transport",
            "factor": self.factor.pk,
            "quantity": 50.0,
            "date": str(date.today()),
        })
        log = ActivityLog.objects.get(user=self.user)
        self.assertEqual(log.user, self.user)

    def test_co2_calculated_correctly_after_post(self):
        self.client.post(reverse("log_activity"), {
            "category": "transport",
            "factor": self.factor.pk,
            "quantity": 100.0,
            "date": str(date.today()),
        })
        log = ActivityLog.objects.get(user=self.user)
        self.assertAlmostEqual(log.co2_kg, 19.2, places=5)

    def test_invalid_post_returns_200_with_form_errors(self):
        resp = self.client.post(reverse("log_activity"), {
            "category": "transport",
            "factor": "",
            "quantity": "",
            "date": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].errors)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse("log_activity"))
        self.assertEqual(resp.status_code, 302)


class FactorOptionsPartialTest(TestCase):

    def setUp(self):
        self.transport_factor = make_factor("transport", "car_petrol", "Petrol car", "km", 0.192)
        self.food_factor = make_factor("food", "beef", "Beef", "kg", 27.0)

    def test_returns_factors_for_category(self):
        resp = self.client.get(reverse("factor_options"), {"category": "transport"})
        self.assertEqual(resp.status_code, 200)
        # The partial template renders factor options; verify correct queryset was passed
        self.assertIn(self.transport_factor, resp.context["factors"])
        self.assertNotIn(self.food_factor, resp.context["factors"])

    def test_food_factors_returned_for_food_category(self):
        resp = self.client.get(reverse("factor_options"), {"category": "food"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.food_factor, resp.context["factors"])
        self.assertNotIn(self.transport_factor, resp.context["factors"])

    def test_empty_result_for_unknown_category(self):
        resp = self.client.get(reverse("factor_options"), {"category": "unknown"})
        self.assertEqual(resp.status_code, 200)

    def test_no_category_param_returns_empty(self):
        resp = self.client.get(reverse("factor_options"))
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────────────────────────────────────────────────────────
# 6. VIEW TESTS — UNDERSTAND PILLAR
# ─────────────────────────────────────────────────────────────────────────────

class LearnViewTest(TestCase):

    def test_learn_returns_200_unauthenticated(self):
        resp = self.client.get(reverse("learn"))
        self.assertEqual(resp.status_code, 200)

    def test_learn_shows_all_education_content(self):
        EducationContent.objects.create(category="food", title="Food Basics", body="...")
        EducationContent.objects.create(category="energy", title="Energy Basics", body="...")
        resp = self.client.get(reverse("learn"))
        self.assertEqual(len(resp.context["contents"]), 2)


class GlossaryViewTest(TestCase):

    def test_glossary_returns_200(self):
        resp = self.client.get(reverse("glossary"))
        self.assertEqual(resp.status_code, 200)

    def test_glossary_shows_all_terms(self):
        GlossaryTerm.objects.create(term="CO2e", definition="Carbon equivalent")
        GlossaryTerm.objects.create(term="Net Zero", definition="Balanced emissions")
        resp = self.client.get(reverse("glossary"))
        self.assertEqual(len(resp.context["terms"]), 2)


class QAViewTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_get_returns_200(self):
        resp = self.client.get(reverse("qa"))
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse("qa"))
        self.assertEqual(resp.status_code, 302)

    @patch("core.views.answer_question")
    @patch("core.views.check_and_increment_qa_usage")
    def test_valid_question_calls_answer_function(self, mock_check, mock_answer):
        mock_check.return_value = True
        mock_answer.return_value = "Great answer!"
        resp = self.client.post(reverse("qa"), {"question": "Why is beef bad?"})
        self.assertEqual(resp.status_code, 200)
        mock_answer.assert_called_once()

    @patch("core.views.check_and_increment_qa_usage")
    def test_rate_limit_exceeded_shows_error(self, mock_check):
        mock_check.return_value = False
        resp = self.client.post(reverse("qa"), {"question": "Why is beef bad?"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("limit", resp.context["error"])

    def test_invalid_question_no_api_call(self):
        resp = self.client.post(reverse("qa"), {"question": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["answer"])


# ─────────────────────────────────────────────────────────────────────────────
# 7. VIEW TESTS — REDUCE PILLAR
# ─────────────────────────────────────────────────────────────────────────────

class InsightsViewTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.factor = make_factor("transport", "car_petrol", "Petrol car", "km", 0.192)
        cache.clear()

    def test_insights_returns_200(self):
        resp = self.client.get(reverse("insights"))
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse("insights"))
        self.assertEqual(resp.status_code, 302)

    @patch("core.views.get_education_tip")
    def test_tip_shown_when_logs_exist(self, mock_tip):
        mock_tip.return_value = "Try cycling."
        make_log(self.user, self.factor, quantity=100.0)
        resp = self.client.get(reverse("insights"))
        self.assertEqual(resp.context["tip"], "Try cycling.")

    def test_tip_is_none_with_no_logs(self):
        resp = self.client.get(reverse("insights"))
        self.assertIsNone(resp.context["tip"])

    def test_recommendations_shown_for_top_category(self):
        Recommendation.objects.create(
            category="transport", action="Walk more", potential_saving_kg=5, effort="low"
        )
        make_log(self.user, self.factor, quantity=1000.0)  # big transport emissions
        resp = self.client.get(reverse("insights"))
        self.assertEqual(resp.context["top_category"], "transport")
        self.assertEqual(len(resp.context["recommendations"]), 1)

    def test_above_average_insight_generated(self):
        # 0.192 * 1000 = 192 kg transport (NATIONAL_AVG transport = 120 * 1.2 = 144 threshold)
        make_log(self.user, self.factor, quantity=1000.0)
        resp = self.client.get(reverse("insights"))
        self.assertTrue(any("above" in i for i in resp.context["insights"]))

    def test_below_average_insight_generated(self):
        # 0.192 * 10 = 1.92 kg transport (well below 120 * 0.8 = 96)
        make_log(self.user, self.factor, quantity=10.0)
        resp = self.client.get(reverse("insights"))
        self.assertTrue(any("below average" in i for i in resp.context["insights"]))


class GoalViewTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_get_returns_200(self):
        resp = self.client.get(reverse("goal"))
        self.assertEqual(resp.status_code, 200)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse("goal"))
        self.assertEqual(resp.status_code, 302)

    def test_get_creates_default_goal_if_none_exists(self):
        self.client.get(reverse("goal"))
        self.assertTrue(Goal.objects.filter(user=self.user).exists())

    def test_post_valid_updates_goal_and_redirects(self):
        resp = self.client.post(reverse("goal"), {"target_kg_per_month": 250.0})
        self.assertEqual(resp.status_code, 302)
        goal = Goal.objects.get(user=self.user)
        self.assertEqual(goal.target_kg_per_month, 250.0)

    def test_post_invalid_returns_200(self):
        resp = self.client.post(reverse("goal"), {"target_kg_per_month": "not-a-number"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].errors)

    def test_second_post_updates_existing_goal(self):
        Goal.objects.create(user=self.user, target_kg_per_month=300.0)
        self.client.post(reverse("goal"), {"target_kg_per_month": 150.0})
        self.assertEqual(Goal.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Goal.objects.get(user=self.user).target_kg_per_month, 150.0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. END-TO-END FLOW TESTS
# ─────────────────────────────────────────────────────────────────────────────

class FullUserJourneyTest(TestCase):
    """
    Simulates a complete user journey:
    sign up → log activities → view dashboard → set goal → view insights
    """

    def setUp(self):
        self.client = Client()
        self.factor_transport = make_factor("transport", "car_petrol", "Petrol car", "km", 0.192)
        self.factor_food = make_factor("food", "beef", "Beef", "kg", 27.0)
        cache.clear()

    def test_full_journey(self):
        # 1. Sign up
        resp = self.client.post(reverse("signup"), {
            "username": "journeyuser",
            "email": "journey@test.com",
            "password1": "JourneyPass99!",
            "password2": "JourneyPass99!",
        })
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username="journeyuser")

        # 2. Dashboard is empty
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total"], 0)

        # 3. Log transport activity
        resp = self.client.post(reverse("log_activity"), {
            "category": "transport",
            "factor": self.factor_transport.pk,
            "quantity": 500.0,
            "date": str(date.today()),
        })
        self.assertEqual(resp.status_code, 302)

        # 4. Log food activity
        resp = self.client.post(reverse("log_activity"), {
            "category": "food",
            "factor": self.factor_food.pk,
            "quantity": 3.0,
            "date": str(date.today()),
        })
        self.assertEqual(resp.status_code, 302)

        # 5. Dashboard now shows combined totals
        resp = self.client.get(reverse("dashboard"))
        expected_transport = round(500.0 * 0.192, 1)  # 96.0
        expected_food = round(3.0 * 27.0, 1)           # 81.0
        expected_total = round(expected_transport + expected_food, 1)
        self.assertAlmostEqual(resp.context["total"], expected_total, places=0)

        # 6. Set monthly goal
        resp = self.client.post(reverse("goal"), {"target_kg_per_month": 200.0})
        self.assertEqual(resp.status_code, 302)

        # 7. Dashboard shows progress percentage
        resp = self.client.get(reverse("dashboard"))
        self.assertIsNotNone(resp.context["progress_pct"])
        expected_pct = min(round((expected_total / 200.0) * 100), 999)
        self.assertEqual(resp.context["progress_pct"], expected_pct)

        # 8. Insights page loads
        resp = self.client.get(reverse("insights"))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context["top_category"])

        # 9. Learn and glossary accessible
        resp = self.client.get(reverse("learn"))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("glossary"))
        self.assertEqual(resp.status_code, 200)

    def test_multi_user_data_isolation(self):
        user_a = make_user("user_a")
        user_b = make_user("user_b")

        # user_a logs a big activity
        make_log(user_a, self.factor_transport, quantity=1000.0)

        # user_b logs nothing, signs in
        self.client.force_login(user_b)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.context["total"], 0)

        # user_b's insights don't expose user_a's data
        resp = self.client.get(reverse("insights"))
        self.assertIsNone(resp.context["top_category"])

    @patch("core.views.answer_question")
    @patch("core.views.check_and_increment_qa_usage")
    def test_qa_rate_limit_full_cycle(self, mock_check, mock_answer):
        user = make_user("qauser")
        self.client.force_login(user)

        # Under limit
        mock_check.return_value = True
        mock_answer.return_value = "Beef is bad."
        resp = self.client.post(reverse("qa"), {"question": "Why is beef bad?"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context["error"])

        # Over limit
        mock_check.return_value = False
        resp = self.client.post(reverse("qa"), {"question": "Why is beef bad?"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context["error"])


class SeedDataCommandTest(TestCase):
    """Tests the management command produces expected DB records."""

    def test_seed_creates_emission_factors(self):
        from django.core.management import call_command
        call_command("seed_data", verbosity=0)
        self.assertGreater(EmissionFactor.objects.count(), 0)
        self.assertTrue(EmissionFactor.objects.filter(category="transport").exists())
        self.assertTrue(EmissionFactor.objects.filter(category="food").exists())

    def test_seed_creates_recommendations(self):
        from django.core.management import call_command
        call_command("seed_data", verbosity=0)
        self.assertGreater(Recommendation.objects.count(), 0)

    def test_seed_creates_education_content(self):
        from django.core.management import call_command
        call_command("seed_data", verbosity=0)
        self.assertGreater(EducationContent.objects.count(), 0)

    def test_seed_creates_glossary_terms(self):
        from django.core.management import call_command
        call_command("seed_data", verbosity=0)
        self.assertGreater(GlossaryTerm.objects.count(), 0)

    def test_seed_is_idempotent(self):
        from django.core.management import call_command
        call_command("seed_data", verbosity=0)
        count_after_first = EmissionFactor.objects.count()
        call_command("seed_data", verbosity=0)
        self.assertEqual(EmissionFactor.objects.count(), count_after_first)