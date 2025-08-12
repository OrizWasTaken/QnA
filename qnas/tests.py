import datetime

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import Question, QuestionVote, Answer, AnswerVote, View

class QuestionModelTests(TestCase):
    def test_is_edited_with_unedited_question(self):
        """is_edited() should return False if the question has not been edited."""
        pub_date = timezone.now()
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
        pub_date = timezone.now()
        mod_date = pub_date + datetime.timedelta(microseconds=999_999)
        unedited_question = Question(pub_date=pub_date, mod_date=mod_date)
        self.assertIs(unedited_question.is_edited, False)

    def test_is_edited_with_edited_questions(self):
        """is_edited() should return True if the question has been edited."""
        pub_date = timezone.now() - datetime.timedelta(minutes=10)
        mod_date = timezone.now()
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
        cls.author = get_user_model().objects.create_user(username="author", password="password")
        cls.question = Question.objects.create(author=cls.author, title="test_question", body="test_body")
        cls.answer = Answer.objects.create(author=cls.author, question=cls.question, text="test_answer")

    def _assert_vote_count_without_votes_for(self, content):
        """vote_count should return 0 when there are no votes."""
        self.assertEqual(content.vote_count, 0)

    def _assert_vote_count_with_votes_for(self, content, vote_model, fk_field_name):
        """
        vote_count should return the net sum (upvotes as +1, downvotes as -1) of all vote values when there are votes.
        """
        vote_values = (1, -1, 1, 1, -1)
        users = [get_user_model()(username=f"test_user{i}") for i in range(len(vote_values))]
        get_user_model().objects.bulk_create(users)

        # Refresh users from DB to get IDs
        users = list(get_user_model().objects.filter(username__startswith="test_user"))

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