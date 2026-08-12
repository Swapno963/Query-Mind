from django.urls import path
from . import views

urlpatterns = [
    path("discover/", views.QueryView.as_view()),
]
