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
from .forms import QuestionForm

# ---------------------------
# Test Helpers
# ---------------------------

def _assert_successful_get_request(obj, view, *reverse_args, query_params=None):
    """Utility: Send a GET request to the given view and assert a 200 OK response."""
    response = obj.client.get(reverse(view, args=reverse_args), query_params=query_params)
    obj.assertEqual(response.status_code, 200)
    return response

def _asserts_404_for_invalid_id(obj, view, method="GET", data=None):
    """Utility: Assert that accessing a resource with a nonexistent ID returns 404."""
    requested_url = reverse(view, args=[999])  # deliberately invalid pk
    response = obj.client.get(requested_url) if method.lower() == "get" else obj.client.post(requested_url, data=data)
    obj.assertEqual(response.status_code, 404)

def _assert_redirects_anonymous_user_to_login(obj, view, *view_args):
    """Utility: Assert that anonymous users are redirected to login page when accessing protected views."""
    obj.client.logout()
    requested_url = reverse(view, args=view_args)
    response = obj.client.get(requested_url)
    login_url = reverse("accounts:login", query={"next": requested_url})
    obj.assertRedirects(response, login_url)

def _assert_non_author_cannot_modify_content(obj, view, content_factory, *factory_args):
    """Utility: Assert that non-authors cannot edit or delete someone else’s content."""
    author = user_factory(username="author")
    content = content_factory(author, *factory_args)
    response = obj.client.get(reverse(view, args=[content.pk]))
    obj.assertEqual(response.status_code, 404)

def user_factory(username="test_user"):
    """Create a user for testing."""
    return get_user_model().objects.bulk_create([get_user_model()(username=username)])[0]

def question_factory(user, num=1):
    """Create one or multiple questions authored by `user`."""
    return (
        Question.objects.bulk_create([Question(author=user) for _ in range(num)]) if num > 1 else
        Question.objects.create(author=user, title="test_question", body="test_body")
    )

def answer_factory(user, question):
    """Create an answer for a question authored by `user`."""
    return Answer.objects.create(author=user, question=question, text="test_answer")

def tag_factory():
    """Create a tag with placeholder text."""
    return Tag.objects.create(text="test_tag")


# ---------------------------
# Model Tests
# ---------------------------

class QuestionModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()

    def test_is_edited_with_unedited_question(self):
        """
        Question.is_edited should return False when pub_date and mod_date
        are the same (or differ only by microseconds).

        This prevents marking fresh questions as "edited" due to
        negligible timestamp differences at creation.
        """
        with self.subTest("Exact same timestamps"):
            q = Question(pub_date=self.now, mod_date=self.now)
            self.assertIs(q.is_edited, False)

        with self.subTest("Difference less than 1 second"):
            q = Question(pub_date=self.now - datetime.timedelta(microseconds=999_999), mod_date=self.now)
            self.assertIs(q.is_edited, False)

    def test_is_edited_with_actual_edit(self):
        """is_edited should be True if mod_date is at least 1 second later than pub_date."""
        q = Question(pub_date=self.now - datetime.timedelta(minutes=10), mod_date=self.now)
        self.assertIs(q.is_edited, True)


class AnswerModelTests(TestCase):
    def test_str_with_short_text(self):
        """__str__ should clean whitespace and return full text if ≤ 200 chars."""
        text = "  Short answer.  \nWith newline.  "
        answer = Answer(text=text)
        expected = "Short answer. With newline."
        self.assertEqual(str(answer), expected)

    def test_str_with_long_text(self):
        """__str__ should truncate text >200 chars and add '...' at the end."""
        text = "line1\n" + "a" * 250
        answer = Answer(text=text)
        expected = ("line1 " + "a" * 250)[:200] + "..."
        self.assertEqual(str(answer), expected)

    def test_str_removes_blank_lines(self):
        """__str__ should remove blank/whitespace-only lines when joining text."""
        answer = Answer(text="Line1\n\n \nLine2")
        self.assertEqual(str(answer), "Line1 Line2")


class VoteCountTests(TestCase):
    """Tests for vote counting logic on both Questions and Answers."""

    @classmethod
    def setUpTestData(cls):
        cls.author = user_factory()
        cls.question = question_factory(cls.author)
        cls.answer = answer_factory(cls.author, cls.question)

    def _assert_vote_count_without_votes_for(self, content):
        self.assertEqual(content.vote_count, 0)

    def _assert_vote_count_with_votes_for(self, content, vote_model, fk_field_name):
        """Ensure net vote count = sum of (+1 upvotes and -1 downvotes)."""
        vote_values = (1, -1, 1, 1, -1)
        users = [get_user_model()(username=f"user{i}") for i in range(len(vote_values))]
        get_user_model().objects.bulk_create(users)

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
        """hrs_since_viewed should return hours elapsed since `view_time`, rounded to 2 decimals."""
        view = View(view_time=(timezone.now() - datetime.timedelta(hours=3)))
        self.assertAlmostEqual(view.hrs_since_viewed, 3, places=2)


# ---------------------------
# View Tests: Listing Questions
# ---------------------------

class QuestionListViewsTests(TestCase):
    """
    Tests for:
    - Filtering (Newest, Unanswered, Popular).
    - Handling empty results.
    - Behavior of tag-specific and general question lists.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tag = tag_factory()

    def _assert_no_question_for(self, view, *args):
        response = _assert_successful_get_request(self, view, *args)
        self.assertContains(response, "0 questions")

    def _assert_default_filter_for(self, view, *args):
        """Ensure 'Newest' is default when tab is missing or invalid."""
        questions = question_factory(self.user, 3)
        if args: self.tag.questions.add(*questions)

        def _assert_newest(query_params=None):
            response = _assert_successful_get_request(self, view, *args, query_params=query_params)
            self.assertEqual(response.context["tab"].lower(), "newest")
            self.assertQuerySetEqual(response.context["all_questions"], reversed(questions))

        with self.subTest("No tab selected"):
            _assert_newest()
        with self.subTest("Invalid tab selected"):
            _assert_newest({"tab": "invalid"})

    def _assert_defined_tabs_for(self, view, *args):
        """Ensure 'Unanswered' shows only unanswered, 'Popular' sorts by view count."""
        q1, q2, q3 = question_factory(self.user, 3)
        if args: self.tag.questions.add(q1, q2, q3)

        with self.subTest("Unanswered tab"):
            q3.answers.create(author=self.user)
            response = _assert_successful_get_request(self, view, *args, query_params={"tab": "Unanswered"})
            self.assertEqual(list(response.context["all_questions"]), [q2, q1])

        with self.subTest("Popular tab"):
            View.objects.bulk_create([View(user=self.user, question=q3) for _ in range(2)])
            View.objects.bulk_create([View(user=self.user, question=q1)])
            response = _assert_successful_get_request(self, view, *args, query_params={"tab": "Popular"})
            self.assertEqual(list(response.context["all_questions"]), [q3, q1, q2])

    # Individual tests
    def test_tagged_questions_invalid_tag_returns_404(self):
        _asserts_404_for_invalid_id(self, "qnas:tagged-questions")

    def test_no_question_for_tagged_questions(self):
        self._assert_no_question_for("qnas:tagged-questions", self.tag.id)

    def test_no_question_for_questions(self):
        self._assert_no_question_for("qnas:questions")

    def test_default_filter_for_questions(self):
        self._assert_default_filter_for("qnas:questions")

    def test_default_filter_for_tagged_questions(self):
        self._assert_default_filter_for("qnas:tagged-questions", self.tag.id)

    def test_defined_tabs_for_questions(self):
        self._assert_defined_tabs_for("qnas:questions")

    def test_defined_tabs_for_tagged_questions(self):
        self._assert_defined_tabs_for("qnas:tagged-questions", self.tag.id)


# ---------------------------
# View Tests: Listing Tags
# ---------------------------

class TagViewTests(TestCase):
    """Tests for tab-based sorting of tags."""

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()

    def test_default_tab_filter(self):
        """Default tab should be 'popular' when missing or invalid."""
        def _assert_popular(query_params=None):
            response = _assert_successful_get_request(self, "qnas:tags", query_params=query_params)
            self.assertEqual(response.context["tab"].lower(), "popular")

        with self.subTest("No tab selected"):
            _assert_popular()
        with self.subTest("Invalid tab selected"):
            _assert_popular({"tab": "nonsense"})

    def test_defined_tabs(self):
        """'Popular' sorts by usage, 'New' by recency, 'Name' alphabetically."""
        t1, t2, t3 = Tag.objects.bulk_create([Tag(text=str(i)) for i in range(3)])
        q1, q2 = question_factory(self.user, 2)
        t2.questions.add(q1, q2); t3.questions.add(q1)

        def _assert_tab(tab):
            response = _assert_successful_get_request(self, "qnas:tags", query_params={"tab": tab})
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
    Tests for asking and editing questions:
    - Permissions (anonymous redirects, only authors may edit).
    - Form validation and behavior on GET/POST.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tag = tag_factory()

    def setUp(self):
        self.client.force_login(self.user)

    def test_ask_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, "qnas:ask")

    def test_edit_question_redirects_anonymous_user_to_login(self):
        _assert_redirects_anonymous_user_to_login(self, "qnas:edit-question", 1)

    def test_edit_question_with_nonexistent_question(self):
        _asserts_404_for_invalid_id(self, "qnas:edit-question")

    def test_non_author_cannot_edit_question(self):
        _assert_non_author_cannot_modify_content(self, "qnas:edit-question", question_factory)

    def _assert_returns_form(self, response, empty_form=True):
        """Helper: verify form type + whether it’s empty or pre-populated."""
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIsInstance(form, QuestionForm)
        if empty_form:
            self.assertIsNone(form.instance.pk)
        else:
            self.assertEqual(form.instance.pk, 1)

    def test_ask_displays_empty_form_on_get(self):
        response = self.client.get(reverse("qnas:ask"))
        self._assert_returns_form(response)

    def test_edit_question_displays_prepopulated_form_on_get(self):
        question_factory(self.user)
        response = self.client.get(reverse("qnas:edit-question", args=[1]))
        self._assert_returns_form(response, False)

    def _assert_re_renders_form_on_invalid_submission(self, view, *args, question_for_edit=None):
        """Invalid POST should re-render form and not persist changes."""
        def _assert_no_commit(new_title):
            if question_for_edit:
                self.assertNotEqual(question_for_edit.title, new_title)
            else:
                self.assertFalse(Question.objects.exists())

        with self.subTest("Missing required field"):
            response = self.client.post(reverse(view, args=args), {"title": "a", "body": "b"})
            self._assert_returns_form(response, not question_for_edit); _assert_no_commit("a")

        with self.subTest("Invalid tag id"):
            response = self.client.post(reverse(view, args=args), {"title": "a", "body": "b", "tags": [999]})
            self._assert_returns_form(response, not question_for_edit); _assert_no_commit("a")

        with self.subTest("Title too long"):
            long_title = "x" * 201
            response = self.client.post(reverse(view, args=args), {"title": long_title, "body": "b", "tags": [self.tag.pk]})
            self._assert_returns_form(response, not question_for_edit); _assert_no_commit(long_title)

    def test_ask_invalid_submission(self):
        self._assert_re_renders_form_on_invalid_submission("qnas:ask")

    def test_edit_question_invalid_submission(self):
        q = question_factory(self.user)
        self._assert_re_renders_form_on_invalid_submission("qnas:edit-question", 1, question_for_edit=q)

    def _assert_valid_submission_creates_or_updates(self, view, *args):
        """Valid POST should create/edit question then redirect to detail page."""
        response = self.client.post(reverse(view, args=args),
            {"title": "title", "body": "body", "tags": [self.tag.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Question.objects.filter(title="title", body="body").exists())
        self.assertRedirects(response, reverse("qnas:detail", args=[1]))

    def test_ask_valid_submission(self):
        self._assert_valid_submission_creates_or_updates("qnas:ask")

    def test_edit_question_valid_submission(self):
        question_factory(self.user)
        self._assert_valid_submission_creates_or_updates("qnas:edit-question", 1)