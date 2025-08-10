from django.urls import path
from . import views

app_name = 'qnas'
urlpatterns = [
    path("", views.index, name="index"),
    path("questions/", views.questions, name='questions'),
    path("questions/<int:question_id>/", views.detail, name="detail"),
    path("questions/ask", views.ask, name="ask"),
    path("questions/tagged/<str:tag_text>", views.tagged_questions, name="tagged-questions"),
    path("tags/", views.tags, name='tags'),
    path("edit/questions/<int:question_id>", views.edit_question, name="edit-question"),
    path("edit/answers/<int:answer_id>", views.edit_answer, name="edit-answer"),
    path("delete/questions/<int:question_id>", views.delete_question, name="delete-question"),
    path("delete/answers/<int:answer_id>", views.delete_answer, name="delete-answer"),
]
