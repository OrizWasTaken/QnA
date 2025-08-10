from django.forms import ModelForm
from .models import Question, Answer

class QuestionForm(ModelForm):
    class Meta:
        model = Question
        fields = ['title', 'body', 'tags']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tags'].required = True

class AnswerForm(ModelForm):
    class Meta:
        model = Answer
        fields = ['text']