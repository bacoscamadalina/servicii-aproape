"""Explicit safe-read allowlist; excluded workflows cannot be reached or reversed."""

from django.conf.urls.i18n import i18n_patterns
from django.urls import include, path
from services import views

preview_patterns = [
    path('', views.home, name='home'),
    path('firme/<int:business_id>/', views.company_detail, name='company_detail'),
    path('api/localitati/', views.localities, name='localities'),
]
urlpatterns = i18n_patterns(
    path('', include((preview_patterns, 'services'))), prefix_default_language=False,
)
