# pyrefly: ignore [missing-import]
from django import forms
# pyrefly: ignore [missing-import]
from django.contrib.auth.forms import UserCreationForm
# pyrefly: ignore [missing-import]
from django.contrib.auth.models import User
from .models import ActivityLog, EmissionFactor, Goal


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    label_suffix = ''

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')


class ActivityLogForm(forms.ModelForm):
    category = forms.ChoiceField(choices=EmissionFactor.CATEGORY_CHOICES)
    factor = forms.ModelChoiceField(queryset=EmissionFactor.objects.all(), label="Activity type")

    class Meta:
        model = ActivityLog
        fields = ['category', 'factor', 'quantity', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If a category was posted, narrow the factor choices (used with htmx)
        if 'category' in self.data:
            try:
                category = self.data.get('category')
                self.fields['factor'].queryset = EmissionFactor.objects.filter(category=category)
            except (ValueError, TypeError):
                pass


class GoalForm(forms.ModelForm):
    label_suffix = ''

    class Meta:
        model = Goal
        fields = ['target_kg_per_month']


class QuestionForm(forms.Form):
    question = forms.CharField(
        max_length=300,
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Why is beef worse than chicken?'})
    )