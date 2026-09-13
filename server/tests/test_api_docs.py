from django.urls import reverse


def test_openapi_schema_documents_health_endpoint(api_client):
    response = api_client.get(reverse("schema"), HTTP_ACCEPT="application/vnd.oai.openapi+json")

    assert response.status_code == 200
    assert "/health/" in response.json()["paths"]
