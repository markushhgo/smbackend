import pytest
from rest_framework.reverse import reverse
from django.conf import settings
from django.test import override_settings


@override_settings(CACHES=settings.TEST_CACHES)
@pytest.mark.django_db
def test_api(api_client, iot_data, iot_data_source):
    url = reverse("iot") + "?source_name=S42"
    response = api_client.get(url)
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["data"] == {"test": 42}
    assert results[1]["data"] == {"Even more test": "Data"}
