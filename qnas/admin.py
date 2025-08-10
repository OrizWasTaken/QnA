from django.contrib import admin
from .models import Tag, Question, Answer, QuestionVote, AnswerVote, View

admin.site.register([Tag, Question, Answer, QuestionVote, AnswerVote, View])