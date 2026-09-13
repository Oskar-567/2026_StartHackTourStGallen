import os

from django.db import DatabaseError, connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

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
