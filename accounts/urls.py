from django.urls import path
from . import views

app_name = 'accounts'
urlpatterns = [
    path("logout/", views.logout, name="logout"),
    path("login/", views.login, name="login"),
    path("signup/", views.signup, name="signup"),
    path("users/<str:username>", views.profile, name="profile"),
    path("users/<str:username>/settings", views.settings, name="settings"),
    path("delete/user/<str:username>", views.delete_user, name="delete-user"),

]