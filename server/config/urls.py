from django.contrib import admin
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from api.views import (
    MandateConfirmView,
    MandateDetailView,
    MandateListView,
    MandateRevokeView,
    MandateTightenView,
    StepUpListView,
    StepUpResolveView,
    health,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/mandates/", MandateListView.as_view(), name="mandate-list"),
    path("api/mandates/<int:pk>/", MandateDetailView.as_view(), name="mandate-detail"),
    path("api/mandates/<int:pk>/confirm/", MandateConfirmView.as_view(), name="mandate-confirm"),
    path("api/mandates/<int:pk>/tighten/", MandateTightenView.as_view(), name="mandate-tighten"),
    path("api/mandates/<int:pk>/revoke/", MandateRevokeView.as_view(), name="mandate-revoke"),
    path("api/step-ups/", StepUpListView.as_view(), name="step-up-list"),
    path("api/step-ups/<int:pk>/resolve/", StepUpResolveView.as_view(), name="step-up-resolve"),
]
