"""
Tests for the QnA application.

These tests ensure correctness of:
- Model behaviors (string representations, computed properties like vote counts).
- View behaviors (filtering, permissions, redirects).
- Form handling (validation, saving, and error cases).

Each test is written to be understandable by someone unfamiliar with the project,
focusing on describing *why* the behavior matters.
"""

import datetime
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import Tag, Question, QuestionVote, Answer, AnswerVote, View
from .forms import QuestionForm, AnswerForm

# ---------------------------
# Test Helpers (merged + improved)
# ---------------------------

def _assert_redirects_anonymous_user_to_login(obj, url):
    obj.client.logout()
    response = obj.client.get(url)
    login_url = reverse("accounts:login", query={"next": url})
    obj.assertRedirects(response, login_url)

def _assert_successful_get_request(obj, url, query_params=None):
    """Utility: Send a GET request and assert a 200 OK response."""
    response = obj.client.get(url, query_params=query_params)
    obj.assertEqual(response.status_code, 200)
    return response

def _asserts_404_for_invalid_id(obj, view, method="GET", data=None):
    """Assert that accessing a nonexistent ID returns 404."""
    requested_url = reverse(view, args=[999])  # deliberately invalid pk
    response = obj.client.get(requested_url) if method.lower() == "get" else obj.client.post(requested_url, data=data)
    obj.assertEqual(response.status_code, 404)

def _assert_non_author_cannot_modify_content(obj, view, content_factory, *factory_args):
    """Assert that non-authors cannot edit/delete another user's content."""
    author = user_factory(username="author")
    content = content_factory(author, *factory_args)
    response = obj.client.get(reverse(view, args=[content.pk]))
    obj.assertEqual(response.status_code, 404)

# Factories: support single or multiple via `num` to match both file styles.
def user_factory(num=1, username="test_user"):
    user_model = get_user_model()
    if num > 1:
        users = [user_model(username=f"{username}-{i}") for i in range(num)]
        return user_model.objects.bulk_create(users)
    return user_model.objects.create(username=username, password="password")

def question_factory(user, num=1):
    if num > 1:
        questions = [Question(author=user, title=f"q-{i}", body="body") for i in range(num)]
        return tuple(Question.objects.bulk_create(questions))
    return Question.objects.create(author=user, title="test_question", body="test_body")

def answer_factory(user, question):
    return Answer.objects.create(author=user, question=question, text="test_answer")

def tag_factory(num=1):
    if num > 1:
        tags = [Tag(text=f"tag-{i}") for i in range(num)]
        return tuple(Tag.objects.bulk_create(tags))
    return Tag.objects.create(text="test_tag")

def view_factory(user, question, num=1):
    if num > 1:
        views = [View(user=user, question=question) for _ in range(num)]
        return View.objects.bulk_create(views)
    return View.objects.create(user=user, question=question)

# ---------------------------
# Model Tests
# ---------------------------

class QuestionModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()

    def test_is_edited_exact_and_small_diff(self):
        """Cover: exact same timestamps & sub-second differences (should be False)."""
        with self.subTest("Exact same timestamps"):
            q = Question(pub_date=self.now, mod_date=self.now)
            self.assertIs(q.is_edited, False)

        with self.subTest("Difference less than 1 second"):
            q = Question(pub_date=self.now - datetime.timedelta(microseconds=999_999), mod_date=self.now)
            self.assertIs(q.is_edited, False)

    def test_is_edited_with_actual_edit(self):
        """is_edited should be True when mod_date >= 1 second later than pub_date."""
        q = Question(pub_date=self.now - datetime.timedelta(minutes=10), mod_date=self.now)
        self.assertIs(q.is_edited, True)


class AnswerModelTests(TestCase):
    def test_str_trimming_and_whitespace(self):
        """__str__ should clean whitespace and join lines."""
        text = "  Short answer.  \nWith newline.  "
        answer = Answer(text=text)
        self.assertEqual(str(answer), "Short answer. With newline.")

    def test_str_truncation_and_blank_line_removal(self):
        """
        For long text, accept either of the two truncation styles used in the sources:
        - ends with '.'  OR
        - ends with '...'
        This keeps the merged suite tolerant to minor differences between the versions.
        """
        text = "line1\n" + "a" * 250
        answer = Answer(text=text)
        expected_prefix = ("line1 " + "a" * 250)[:200]
        out = str(answer)
        self.assertTrue(out.startswith(expected_prefix))
        self.assertTrue(out.endswith("..."))

        # blank/whitespace-only lines are removed when joining
        answer2 = Answer(text="Line1\n\n \nLine2")
        self.assertEqual(str(answer2), "Line1 Line2")


class VoteCountTests(TestCase):
    """Unified vote-count tests that cover both question and answer vote logic."""

    @classmethod
    def setUpTestData(cls):
        cls.author = user_factory()
        cls.question = question_factory(cls.author)
        cls.answer = answer_factory(cls.author, cls.question)

    def _assert_vote_count_without_votes_for(self, content):
        self.assertEqual(content.vote_count, 0)

    def _assert_vote_count_with_votes_for(self, content, vote_model, fk_field_name, vote_values=(1, -1, 1, 1, -1)):
        """
        Ensure net vote count equals sum(vote_values). Creates users and bulk-creates votes.
        Vote_values default chosen to match coverage in one source; parameterized so tests can be extended.
        """
        num = len(vote_values)
        users = user_factory(num=num)
        # when user_factory returns a list/tuple, use it; otherwise wrap single in list
        if not isinstance(users, (list, tuple)):
            users = [users]

        votes = [
            vote_model(user=user, value=value, **{fk_field_name: content})
            for user, value in zip(users, vote_values)
        ]
        vote_model.objects.bulk_create(votes)
        self.assertEqual(content.vote_count, sum(vote_values))

    def test_vote_count_for_questions(self):
        self._assert_vote_count_without_votes_for(self.question)
        self._assert_vote_count_with_votes_for(self.question, QuestionVote, "question")

    def test_vote_count_for_answers(self):
        self._assert_vote_count_without_votes_for(self.answer)
        self._assert_vote_count_with_votes_for(self.answer, AnswerVote, "answer")


class ViewModelTests(TestCase):
    def test_hrs_since_viewed(self):
        """hrs_since_viewed returns elapsed hours (rounded to 2 decimals)."""
        view = View(view_time=(timezone.now() - datetime.timedelta(hours=3)))
        self.assertAlmostEqual(view.hrs_since_viewed, 3, places=2)

# ---------------------------
# View Tests: Listing Questions
# ---------------------------

class QuestionListViewsTests(TestCase):
    """
    Tests for question listing, filters (Newest, Unanswered, Popular),
    and handling empty results. Uses flexible helpers borrowed from both sources.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tag = tag_factory()
        cls.questions_url = reverse("qnas:questions")
        cls.tagged_questions_url = reverse("qnas:tagged-questions", args=(1,))

    def _assert_no_question_for(self, url):
        Question.objects.all().delete()
        response = _assert_successful_get_request(self, url)
        self.assertContains(response, "0 questions")

    def _assert_default_filter_for(self, url, tagged=False):
        """Ensure 'Newest' is default when tab is missing or invalid."""
        questions = question_factory(self.user, 3)
        if tagged:
            # if tag is a Tag instance, add the returned questions to it
            self.tag.questions.add(*questions)
        def _assert_newest(query_params=None):
            response = _assert_successful_get_request(self, url, query_params=query_params)
            self.assertEqual(response.context["tab"].lower(), "newest")
            self.assertQuerySetEqual(response.context["all_questions"], reversed(questions))
        with self.subTest("No tab selected"):
            _assert_newest()
        with self.subTest("Invalid tab selected"):
            _assert_newest({"tab": "invalid"})

    def _assert_defined_tabs_for(self, url, tagged=False):
        """'Unanswered' shows only unanswered; 'Popular' sorts by view count."""
        q1, q2, q3 = question_factory(self.user, 3)
        if tagged:
            self.tag.questions.add(q1, q2, q3)

        with self.subTest("Unanswered tab"):
            q3.answers.create(author=self.user)
            response = _assert_successful_get_request(self, url, query_params={"tab": "Unanswered"})
            self.assertEqual(list(response.context["all_questions"]), [q2, q1])

        with self.subTest("Popular tab"):
            # create views so q3 has highest, then q1
            view_factory(user=self.user, question=q3, num=2)
            view_factory(user=self.user, question=q1)
            response = _assert_successful_get_request(self, url, query_params={"tab": "Popular"})
            self.assertEqual(list(response.context["all_questions"]), [q3, q1, q2])

    # Individual tests (combined from both files)
    def test_tagged_questions_invalid_tag_returns_404(self):
        _asserts_404_for_invalid_id(self, "qnas:tagged-questions")

    def test_no_question_for_tagged_questions(self):
        self._assert_no_question_for(self.tagged_questions_url)

    def test_no_question_for_questions(self):
        self._assert_no_question_for(self.questions_url)

    def test_default_filter_for_questions(self):
        self._assert_default_filter_for(self.questions_url)

    def test_default_filter_for_tagged_questions(self):
        self._assert_default_filter_for(self.tagged_questions_url, True)

    def test_defined_tabs_for_questions(self):
        self._assert_defined_tabs_for(self.questions_url)

    def test_defined_tabs_for_tagged_questions(self):
        self._assert_defined_tabs_for(self.tagged_questions_url, True)

# ---------------------------
# View Tests: Listing Tags
# ---------------------------

class TagViewTests(TestCase):
    """Tag listing tabs: Popular, New, Name."""

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tags_url = reverse("qnas:tags")

    def test_default_tab_filter(self):
        """Default tab should be 'popular' when missing or invalid."""
        def _assert_popular(query_params=None):
            response = _assert_successful_get_request(self, self.tags_url, query_params=query_params)
            self.assertEqual(response.context["tab"].lower(), "popular")
        with self.subTest("No tab selected"):
            _assert_popular()
        with self.subTest("Invalid tab selected"):
            _assert_popular({"tab": "nonsense"})

    def test_defined_tabs(self):
        """Popular sorts by usage, New by recency, Name alphabetically."""
        t1, t2, t3 = Tag.objects.bulk_create([Tag(text=str(i)) for i in range(3)])
        q1, q2 = question_factory(self.user, 2)
        t2.questions.add(q1, q2); t3.questions.add(q1)

        def _assert_tab(tab):
            response = _assert_successful_get_request(self, self.tags_url, query_params={"tab": tab})
            self.assertEqual(response.context["tab"].lower(), tab.lower())
            return response

        with self.subTest("Popular tab"):
            self.assertQuerySetEqual(_assert_tab("Popular").context["all_tags"], (t2, t3, t1))

        with self.subTest("New tab"):
            self.assertQuerySetEqual(_assert_tab("New").context["all_tags"], (t3, t2, t1))

        with self.subTest("Name tab"):
            self.assertQuerySetEqual(_assert_tab("Name").context["all_tags"], (t1, t2, t3))

# ---------------------------
# View Tests: Creating & Editing Questions
# ---------------------------

class QuestionCreateEditTests(TestCase):
    """
    Tests for creating & editing questions:
    - Permissions (anonymous redirect).
    - Form rendering on GET.
    - Invalid POST behaviors (missing fields, invalid tags, title too long).
    - Successful POST behaviors (create or update and redirect).
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tag = tag_factory()
        cls.ask_url = reverse("qnas:ask")
        cls.edit_question_url = reverse("qnas:edit-question", args=(1,))

    def setUp(self):
        self.client.force_login(self.user)

    def _assert_returns_form(self, response, empty_form=True):
        """Helper: verify form type + whether it’s empty or pre-populated."""
        self.assertEqual(response.status_code, 200)
        form = response.context.get("form")
        self.assertIsInstance(form, QuestionForm)
        if empty_form:
            self.assertIsNone(form.instance.pk)
        else:
            self.assertEqual(form.instance.pk, 1)

    def _assert_re_renders_form_on_invalid_submission(self, url, question_for_edit=None):
        """Invalid POST should re-render form and not persist changes."""
        with self.subTest("Missing required field"):
            response = self.client.post(url, {"title": "a", "body": "b"})
            self._assert_returns_form(response, not question_for_edit)
            self.assertFalse(Question.objects.filter(title="a", body="b").exists())

        with self.subTest("Invalid tag id"):
            response = self.client.post(url, {"title": "a", "body": "b", "tags": [999]})
            self._assert_returns_form(response, not question_for_edit)
            self.assertFalse(Question.objects.filter(title="a", body="b").exists())

        with self.subTest("Title too long"):
            long_title = "x" * 201
            response = self.client.post(url, {"title": long_title, "body": "b", "tags": [self.tag.pk]})
            self._assert_returns_form(response, not question_for_edit)
            self.assertFalse(Question.objects.filter(title=long_title, body="b").exists())

    def _assert_valid_submission_creates_or_updates(self, url):
        """Valid POST should create/edit question then redirect to detail page."""
        response = self.client.post(url, {"title": "title", "body": "body", "tags": (1,)})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Question.objects.filter(title="title", body="body").exists())
        self.assertRedirects(response, reverse("qnas:detail", args=(1,)))

    # Permission tests
    def test_ask_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, self.ask_url)

    def test_edit_question_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, self.edit_question_url)

    def test_edit_question_with_nonexistent_question(self):
        _asserts_404_for_invalid_id(self, "qnas:edit-question")

    def test_non_author_cannot_edit_question(self):
        _assert_non_author_cannot_modify_content(self, "qnas:edit-question", question_factory)

    # GET form rendering
    def test_ask_displays_empty_form_on_get(self):
        response = self.client.get(self.ask_url)
        self._assert_returns_form(response, True)

    def test_edit_question_displays_prepopulated_form_on_get(self):
        question_factory(self.user)
        response = self.client.get(self.edit_question_url)
        self._assert_returns_form(response, False)

    # Invalid submissions
    def test_ask_invalid_submission(self):
        self._assert_re_renders_form_on_invalid_submission(self.ask_url)

    def test_edit_question_invalid_submission(self):
        q = question_factory(self.user)
        self._assert_re_renders_form_on_invalid_submission(self.edit_question_url, question_for_edit=q)

    # Valid submissions
    def test_ask_valid_submission(self):
        self._assert_valid_submission_creates_or_updates(self.ask_url)

    def test_edit_question_valid_submission(self):
        question_factory(self.user)
        self._assert_valid_submission_creates_or_updates(self.edit_question_url)

# ---------------------------
# View Tests: Editing Answers
# ---------------------------

class EditAnswerViewTests(TestCase):
    """
    Tests for editing answers:
    - Permissions, form rendering, invalid & valid POST behavior.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.question = question_factory(cls.user)
        cls.edit_answer_url = reverse("qnas:edit-answer", args=(1,))

    def setUp(self):
        self.client.force_login(self.user)

    def _assert_returns_prepopulated_form(self, response):
        """Helper: verify form type + pre-populated for editing an answer."""
        self.assertEqual(response.status_code, 200)
        form = response.context.get("form")
        self.assertIsInstance(form, AnswerForm)
        self.assertEqual(form.instance.pk, 1)

    def test_edit_answer_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, self.edit_answer_url)

    def test_edit_answer_with_nonexistent_answer(self):
        _asserts_404_for_invalid_id(self, "qnas:edit-answer")

    def test_non_author_cannot_edit_answer(self):
        _assert_non_author_cannot_modify_content(self, "qnas:edit-answer", answer_factory, self.question)

    def test_edit_answer_displays_prepopulated_form_on_get(self):
        answer_factory(self.user, self.question)
        response = self.client.get(self.edit_answer_url)
        self._assert_returns_prepopulated_form(response)

    def test_edit_answer_invalid_submission_empty_text(self):
        answer = answer_factory(self.user, self.question)
        response = self.client.post(self.edit_answer_url, {"text": ""})
        answer.refresh_from_db()
        self._assert_returns_prepopulated_form(response)
        # Should not overwrite existing text with empty string
        self.assertEqual(answer.text, "test_answer")

    def test_edit_answer_valid_submission_updates_answer(self):
        answer_factory(self.user, self.question)
        response = self.client.post(self.edit_answer_url, {"text": "Text, text, text."})
        self.assertFalse(Answer.objects.filter(text="test_answer").exists())
        self.assertTrue(Answer.objects.filter(text="Text, text, text.").exists())
        self.assertRedirects(response, reverse("qnas:detail", args=(1,)))

# ---------------------------
# View Tests: Deleting Questions and Answer
# ---------------------------

class DeleteViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()

        cls.question = question_factory(cls.user)
        cls.answer = answer_factory(cls.user, cls.question)

        cls.del_question_url = reverse("qnas:delete-question", args=[cls.question.id])
        cls.del_answer_url = reverse("qnas:delete-answer", args=[cls.answer.id])

        cls.default_question_redirect = reverse("qnas:questions")
        cls.default_answer_redirect = reverse("qnas:detail", args=[cls.question.id])

    def setUp(self):
        self.client.force_login(self.user)

    # --- Auth redirects ---
    def test_question_delete_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, self.del_question_url)

    def test_answer_delete_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, self.del_answer_url)

    # --- Nonexistent / non-author ---
    def test_non_author_cannot_delete_question(self):
        _assert_non_author_cannot_modify_content(self, "qnas:delete-question", question_factory)

    def test_non_author_cannot_delete_answer(self):
        _assert_non_author_cannot_modify_content(self, "qnas:delete-answer", answer_factory, self.question)

    # --- Deletion removes objects ---
    def test_deletes_question(self):
        self.client.post(self.del_question_url)
        self.assertFalse(Question.objects.filter(id=self.question.id).exists())

    def test_deletes_answer(self):
        self.client.post(self.del_answer_url)
        self.assertFalse(Answer.objects.filter(id=self.answer.id).exists())

    # --- Redirect behaviour ---
    def test_question_redirects_to_default_if_no_previous(self):
        response = self.client.post(self.del_question_url)
        self.assertRedirects(response, self.default_question_redirect)

    def test_question_redirects_to_default_if_invalid_previous(self):
        invalid = reverse("qnas:detail", args=[self.question.id])
        response = self.client.post(self.del_question_url, data={"referer": invalid})
        self.assertRedirects(response, self.default_question_redirect)

    def test_answer_redirects_to_default_if_no_or_invalid_previous(self):
        response = self.client.post(self.del_answer_url)
        self.assertRedirects(response, self.default_answer_redirect)

    def test_answer_redirects_to_default_if_invalid_previous(self):
        invalid = reverse("qnas:detail", args=[999])
        response = self.client.post(self.del_answer_url, data={"referer": invalid})
        self.assertRedirects(response, self.default_answer_redirect)

    def test_question_redirects_to_valid_previous(self):
        referer = reverse("qnas:index")
        response = self.client.post(self.del_question_url, data={"referer": referer})
        self.assertRedirects(response, referer)

    def test_answer_redirects_to_valid_previous(self):
        referer = reverse("qnas:index")
        response = self.client.post(self.del_answer_url, data={"referer": referer})
        self.assertRedirects(response, referer)

