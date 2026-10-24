# -*- coding: utf-8 -*-
"""URLConf только для тестов Django-интеграции."""

from django.urls import path

from kremle_detect.integrations.django_ext import kremle_urls

urlpatterns = [
    path('kremle/', kremle_urls()),
]
