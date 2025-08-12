import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils import timezone

class Tag(models.Model):
    text = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=250, blank=True)
    creation_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'#{self.text}'

class Question(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='questions',on_delete=models.DO_NOTHING)
    title = models.CharField(max_length=200)
    body = models.TextField()
    tags = models.ManyToManyField(Tag, related_name='questions')
    pub_date = models.DateTimeField('asked', auto_now_add=True)
    mod_date = models.DateTimeField('edited', auto_now=True)

    @property
    def is_edited(self):
        return self.mod_date - self.pub_date  >= datetime.timedelta(seconds=1)

    @property
    def vote_count(self):
        return self.votes.aggregate(vote_count=models.Sum('value')).get('vote_count') or 0

    @property
    def class_name(self):
        return self.__class__.__name__

    def __str__(self):
        return self.title

class Answer(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING)
    question = models.ForeignKey(Question, related_name='answers', on_delete=models.CASCADE)
    text = models.TextField('Your Answer')
    pub_date = models.DateTimeField('answered', auto_now_add=True)
    mod_date = models.DateTimeField('edited', auto_now=True)

    @property
    def vote_count(self):
        return self.votes.aggregate(vote_count=models.Sum('value')).get('vote_count') or 0

    @property
    def class_name(self):
        return self.__class__.__name__

    def __str__(self):
        str_repr = ' '.join(line.strip() for line in self.text.splitlines() if line.strip())
        return str_repr if len(str_repr) <= 200 else str_repr[:200] + '...'


class BaseVote(models.Model):
    UPVOTE = 1
    DOWNVOTE = -1
    choices = [
        (UPVOTE, 'upvote'),
        (DOWNVOTE, 'downvote'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    value = models.SmallIntegerField(choices=choices)

    class Meta:
        abstract = True

class QuestionVote(BaseVote):
    question = models.ForeignKey(Question, related_name='votes', on_delete=models.CASCADE)
    class Meta:
        unique_together = ['user', 'question', 'value']

    def __str__(self):
        return f'{self.user} {self.get_value_display()}d "{self.question}"'

class AnswerVote(BaseVote):
    answer = models.ForeignKey(Answer, related_name='votes', on_delete=models.CASCADE)
    class Meta:
        unique_together = ['user', 'answer', 'value']

    def __str__(self):
        return f'{self.user} {self.get_value_display()}d "{self.answer}"'

class View(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='views', on_delete=models.DO_NOTHING, null=True)
    question = models.ForeignKey(Question, related_name='views', on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField(null=True)
    view_time = models.DateTimeField(auto_now_add=True)

    @property
    def hrs_since_viewed(self):
        return (timezone.now() - self.view_time).total_seconds() / 3600

    def clean(self):
        if not (self.user or self.ip_address):
            raise ValidationError('You must specify a user or IP address')

    def __str__(self):
        return f'"{self.user}" viewed "{self.question}"'