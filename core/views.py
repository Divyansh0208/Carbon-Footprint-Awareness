from datetime import date, timedelta
# pyrefly: ignore [missing-import]
from django.contrib.auth import login
# pyrefly: ignore [missing-import]
from django.contrib.auth.decorators import login_required
# pyrefly: ignore [missing-import]
from django.contrib.auth.views import LoginView, LogoutView
# pyrefly: ignore [missing-import]
from django.contrib.auth.forms import AuthenticationForm
# pyrefly: ignore [missing-import]
from django.db.models import Sum
# pyrefly: ignore [missing-import]
from django.shortcuts import render, redirect, get_object_or_404
# pyrefly: ignore [missing-import]
from django.urls import reverse_lazy
# pyrefly: ignore [missing-import]
from django.http import JsonResponse

from .models import (
    ActivityLog, EmissionFactor, Recommendation, Goal,
    EducationContent, GlossaryTerm
)
from .forms import SignUpForm, ActivityLogForm, GoalForm, QuestionForm
from .services.llm import get_education_tip, answer_question, check_and_increment_qa_usage

# National average benchmarks (kg CO2/month) — placeholder approximations.
# Replace with sourced figures (e.g. DEFRA/EPA national stats) before production use.
NATIONAL_AVG = {
    'transport': 120.0,
    'energy': 200.0,
    'food': 150.0,
    'goods': 80.0,
}


# ---------- Auth ----------

def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = SignUpForm()
    return render(request, 'core/signup.html', {'form': form})


class NoColonAuthenticationForm(AuthenticationForm):
    label_suffix = ''


class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    authentication_form = NoColonAuthenticationForm


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('login')


# ---------- Helpers ----------

def _last_30_days_summary(user):
    start = date.today() - timedelta(days=30)
    logs = ActivityLog.objects.filter(user=user, date__gte=start)
    by_category = logs.values('factor__category').annotate(total=Sum('co2_kg'))
    summary = {row['factor__category']: round(row['total'], 1) for row in by_category}
    return summary


def _generate_insights(summary):
    insights = []
    for category, total in summary.items():
        avg = NATIONAL_AVG.get(category, 0)
        if avg and total > avg * 1.2:
            pct = round(((total - avg) / avg) * 100)
            insights.append(f"Your {category} emissions are {pct}% above the national average.")
        elif avg and total < avg * 0.8:
            insights.append(f"Your {category} emissions are well below average — nice work.")
    return insights


# ---------- Track pillar ----------

@login_required
def dashboard_view(request):
    summary = _last_30_days_summary(request.user)
    total = round(sum(summary.values()), 1) if summary else 0
    insights = _generate_insights(summary)

    logs = ActivityLog.objects.filter(user=request.user).order_by('-date')[:10]

    goal = Goal.objects.filter(user=request.user).first()
    progress_pct = None
    if goal and goal.target_kg_per_month:
        progress_pct = min(round((total / goal.target_kg_per_month) * 100), 999)

    chart_labels = list(summary.keys())
    chart_values = list(summary.values())

    context = {
        'summary': summary,
        'total': total,
        'insights': insights,
        'logs': logs,
        'goal': goal,
        'progress_pct': progress_pct,
        'chart_labels': chart_labels,
        'chart_values': chart_values,
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def log_activity_view(request):
    if request.method == 'POST':
        form = ActivityLogForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user = request.user
            entry.save()
            return redirect('dashboard')
    else:
        form = ActivityLogForm(initial={'date': date.today()})
    return render(request, 'core/log_activity.html', {'form': form})


def factor_options_partial(request):
    """htmx endpoint: returns <option> tags for the factor dropdown based on selected category."""
    category = request.GET.get('category')
    factors = EmissionFactor.objects.filter(category=category) if category else EmissionFactor.objects.none()
    return render(request, 'core/_factor_options.html', {'factors': factors})


# ---------- Understand pillar ----------

def learn_view(request):
    contents = EducationContent.objects.all()
    return render(request, 'core/learn.html', {'contents': contents})


def glossary_view(request):
    terms = GlossaryTerm.objects.all()
    return render(request, 'core/glossary.html', {'terms': terms})


@login_required
def qa_view(request):
    answer = None
    error = None
    if request.method == 'POST':
        form = QuestionForm(request.POST)
        if form.is_valid():
            if check_and_increment_qa_usage(request.user):
                summary = _last_30_days_summary(request.user)
                answer = answer_question(request.user, summary, form.cleaned_data['question'])
            else:
                error = "You've reached today's question limit. Please try again tomorrow."
    else:
        form = QuestionForm()
    return render(request, 'core/_qa_result.html', {'form': form, 'answer': answer, 'error': error})


# ---------- Reduce pillar ----------

@login_required
def insights_view(request):
    summary = _last_30_days_summary(request.user)
    insights = _generate_insights(summary)

    top_category = max(summary, key=summary.get) if summary else None
    recommendations = Recommendation.objects.filter(category=top_category) if top_category else Recommendation.objects.none()

    tip = None
    if summary:
        tip = get_education_tip(request.user, summary, NATIONAL_AVG)

    return render(request, 'core/insights.html', {
        'summary': summary,
        'insights': insights,
        'recommendations': recommendations,
        'top_category': top_category,
        'tip': tip,
    })


@login_required
def goal_view(request):
    goal, _ = Goal.objects.get_or_create(user=request.user, defaults={'target_kg_per_month': 300})
    if request.method == 'POST':
        form = GoalForm(request.POST, instance=goal)
        if form.is_valid():
            form.save()
            return redirect('dashboard')
    else:
        form = GoalForm(instance=goal)
    return render(request, 'core/goal.html', {'form': form, 'goal': goal})