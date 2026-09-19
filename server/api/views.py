import os
from datetime import timedelta

from django.db import DatabaseError, connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, serializers, status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api import services
from api.models import ApprovedSpend, AuthorizationRecord, Decision, Mandate
from api.serializers import (
    MandateSerializer,
    MandateTightenSerializer,
    StepUpResolveSerializer,
    StepUpSerializer,
)
from viseca.client import VisecaAPIError, VisecaConnectionError

HealthSerializer = inline_serializer(
    name="Health",
    fields={
        "status": serializers.ChoiceField(choices=["ok", "error"]),
        "database": serializers.ChoiceField(choices=["ok", "error"]),
        "version": serializers.CharField(),
    },
)


def database_is_reachable() -> bool:
    """Return True if a trivial query against the default database succeeds."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return False
    return True


@extend_schema(responses={200: HealthSerializer, 503: HealthSerializer})
@api_view(["GET"])
def health(request: Request) -> Response:
    """Used by Render's health check, the CD smoke test, the app and the keep-alive pinger."""
    database_ok = database_is_reachable()
    return Response(
        {
            "status": "ok" if database_ok else "error",
            "database": "ok" if database_ok else "error",
            # Set by Render; lets the CD smoke test confirm that this exact commit is live.
            "version": os.environ.get("RENDER_GIT_COMMIT", "local"),
        },
        status=status.HTTP_200_OK if database_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@extend_schema(tags=["mandates"])
class MandateListView(generics.ListAPIView):
    """The customer's mandates, most recent first."""

    queryset = Mandate.objects.all()
    serializer_class = MandateSerializer


@extend_schema(tags=["mandates"])
class MandateDetailView(generics.RetrieveAPIView):
    """One mandate's current permissions, including guidance and open questions."""

    queryset = Mandate.objects.all()
    serializer_class = MandateSerializer


@extend_schema(
    tags=["mandates"],
    request=MandateTightenSerializer,
    responses={200: MandateSerializer, 400: MandateTightenSerializer},
)
class MandateTightenView(APIView):
    """Add hard rules and/or move uncertainty_policy towards stricter.

    Existing rules may not be removed or altered, only added to; uncertainty_policy
    may only move from approve/ask to decline. Violations are rejected with a 400.
    """

    def post(self, request: Request, pk: int) -> Response:
        mandate = get_object_or_404(Mandate, pk=pk)
        serializer = MandateTightenSerializer(data=request.data, context={"mandate": mandate})
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except services.MandateStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (VisecaAPIError, VisecaConnectionError) as exc:
            return Response(
                {"detail": f"The external challenge API rejected this change: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(MandateSerializer(mandate).data)


@extend_schema(
    tags=["mandates"],
    request=None,
    responses={200: MandateSerializer, 400: MandateSerializer},
)
class MandateRevokeView(APIView):
    """Withdraw permission: forward a revoke to the external API and move an
    active mandate to revoked locally."""

    def post(self, request: Request, pk: int) -> Response:
        mandate = get_object_or_404(Mandate, pk=pk)
        try:
            services.revoke_mandate(mandate)
        except services.MandateStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (VisecaAPIError, VisecaConnectionError) as exc:
            return Response(
                {"detail": f"The external challenge API rejected this revoke: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(MandateSerializer(mandate).data)


@extend_schema(
    tags=["mandates"],
    request=None,
    responses={200: MandateSerializer, 400: MandateSerializer},
)
class MandateConfirmView(APIView):
    """The customer agrees to a draft mandate: confirm it with the external
    API and activate the local record. Confirming anything that is not a
    draft is a clean 400.
    """

    def post(self, request: Request, pk: int) -> Response:
        mandate = get_object_or_404(Mandate, pk=pk)
        confirmed_by = request.data.get("confirmed_by", "") if hasattr(request.data, "get") else ""
        try:
            services.confirm_mandate(mandate, confirmed_by=confirmed_by)
        except services.MandateStateError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except (VisecaAPIError, VisecaConnectionError) as exc:
            return Response(
                {"detail": f"The external challenge API rejected this confirmation: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(MandateSerializer(mandate).data)


@extend_schema(tags=["step-ups"])
class StepUpListView(generics.ListAPIView):
    """The pending approval queue: purchases the customer can still answer, newest first.

    A step-up whose human window has closed is left out: the challenge API has
    already counted it as timed out, so it can no longer be approved or declined,
    and leaving it listed buries the purchases that still can.
    """

    serializer_class = StepUpSerializer

    def get_queryset(self):
        window_start = timezone.now() - timedelta(seconds=services.HUMAN_WINDOW_SECONDS)
        return (
            AuthorizationRecord.objects.pending_step_ups()
            .filter(latest_decision_at__gte=window_start)
            .select_related("run")
            .order_by("-latest_decision_at")
        )


@extend_schema(
    tags=["step-ups"],
    request=StepUpResolveSerializer,
    responses={200: StepUpSerializer, 400: StepUpResolveSerializer},
)
class StepUpResolveView(APIView):
    """The customer answers a pending step-up.

    Records the answer locally (as a `Decision` with `source=customer`) and leaves
    `forwarded_at` unset; a separate worker forwards it to the external challenge
    API. Resolving an already-resolved step-up is a clean 400.
    """

    def post(self, request: Request, pk: int) -> Response:
        authorization = get_object_or_404(AuthorizationRecord, pk=pk)
        serializer = StepUpResolveSerializer(
            data=request.data, context={"authorization": authorization}
        )
        serializer.is_valid(raise_exception=True)
        decision_value = serializer.validated_data["decision"]

        Decision.objects.create(
            authorization=authorization,
            decision=decision_value,
            source=Decision.Source.CUSTOMER,
            is_final=True,
            customer_message=serializer.validated_data.get("message", ""),
        )

        if decision_value == Decision.Value.APPROVE:
            ApprovedSpend.objects.create(
                authorization=authorization,
                mandate=authorization.run.mandate,
                amount_chf=authorization.billing_amount_chf,
                simulated_purchased_at=authorization.simulated_purchased_at,
            )

        return Response(StepUpSerializer(authorization).data)
