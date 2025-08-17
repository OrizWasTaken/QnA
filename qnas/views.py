from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from .models import Question, Answer, Tag, QuestionVote, AnswerVote, View
from .forms import QuestionForm, AnswerForm

def index(request):
    return render(request, 'qnas/index.html')

def _get_questions_context(request, all_questions):
    tab = request.GET.get("tab") or "Newest"
    if tab.lower() == "unanswered":
        all_questions = [question for question in all_questions if not question.answers.all().exists()]
    elif tab.lower() == "popular":
        all_questions = sorted(all_questions, key=lambda question: question.views.count(), reverse=True)
    else: tab = "Newest"
    return {"all_questions": all_questions, "tab": tab}

def questions(request):
    all_questions = Question.objects.order_by("-pub_date")
    context = _get_questions_context(request, all_questions)
    return render(request, "qnas/questions.html", context)

def tagged_questions(request, tag_id):
    tag = get_object_or_404(Tag, pk=tag_id)
    all_questions = Question.objects.filter(tags=tag).order_by("-pub_date")
    context = _get_questions_context(request, all_questions)
    context.update({"tag": tag})
    return render(request, "qnas/tagged-questions.html", context)

def tags(request): # 'tag'
    all_tags = Tag.objects.all()
    tab = request.GET.get("tab") or "Popular"
    if tab.lower() == "popular":
        all_tags = sorted(all_tags, key=lambda tag: tag.questions.count(), reverse=True)
    elif tab.lower() == "new":
        all_tags = all_tags.order_by("-creation_date")
    elif tab.lower() == "name":
        all_tags = all_tags.order_by("text")
    else: tab = "Popular"
    context = {"all_tags": all_tags, "tab": tab}
    return render(request, "qnas/tags.html", context)

def _new_answer(request, question):
    form = AnswerForm(request.POST)
    if form.is_valid():
        ans = form.save(commit=False)
        ans.author = request.user
        ans.question = question
        ans.save()

def _manage_votes(value, get_or_create):
    vote, created = get_or_create
    if not created and vote.value == int(value):
        vote.delete()
    elif not created:
        vote.value = value
        vote.save()

def _manage_views(request, question):
    if request.user.is_authenticated:
        identifier = {"user": request.user}
    else:
        identifier = {"ip_address": (
                request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0]
                or request.META.get("REMOTE_ADDR"))
        }
    views = View.objects.filter(**identifier, question=question)
    if not views:
        View(**identifier, question=question).save()
    else:
        latest_view = views.latest("view_time")
        if latest_view.hrs_since_viewed > 1:
            View(**identifier, question=question).save()

def _vote(request, question):
    value = request.POST.get('vote')
    ans_id = request.POST.get('answer_id')
    if ans_id: # if an answer was voted
        ans = get_object_or_404(Answer, pk=int(ans_id))
        _manage_votes(value, AnswerVote.objects.get_or_create(
            defaults={'value':value}, user=request.user, answer=ans))
    elif value: # `if sth else (question) was voted
        _manage_votes(value, QuestionVote.objects.get_or_create(
            defaults={'value':value}, user=request.user, question=question))

def _get_user_vote_meta(question, user):
    return({
        "question_is_upvoted": _question_is_voted(question, user, 1),
        "question_is_downvoted": _question_is_voted(question, user, -1),
        "upvoted_ans_ids": _get_voted_ans_ids(user, 1),
        "downvoted_ans_ids": _get_voted_ans_ids(user, -1)
    } if user.is_authenticated else {})

def _get_voted_ans_ids(vote_user, vote_value):
    return (ans.id for ans in Answer.objects.filter(votes__user=vote_user, votes__value=int(vote_value)))

def _question_is_voted(question, user, value):
    return bool(question.votes.filter(user=user, value=int(value)))

def detail(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    user = request.user
    if request.method == "POST":
        if not user.is_authenticated:
            return redirect("accounts:login")
        _new_answer(request, question)
        _vote(request, question)
        return redirect("qnas:detail", question.id)
    _manage_views(request, question)
    vote_meta = _get_user_vote_meta(question, user)
    return render(request, "qnas/detail.html", {"question": question, "form": AnswerForm(), "vote_META": vote_meta})

@login_required
def ask(request):
    if request.method == "POST":
        form = QuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.author = request.user
            question.save()
            return redirect("qnas:detail", question.id)
    context = {"form": QuestionForm()}
    return render(request, "qnas/ask.html", context)

def _validate_owner(request, content):
    if request.user != content.author:
        raise Http404

@login_required
def edit_question(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    _validate_owner(request, question)
    if request.method == "POST":
        form = QuestionForm(data=request.POST, instance=question)
        if form.is_valid():
            form.save()
            return redirect('qnas:detail', question.id)
    context = {'form': QuestionForm(instance=question), 'question': question}
    return render(request, 'qnas/edit-question.html', context)

@login_required
def edit_answer(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    question = answer.question
    _validate_owner(request, answer)
    if request.method == "POST":
        form = AnswerForm(data=request.POST, instance=answer)
        if form.is_valid():
            form.save()
            return redirect("qnas:detail", question.id)
    context = {"form": AnswerForm(instance=answer), "question": question, "answer": answer}
    return render(request, "qnas/edit-answer.html", context)

def _del_content(request, content, *default_redirect_url, forbidden_url=None):
    _validate_owner(request, content)
    if request.method == "POST":
        content.delete()
        next_url = request.POST.get("next")
        if next_url in ("None", forbidden_url):
            url = default_redirect_url
        else:
            url = (next_url,)
        return redirect(*url)
    context = {"content": content, "model": content.class_name, "referer": request.META.get('HTTP_REFERER')}
    return render(request, "qnas/confirm-deletion.html", context)

@login_required
def delete_question(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    forbidden_url = request.build_absolute_uri(reverse("qnas:detail", args=[question.id]))
    return _del_content(request, question, "qnas:questions", forbidden_url=forbidden_url)

@login_required
def delete_answer(request, answer_id):
    answer = get_object_or_404(Answer, pk=answer_id)
    return _del_content(request, answer, "qnas:detail", answer.question.id)