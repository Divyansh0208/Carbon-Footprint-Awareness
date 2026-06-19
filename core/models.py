from django.db import models
from django.contrib.auth.models import User


class EmissionFactor(models.Model):
    CATEGORY_CHOICES = [
        ('transport', 'Transport'),
        ('energy', 'Energy'),
        ('food', 'Food'),
        ('goods', 'Goods'),
    ]
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    subcategory = models.CharField(max_length=50)  # e.g. car_petrol, flight_short_haul, beef
    label = models.CharField(max_length=100)        # human-readable, e.g. "Petrol car (per km)"
    unit = models.CharField(max_length=20)           # km, kWh, kg, item
    kg_co2_per_unit = models.FloatField()

    class Meta:
        unique_together = ('category', 'subcategory')
        ordering = ['category', 'subcategory']

    def __str__(self):
        return f"{self.label} ({self.kg_co2_per_unit} kg CO2e/{self.unit})"


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_logs')
    factor = models.ForeignKey(EmissionFactor, on_delete=models.PROTECT)
    quantity = models.FloatField()
    date = models.DateField()
    co2_kg = models.FloatField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        self.co2_kg = self.quantity * self.factor.kg_co2_per_unit
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.factor.label} - {self.date}"


class Recommendation(models.Model):
    EFFORT_CHOICES = [('low', 'Low'), ('med', 'Medium'), ('high', 'High')]
    category = models.CharField(max_length=50, choices=EmissionFactor.CATEGORY_CHOICES)
    action = models.TextField()
    potential_saving_kg = models.FloatField(help_text="Estimated kg CO2 saved per month")
    effort = models.CharField(max_length=10, choices=EFFORT_CHOICES)

    class Meta:
        ordering = ['category', 'effort']

    def __str__(self):
        return f"[{self.category}] {self.action[:50]}"


class Goal(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='goal')
    target_kg_per_month = models.FloatField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} target: {self.target_kg_per_month} kg/month"


class EducationContent(models.Model):
    category = models.CharField(max_length=50, choices=EmissionFactor.CATEGORY_CHOICES)
    title = models.CharField(max_length=200)
    body = models.TextField()
    fun_fact = models.TextField(blank=True, help_text="Short contextual tip shown at log-time")

    class Meta:
        ordering = ['category']

    def __str__(self):
        return self.title


class GlossaryTerm(models.Model):
    term = models.CharField(max_length=100, unique=True)
    definition = models.TextField()

    class Meta:
        ordering = ['term']

    def __str__(self):
        return self.term


class QAUsage(models.Model):
    """Tracks daily Q&A usage per user for rate-limiting (free-tier credit protection)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    count = models.IntegerField(default=0)

    class Meta:
        unique_together = ('user', 'date')
