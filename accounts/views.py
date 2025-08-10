from itertools import chain

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import render, get_object_or_404
from django.shortcuts import redirect
from django.contrib import auth
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required

from qnas.models import Question, Answer


def signup(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth.login(request, user)
            return redirect("qnas:index")
    else:
        form = UserCreationForm()
    context = {'form': form, 'errors': form.errors}
    return render(request, 'registration/signup.html', context)

def login(request):
    error = ""
    if request.method == 'POST':
        user = auth.authenticate(username=request.POST['username'], password=request.POST['password'])
        if user:
            auth.login(request, user)
            return redirect('qnas:index')
        if get_user_model().objects.filter(username=request.POST["username"]):
            error = "The password you entered is incorrect."
        else:
            error = "The username you entered isn't connected to an account."
    context = {'form':AuthenticationForm(), "error": error}
    return render(request, 'registration/login.html', context)

@login_required
def logout(request):
    auth.logout(request)
    return redirect('qnas:index')

def _get_profile_view_context(tab, all_questions, all_answers, user):
    def get_voted_posts(post_type, vote=1): return post_type.objects.filter(votes__user=user, votes__value=vote)
    def latest(content): return content.pub_date
    if not tab:
        tab = "overview"
    if tab.lower() == "questions":
        contents = all_questions
    elif tab.lower() == "answers":
        contents = all_answers
    elif tab.lower() == "upvoted":
        contents = sorted(chain(get_voted_posts(Question), get_voted_posts(Answer)), key=latest, reverse=True)
    elif tab.lower() == "downvoted":
        contents = sorted(chain(get_voted_posts(Question, -1), get_voted_posts(Answer, -1)), key=latest, reverse=True)
    else:
        contents = sorted(chain(all_questions, all_answers), key=latest, reverse=True)
    return contents

def profile(request, username):
    profile_owner = get_object_or_404(get_user_model(), username=username)
    all_questions = Question.objects.filter(author=profile_owner)
    all_answers = Answer.objects.filter(author=profile_owner)
    tab = request.GET.get("tab")
    contents = _get_profile_view_context(tab, all_questions, all_answers, profile_owner)
    context = {'profile_owner': profile_owner, "contents": contents}
    return render(request, "accounts/profile.html", context)

def _validate_password_change(user, current_password, new_password):
    error_dict = {}
    if current_password and new_password:
        if user:
            try:
                validate_password(new_password)
            except ValidationError as e:
                error_dict = {"triggered_by": "new password", "errors": e.messages}
            else:
                user.set_password(new_password)
                user.save()
        else:
            error_dict = {"triggered_by": "current password", "errors": ["Incorrect password"]}
    elif current_password or new_password:
        error_dict = {"triggered_by": "both", "errors": ["Missing current or new password"]}
    return error_dict

@login_required
def settings(request, username):
    if request.user.username != username:
        raise Http404
    context = {"username": username}
    if request.method == 'POST':
        current_password, new_password = request.POST.get("current-password"), request.POST.get("new-password")
        user = auth.authenticate(username=username, password=current_password)
        error_dict = _validate_password_change(user, current_password, new_password)
        if (current_password or new_password) and not error_dict:
            auth.login(request, user)
            return redirect("accounts:profile", username)
        context.update({"error_dict": error_dict})
    return render(request, "accounts/settings.html", context)

@login_required
def delete_user(request, username):
    if request.user.username != username:
        raise Http404
    user = get_object_or_404(get_user_model(), username=username)
    if request.method == "POST":
        user.delete()
        return redirect("qnas:index")
    context = {"answer": user, "model": "Account"}
    return render(request, "qnas/confirm-deletion.html", context)