from django.contrib import admin
from .models import (
    EmissionFactor, ActivityLog, Recommendation, Goal,
    EducationContent, GlossaryTerm, QAUsage
)

@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = ('category', 'subcategory', 'label', 'unit', 'kg_co2_per_unit')
    list_filter = ('category',)

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'factor', 'quantity', 'date', 'co2_kg')
    list_filter = ('factor__category', 'date')
    readonly_fields = ('co2_kg',)

@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ('category', 'action', 'potential_saving_kg', 'effort')
    list_filter = ('category', 'effort')

@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ('user', 'target_kg_per_month', 'updated_at')

@admin.register(EducationContent)
class EducationContentAdmin(admin.ModelAdmin):
    list_display = ('title', 'category')
    list_filter = ('category',)

@admin.register(GlossaryTerm)
class GlossaryTermAdmin(admin.ModelAdmin):
    list_display = ('term',)

@admin.register(QAUsage)
class QAUsageAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'count')
