from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="training_home"),
    path("history/", views.history, name="training_history"),
    path("modules/<int:pk>/revision/", views.revision, name="training_revision"),
    path("modules/<int:pk>/", views.lesson, name="training_lesson"),
    path("modules/<int:pk>/asset/<str:kind>/", views.asset, name="training_asset"),
    path("modules/<int:pk>/progress/", views.progress, name="training_progress"),
    path("modules/<int:pk>/quiz/", views.quiz_submit, name="training_quiz"),
    path(
        "modules/<int:pk>/publication/", views.publication, name="training_publication"
    ),
    path(
        "scenarios/<int:pk>/start/",
        views.practice_start,
        name="training_practice_start",
    ),
    path("practice/<uuid:pk>/", views.practice, name="training_practice"),
    path(
        "practice/<uuid:pk>/turn/", views.practice_turn, name="training_practice_turn"
    ),
    path(
        "practice/<uuid:pk>/finish/",
        views.practice_finish,
        name="training_practice_finish",
    ),
    path("proctor/start/", views.proctor_start, name="training_proctor_start"),
    path("proctor/<uuid:pk>/", views.proctor_room, name="training_proctor"),
    path("manage/", views.management, name="training_management"),
    path("manage/assign/", views.assign, name="training_assign"),
    path("manage/<int:pk>/", views.employee_record, name="training_employee"),
    path(
        "manage/<int:pk>/action/", views.manager_action, name="training_manager_action"
    ),
]
