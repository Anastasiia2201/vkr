from django.contrib import admin
from .models import LandPlot


@admin.register(LandPlot)
class LandPlotAdmin(admin.ModelAdmin):
    list_display = ("cadastral_number", "area_hectares",)
    search_fields = ("cadastral_number",)
