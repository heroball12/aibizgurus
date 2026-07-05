from django.urls import path
from . import views
urlpatterns = [
    path("healthz/", views.healthz, name="healthz"),
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("", views.home, name="home"),
    path("solutions/", views.solutions, name="solutions"),
    path("solutions/<slug:slug>/", views.solution_detail, name="solution_detail"),
    path("ai-employees/", views.ai_employees, name="ai_employees"),
    path("industries/", views.industries, name="industries"),
    path("demo/", views.demo, name="demo"),
    path("pricing/", views.pricing, name="pricing"),
    path("case-studies/", views.case_studies, name="case_studies"),
    path("growth-assessment/", views.growth_assessment, name="growth_assessment"),
    path("request-consultation/", views.consultation_request, name="consultation_request"),
]
