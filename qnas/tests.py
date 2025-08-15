import datetime

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import Tag, Question, QuestionVote, Answer, AnswerVote, View

def _assert_successful_request(obj, view, query_params=None, **kwargs):
    """send a request to a url and assert that the response is 200 (successful)"""
    response = obj.client.get(reverse(view, kwargs=kwargs), query_params=query_params)
    obj.assertEqual(response.status_code, 200)
    return response

class QuestionModelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_is_edited_with_unedited_question(self):
        """is_edited() should return False if the question has not been edited."""
        pub_date = self.now
        mod_date = pub_date
        unedited_question = Question(pub_date=pub_date, mod_date=mod_date)
        self.assertIs(unedited_question.is_edited, False)

    def test_is_edited_ignores_microseconds_in_comparison(self):
        """
           is_edited() should return False when the only difference
           between pub_date and mod_date is less than one second (microseconds difference).

           This verifies that microsecond-level variations, which can occur when both
           timestamps are set during object creation, are ignored in the edited check.
       """
        pub_date = self.now - datetime.timedelta(microseconds=999_999)
        mod_date = self.now
        unedited_question = Question(pub_date=pub_date, mod_date=mod_date)
        self.assertIs(unedited_question.is_edited, False)

    def test_is_edited_with_edited_questions(self):
        """is_edited() should return True if the question has been edited."""
        pub_date = self.now - datetime.timedelta(minutes=10)
        mod_date = self.now
        edited_question = Question(pub_date=pub_date, mod_date=mod_date)
        self.assertIs(edited_question.is_edited, True)

class AnswerStrMethodTest(TestCase):
    def test_str_with_short_text(self):
        """__str__ should return the stripped text if ≤ 200 chars."""
        short_text = "  This is a short answer.  \n  With a second line.  "
        answer = Answer(text=short_text,)
        expected = "This is a short answer. With a second line."
        self.assertEqual(str(answer), expected)

    def test_str_with_long_text(self):
        """__str__ should truncate to 200 chars with ellipsis if longer."""
        long_text = "line1\n" + "a" * 250
        answer = Answer(text=long_text)
        stripped_joined = "line1 " + "a" * 250
        expected = stripped_joined[:200] + "..."
        self.assertEqual(str(answer), expected)

    def test_str_removes_blank_lines(self):
        """__str__ should remove blank lines entirely."""
        answer = Answer(text="First line\n\n \nSecond line")
        expected = "First line Second line"
        self.assertEqual(str(answer), expected)

class VoteCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author, = get_user_model().objects.bulk_create([get_user_model()(username=f"author")])
        cls.question = Question.objects.create(author=cls.author, title="test_question", body="test_body")
        cls.answer = Answer.objects.create(author=cls.author, question=cls.question, text="test_answer")

    def _assert_vote_count_without_votes_for(self, content):
        """assert vote_count should return 0 when there are no votes for `content`."""
        self.assertEqual(content.vote_count, 0)

    def _assert_vote_count_with_votes_for(self, content, vote_model, fk_field_name):
        """
        Create `vote_model` votes for a `content` with related_name `fk_field_name` and assert that vote_count
        return the net sum (upvotes as +1, downvotes as -1) of all vote values when there are votes for `content`.
        """
        vote_values = (1, -1, 1, 1, -1)
        users = [get_user_model()(username=f"test_user{i}") for i in range(len(vote_values))]
        get_user_model().objects.bulk_create(users)

        votes = [
            vote_model(user=user, value=value, **{fk_field_name: content})
            for user, value in zip(users, vote_values)]
        vote_model.objects.bulk_create(votes)

        self.assertEqual(content.vote_count, sum(vote_values))

    def test_vote_count_without_votes_for_questions(self):
        self._assert_vote_count_without_votes_for(self.question)

    def test_vote_count_with_votes_for_questions(self):
        self._assert_vote_count_with_votes_for(self.question, QuestionVote, "question")

    def test_vote_count_without_votes_for_answers(self):
        self._assert_vote_count_without_votes_for(self.answer)

    def test_vote_count_with_votes_for_answers(self):
        self._assert_vote_count_with_votes_for(self.answer, AnswerVote, "answer")

class ViewModelTests(TestCase):
    def test_hrs_since_viewed(self):
        """hrs_since_viewed should return the number of hours since view_time"""
        view = View(
            view_time=(timezone.now() - datetime.timedelta(hours=3)) # viewed 3 hrs ago
        )
        self.assertAlmostEqual(view.hrs_since_viewed, 3, places=2) # 3 hrs to 2 d.p

class QuestionListViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user, = get_user_model().objects.bulk_create((get_user_model()(username=f"author"),))

    def _assert_no_question_for(self, view, **kwargs):
        """
        If no question exists, an appropriate text should be displayed.
        By verifying text, asserts that the respective view functions render the right template.
        """
        response = _assert_successful_request(self, view, **kwargs)
        self.assertContains(response, "0 questions")

    def _assert_default_filter_for(self, view, **kwargs):
        """questions should be ordered by `newest` if no tab is selected or the selected tab does not exist."""
        questions = Question.objects.bulk_create([Question(author=self.user) for _ in range(3)])
        if kwargs.get("tag"):
            kwargs["tag"].questions.add(*questions)
            kwargs = {"tag_text": kwargs["tag"].text}

        def _assert_newest_is_default_tab(query_params=None):
            response = _assert_successful_request(self, view, query_params=query_params, **kwargs)
            self.assertEqual(response.context["tab"].lower(), "newest")
            self.assertQuerySetEqual(response.context["all_questions"], reversed(questions))

        with self.subTest("No tab selected"): _assert_newest_is_default_tab()
        with self.subTest("Selected undefined tab"): _assert_newest_is_default_tab(query_params={"tab": "oldest"})

    def _assert_defined_tabs_for(self, view, **kwargs):
        """
        questions should be filtered correctly when a defined, existing tag is selected.
        tab 'unanswered' should filter questions without an answer.
        tab 'popular' should filter questions by view count in descending order.
        """
        questions = Question.objects.bulk_create([Question(author=self.user) for _ in range(3)])
        q1, q2, q3 = questions
        if kwargs.get("tag"):
            kwargs["tag"].questions.add(*questions)
            kwargs = {"tag_text": kwargs["tag"].text}

        with self.subTest("Tab 'unanswered' selected"):
            q3.answers.create(author=self.user) # create an answer for the last question.
            response = _assert_successful_request(self, view, query_params={"tab": "Unanswered"}, **kwargs)
            self.assertEqual(response.context["tab"], "Unanswered")
            self.assertQuerySetEqual(response.context["all_questions"], (q2, q1)) # `all_questions` should omit q3.

        with self.subTest("Tab 'popular' selected"):
            View.objects.bulk_create([View(user=self.user, question=q3) for _ in range(2)])
            View.objects.bulk_create([View(user=self.user, question=q1) for _ in range(1)])
            response = _assert_successful_request(self, view, query_params={"tab": "Popular"}, **kwargs)
            self.assertEqual(response.context["tab"], "Popular")
            self.assertQuerySetEqual(response.context["all_questions"], (q3, q1, q2)) # questions ordered by views.

    def test_tagged_questions_with_nonexistent_tag(self):
        response = self.client.get(reverse("qnas:tagged-questions", args=["test_tag"]))
        self.assertEqual(response.status_code, 404)

    def test_no_question_for_tagged_questions(self):
        self._assert_no_question_for("qnas:tagged-questions", tag_text=Tag.objects.create(text="test_tag").text)

    def test_no_question_for_questions(self):
        self._assert_no_question_for("qnas:questions")

    def test_default_filter_for_questions(self):
        self._assert_default_filter_for("qnas:questions")

    def test_default_filter_for_tagged_questions(self):
        self._assert_default_filter_for("qnas:tagged-questions", tag=Tag.objects.create(text="test_tag"))

    def test_defined_tag_for_questions(self):
        self._assert_defined_tabs_for("qnas:questions")

    def test_defined_tag_for_tagged_questions(self):
        self._assert_defined_tabs_for("qnas:tagged-questions", tag=Tag.objects.create(text="test_tag"))

class TagViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user, = get_user_model().objects.bulk_create((get_user_model()(username=f"author"),))

    def test_default_tab_filter(self):
        """
        Tab should default to 'popular' if no tab is selected or the selected tab does not exist.
        """
        def _assert_popular_is_default_tab(query_params=None):
            response = _assert_successful_request(self, "qnas:tags", query_params=query_params)
            self.assertEqual(response.context["tab"].lower(), "popular")

        with self.subTest("No tab selected"): _assert_popular_is_default_tab()
        with self.subTest("Selected undefined tab"): _assert_popular_is_default_tab(query_params={"tab": "unused"})

    def test_defined_tabs(self):
        t1, t2, t3 = Tag.objects.bulk_create([Tag(text=str(i)) for i in range(3)])
        q1, q2 = Question.objects.bulk_create([Question(author=self.user) for _ in range(2)])

        t2.questions.add(q1, q2)
        t3.questions.add(q1)

        def _assert_selected_tab(tab=None):
            response = _assert_successful_request(self, "qnas:tags", query_params={"tab": tab})
            self.assertEqual(response.context["tab"].lower(), tab.lower())
            return response

        with self.subTest("Tab 'Popular' selected"):
            self.assertQuerySetEqual(_assert_selected_tab(tab="Popular").context["all_tags"], (t2, t3, t1))

        with self.subTest("Tab 'New' selected"):
            self.assertQuerySetEqual(_assert_selected_tab(tab="New").context["all_tags"], (t3, t2, t1))

        with self.subTest("Tab 'Name' selected"):
            self.assertQuerySetEqual(_assert_selected_tab(tab="Name").context["all_tags"], (t1, t2, t3))