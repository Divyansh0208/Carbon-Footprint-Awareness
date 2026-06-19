from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),

    # Track
    path('', views.dashboard_view, name='dashboard'),
    path('log/', views.log_activity_view, name='log_activity'),
    path('log/factor-options/', views.factor_options_partial, name='factor_options'),

    # Understand
    path('learn/', views.learn_view, name='learn'),
    path('glossary/', views.glossary_view, name='glossary'),
    path('qa/', views.qa_view, name='qa'),

    # Reduce
    path('insights/', views.insights_view, name='insights'),
    path('goal/', views.goal_view, name='goal'),
]
