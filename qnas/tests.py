import datetime

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import Tag, Question, QuestionVote, Answer, AnswerVote, View
from .forms import  QuestionForm


def _assert_successful_get_request(obj, view, query_params=None, **reverse_kwargs):
    """Send a GET request to the given view and assert a 200 OK response."""
    response = obj.client.get(reverse(view, kwargs=reverse_kwargs), query_params=query_params)
    obj.assertEqual(response.status_code, 200)
    return response

def user_factory():
    return get_user_model().objects.bulk_create([get_user_model()(username="author")])[0]

def question_factory(user):
    return Question.objects.create(author=user, title="test_question", body="test_body")

def answer_factory(user, question):
    return Answer.objects.create(author=user, question=question, text="test_answer")

def tag_factory():
    return Tag.objects.create(text="test_tag")

class QuestionModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = timezone.now()

    def test_is_edited_with_unedited_question(self):
        """
        is_edited should return False if pub_date and mod_date are identical
        or the only difference between them is less than one second
        (microsecond differences ignored).

        This verifies that microsecond-level variations, which can occur when both
        timestamps are set during object creation, are ignored in the edited check.
        """
        with self.subTest("pub_date and mod_date are identical"):
            mod_date = pub_date = self.now
            unedited_question = Question(pub_date=pub_date, mod_date=mod_date)
            self.assertIs(unedited_question.is_edited, False)

        with self.subTest("pub_date and mod_date differ by less than a second"):
            pub_date = self.now - datetime.timedelta(microseconds=999_999)
            mod_date = self.now
            unedited_question = Question(pub_date=pub_date, mod_date=mod_date)
            self.assertIs(unedited_question.is_edited, False)

    def test_is_edited_with_edited_questions(self):
        """is_edited should return True if mod_date is later than pub_date by ≥ 1 second."""
        pub_date = self.now - datetime.timedelta(minutes=10)
        mod_date = self.now
        edited_question = Question(pub_date=pub_date, mod_date=mod_date)
        self.assertIs(edited_question.is_edited, True)

class AnswerModelTests(TestCase):
    def test_str_with_short_text(self):
        """__str__ should return the cleaned text if ≤ 200 characters."""
        short_text = "  This is a short answer.  \n  With a second line.  "
        answer = Answer(text=short_text)
        expected = "This is a short answer. With a second line."
        self.assertEqual(str(answer), expected)

    def test_str_with_long_text(self):
        """__str__ should return the first 200 characters followed by '...' if text is longer."""
        long_text = "line1\n" + "a" * 250
        answer = Answer(text=long_text)
        stripped_joined = "line1 " + "a" * 250
        expected = stripped_joined[:200] + "..."
        self.assertEqual(str(answer), expected)

    def test_str_removes_blank_lines(self):
        """__str__ should remove all blank lines when joining text."""
        answer = Answer(text="First line\n\n \nSecond line")
        expected = "First line Second line"
        self.assertEqual(str(answer), expected)

class VoteCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user_factory()
        cls.question = question_factory(cls.author)
        cls.answer = answer_factory(cls.author, cls.question)

    def _assert_vote_count_without_votes_for(self, content):
        """vote_count should return 0 if there are no votes for the content."""
        self.assertEqual(content.vote_count, 0)

    def _assert_vote_count_with_votes_for(self, content, vote_model, fk_field_name):
        """
        vote_count should return the net sum of all vote values (+1 upvote, -1 downvote)
        when votes exist for the content.
        """
        vote_values = (1, -1, 1, 1, -1)
        users = [get_user_model()(username=f"test_user{i}") for i in range(len(vote_values))]
        get_user_model().objects.bulk_create(users)

        votes = [
            vote_model(user=user, value=value, **{fk_field_name: content})
            for user, value in zip(users, vote_values)
        ]
        vote_model.objects.bulk_create(votes)

        self.assertEqual(content.vote_count, sum(vote_values))

    def test_vote_count_without_votes_for_questions(self):
        """Questions without votes should have vote_count = 0."""
        self._assert_vote_count_without_votes_for(self.question)

    def test_vote_count_with_votes_for_questions(self):
        """Questions with votes should return correct net vote count."""
        self._assert_vote_count_with_votes_for(self.question, QuestionVote, "question")

    def test_vote_count_without_votes_for_answers(self):
        """Answers without votes should have vote_count = 0."""
        self._assert_vote_count_without_votes_for(self.answer)

    def test_vote_count_with_votes_for_answers(self):
        """Answers with votes should return correct net vote count."""
        self._assert_vote_count_with_votes_for(self.answer, AnswerVote, "answer")

class ViewModelTests(TestCase):
    def test_hrs_since_viewed(self):
        """hrs_since_viewed should return hours since view_time, rounded to 2 decimals."""
        view = View(
            view_time=(timezone.now() - datetime.timedelta(hours=3))
        )
        self.assertAlmostEqual(view.hrs_since_viewed, 3, places=2)

class QuestionListViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tag = tag_factory()

    def _assert_no_question_for(self, view, **kwargs):
        """When no questions exist, the page should display '0 questions'."""
        response = _assert_successful_get_request(self, view, **kwargs)
        self.assertContains(response, "0 questions")

    def _assert_default_filter_for(self, view, **kwargs):
        """Questions should default to 'newest' tab if no or invalid tab is selected."""
        questions = Question.objects.bulk_create([Question(author=self.user) for _ in range(3)])
        if kwargs.get("tag"):
            kwargs["tag"].questions.add(*questions)
            kwargs = {"tag_text": kwargs["tag"].text}

        def _assert_newest_is_default_tab(query_params=None):
            response = _assert_successful_get_request(self, view, query_params=query_params, **kwargs)
            self.assertEqual(response.context["tab"].lower(), "newest")
            self.assertQuerySetEqual(response.context["all_questions"], reversed(questions))

        with self.subTest("No tab selected"):
            _assert_newest_is_default_tab()
        with self.subTest("Invalid tab selected"):
            _assert_newest_is_default_tab(query_params={"tab": "oldest"})

    def _assert_defined_tabs_for(self, view, **kwargs):
        """
        'Unanswered' tab should show only questions without answers.
        'Popular' tab should sort questions by view count (descending).
        """
        questions = Question.objects.bulk_create([Question(author=self.user) for _ in range(3)])
        q1, q2, q3 = questions
        if kwargs.get("tag"):
            kwargs["tag"].questions.add(*questions)
            kwargs = {"tag_text": kwargs["tag"].text}

        with self.subTest("'Unanswered' tab"):
            q3.answers.create(author=self.user)
            response = _assert_successful_get_request(self, view, query_params={"tab": "Unanswered"}, **kwargs)
            self.assertEqual(response.context["tab"], "Unanswered")
            self.assertQuerySetEqual(response.context["all_questions"], (q2, q1))

        with self.subTest("'Popular' tab"):
            View.objects.bulk_create([View(user=self.user, question=q3) for _ in range(2)])
            View.objects.bulk_create([View(user=self.user, question=q1) for _ in range(1)])
            response = _assert_successful_get_request(self, view, query_params={"tab": "Popular"}, **kwargs)
            self.assertEqual(response.context["tab"], "Popular")
            self.assertQuerySetEqual(response.context["all_questions"], (q3, q1, q2))

    def test_tagged_questions_with_nonexistent_tag(self):
        """Nonexistent tag in tagged-questions view should return 404."""
        response = self.client.get(reverse("qnas:tagged-questions", args=["nonexistent_tag"]))
        self.assertEqual(response.status_code, 404)

    def test_no_question_for_tagged_questions(self):
        """If no questions exist, '0 questions' should be displayed."""
        self._assert_no_question_for("qnas:tagged-questions", tag_text=self.tag.text)

    def test_no_question_for_questions(self):
        """If no questions exist, '0 questions' should be displayed."""
        self._assert_no_question_for("qnas:questions")

    def test_default_filter_for_questions(self):
        """Questions view should default to 'newest' ordering."""
        self._assert_default_filter_for("qnas:questions")

    def test_default_filter_for_tagged_questions(self):
        """Tagged-questions view should default to 'newest' ordering."""
        self._assert_default_filter_for("qnas:tagged-questions", tag=self.tag)

    def test_defined_tab_for_questions(self):
        """Questions view should filter correctly for defined tabs."""
        self._assert_defined_tabs_for("qnas:questions")

    def test_defined_tab_for_tagged_questions(self):
        """Tagged-questions view should filter correctly for defined tabs."""
        self._assert_defined_tabs_for("qnas:tagged-questions", tag=self.tag)

class TagViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()

    def test_default_tab_filter(self):
        """Tags view should default to 'popular' if no or invalid tab is selected."""
        def _assert_popular_is_default_tab(query_params=None):
            response = _assert_successful_get_request(self, "qnas:tags", query_params=query_params)
            self.assertEqual(response.context["tab"].lower(), "popular")

        with self.subTest("No tab selected"):
            _assert_popular_is_default_tab()
        with self.subTest("Invalid tab selected"):
            _assert_popular_is_default_tab(query_params={"tab": "unused"})

    def test_defined_tabs(self):
        """
        'Popular' tab should sort tags by usage count.
        'New' tab should sort tags by creation date (descending).
        'Name' tab should sort tags alphabetically.
        """
        t1, t2, t3 = Tag.objects.bulk_create([Tag(text=str(i)) for i in range(3)])
        q1, q2 = Question.objects.bulk_create([Question(author=self.user) for _ in range(2)])

        t2.questions.add(q1, q2)
        t3.questions.add(q1)

        def _assert_selected_tab(tab=None):
            response = _assert_successful_get_request(self, "qnas:tags", query_params={"tab": tab})
            self.assertEqual(response.context["tab"].lower(), tab.lower())
            return response

        with self.subTest("'Popular' tab"):
            self.assertQuerySetEqual(_assert_selected_tab(tab="Popular").context["all_tags"], (t2, t3, t1))

        with self.subTest("'New' tab"):
            self.assertQuerySetEqual(_assert_selected_tab(tab="New").context["all_tags"], (t3, t2, t1))

        with self.subTest("'Name' tab"):
            self.assertQuerySetEqual(_assert_selected_tab(tab="Name").context["all_tags"], (t1, t2, t3))

class AskViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = user_factory()
        cls.tag = tag_factory()

    def setUp(self):
        self.client.force_login(self.user)

    def test_redirects_anonymous_user_to_login(self):
        """Anonymous users should be redirected to login page."""
        self.client.logout()
        response = self.client.get(reverse("qnas:ask"))
        login_url = reverse("accounts:login") + f"?next={reverse('qnas:ask')}"
        self.assertRedirects(response, login_url)

    def _assert_returns_empty_form(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["form"], QuestionForm)
        self.assertFalse(response.context["form"].is_bound)
        self.assertEqual(
            list(response.context["form"].fields.keys()),
            ["title", "body", "tags"],
        )

    def test_displays_empty_form_on_get_request(self):
        """Logged-in user should see an empty form when using GET."""
        response = self.client.get(reverse("qnas:ask"))
        self._assert_returns_empty_form(response)

    def test_re_renders_form_on_invalid_submission(self):
        """Invalid POST requests should re-render form with errors and not create a question."""

        with self.subTest("Missing required field"):
            response = self.client.post(
                reverse("qnas:ask"),
                {"title": "a", "body": "b"},  # missing tags
            )
            self._assert_returns_empty_form(response)
            self.assertFalse(Question.objects.exists())

        with self.subTest("Invalid tag id"):
            response = self.client.post(
                reverse("qnas:ask"),
                {"title": "a", "body": "b", "tags": [999]},
            )
            self._assert_returns_empty_form(response)
            self.assertFalse(Question.objects.exists())

        with self.subTest("Title exceeds max_length"):
            long_title = "x" * 201
            response = self.client.post(
                reverse("qnas:ask"),
                {"title": long_title, "body": "body", "tags": [self.tag.pk]},
            )
            self._assert_returns_empty_form(response)
            self.assertFalse(Question.objects.exists())

    def test_creates_question_and_redirects_on_valid_form(self):
        """Valid POST should create a question and redirect to detail page."""
        response = self.client.post(
            reverse("qnas:ask"),
            {
                "title": "test_title",
                "body": "test_body",
                "tags": [self.tag.pk],
            },
        )
        self.assertEqual(response.status_code, 302)

        question = Question.objects.get(title="test_title", body="test_body")
        self.assertEqual(question.author, self.user)

        self.assertRedirects(
            response,
            reverse("qnas:detail", args=[question.pk]),
        )

