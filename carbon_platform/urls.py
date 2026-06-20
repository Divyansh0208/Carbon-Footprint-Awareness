# pyrefly: ignore [missing-import]
from django.contrib import admin
# pyrefly: ignore [missing-import]
from django.urls import path, include
# pyrefly: ignore [missing-import]
from decouple import config

ADMIN_URL = config('ADMIN_URL', default='admin/')

urlpatterns = [
    path(ADMIN_URL, admin.site.urls),
    path('', include('core.urls')),
]