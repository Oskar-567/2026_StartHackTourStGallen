"""`api.services.build_engine_state` -- windowing on the simulated clock,
merchant/device familiarity, and combining historical + this-run data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from api import services
from api.models import ApprovedSpend
from tests.factories import make_authorization, make_mandate, make_run


def _raw_event(*, authorization_id, card_id, merchant_id, merchant_name, device_id) -> dict:
    return {
        "type": "authorization.request",
        "authorization": {
            "authorization_id": authorization_id,
            "card_id": card_id,
            "merchant": {
                "merchant_id": merchant_id,
                "merchant_name": merchant_name,
                "merchant_country": "CH",
            },
            "customer_device_id": device_id,
            "purchase_description": "Test purchase",
            "items": [{"item_category": "groceries"}],
        },
    }


def _approve(authorization, mandate) -> None:
    ApprovedSpend.objects.create(
        authorization=authorization,
        mandate=mandate,
        amount_chf=authorization.billing_amount_chf,
        simulated_purchased_at=authorization.simulated_purchased_at,
    )


@pytest.fixture(autouse=True)
def _empty_history_cache(monkeypatch):
    """No network call: pretend the historical CSV was already fetched and cached."""
    monkeypatch.setattr(services, "_history_rows_cache", [])


@pytest.mark.django_db
def test_recent_approved_purchases_excludes_purchases_after_the_current_event_in_simulated_time():
    mandate = make_mandate()
    run = make_run(mandate=mandate)
    current_ts = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    earlier = make_authorization(
        run=run,
        authorization_id="AU_EARLIER",
        raw_event=_raw_event(
            authorization_id="AU_EARLIER",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 8, 10, 11, 0, tzinfo=UTC),
        billing_amount_chf=Decimal("15.00"),
    )
    _approve(earlier, mandate)

    later = make_authorization(
        run=run,
        authorization_id="AU_LATER",
        raw_event=_raw_event(
            authorization_id="AU_LATER",
            card_id="CA0001",
            merchant_id="ME0002",
            merchant_name="Neighbour Pantry",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 8, 10, 13, 0, tzinfo=UTC),
        billing_amount_chf=Decimal("10.00"),
    )
    _approve(later, mandate)

    current = make_authorization(
        run=run,
        authorization_id="AU_CURRENT",
        raw_event=_raw_event(
            authorization_id="AU_CURRENT",
            card_id="CA0001",
            merchant_id="ME0003",
            merchant_name="Some Shop",
            device_id="DVC-1",
        ),
        simulated_purchased_at=current_ts,
        billing_amount_chf=Decimal("20.00"),
    )

    state = services.build_engine_state(run, current)

    ids_in_state = {p.authorization_id for p in state.recent_approved_purchases}
    assert ids_in_state == {"AU_EARLIER"}
    assert "AU_LATER" not in ids_in_state


@pytest.mark.django_db
def test_seen_authorization_ids_excludes_only_the_current_authorization():
    mandate = make_mandate()
    run = make_run(mandate=mandate)
    other = make_authorization(
        run=run,
        authorization_id="AU_OTHER",
        raw_event=_raw_event(
            authorization_id="AU_OTHER",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
    )
    current = make_authorization(
        run=run,
        authorization_id="AU_CURRENT",
        raw_event=_raw_event(
            authorization_id="AU_CURRENT",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
    )

    state = services.build_engine_state(run, current)

    assert state.seen_authorization_ids == {other.authorization_id}


@pytest.mark.django_db
def test_known_merchant_and_device_counts_combine_history_with_this_runs_approvals(monkeypatch):
    monkeypatch.setattr(
        services,
        "_history_rows_cache",
        [
            {
                "card_id": "CA0001",
                "status": "approved",
                "merchant_id": "ME0001",
                "customer_device_id": "DVC-1",
            },
            {
                "card_id": "CA0001",
                "status": "approved",
                "merchant_id": "ME0001",
                "customer_device_id": "DVC-1",
            },
            # Different card: must not be counted.
            {
                "card_id": "CA9999",
                "status": "approved",
                "merchant_id": "ME0001",
                "customer_device_id": "DVC-1",
            },
            # Declined: must not be counted.
            {
                "card_id": "CA0001",
                "status": "declined",
                "merchant_id": "ME0001",
                "customer_device_id": "DVC-1",
            },
        ],
    )
    mandate = make_mandate()
    run = make_run(mandate=mandate)
    prior = make_authorization(
        run=run,
        authorization_id="AU_PRIOR",
        raw_event=_raw_event(
            authorization_id="AU_PRIOR",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 8, 10, 11, 0, tzinfo=UTC),
    )
    _approve(prior, mandate)
    current = make_authorization(
        run=run,
        authorization_id="AU_CURRENT",
        raw_event=_raw_event(
            authorization_id="AU_CURRENT",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
    )

    state = services.build_engine_state(run, current)

    # 2 historical approved rows for this card+merchant + 1 approved this run.
    assert state.known_merchant_ids["ME0001"] == 3
    assert state.known_device_ids["DVC-1"] == 3


@pytest.mark.django_db
def test_approved_spend_in_period_chf_is_a_month_to_date_sum_on_the_simulated_clock():
    mandate = make_mandate()
    run = make_run(mandate=mandate)

    same_month = make_authorization(
        run=run,
        authorization_id="AU_SAME_MONTH",
        raw_event=_raw_event(
            authorization_id="AU_SAME_MONTH",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 8, 3, 9, 0, tzinfo=UTC),
        billing_amount_chf=Decimal("40.00"),
    )
    _approve(same_month, mandate)

    previous_month = make_authorization(
        run=run,
        authorization_id="AU_PREV_MONTH",
        raw_event=_raw_event(
            authorization_id="AU_PREV_MONTH",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 7, 28, 9, 0, tzinfo=UTC),
        billing_amount_chf=Decimal("999.00"),
    )
    _approve(previous_month, mandate)

    current = make_authorization(
        run=run,
        authorization_id="AU_CURRENT",
        raw_event=_raw_event(
            authorization_id="AU_CURRENT",
            card_id="CA0001",
            merchant_id="ME0001",
            merchant_name="Alpine Basket",
            device_id="DVC-1",
        ),
        simulated_purchased_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        billing_amount_chf=Decimal("20.00"),
    )

    state = services.build_engine_state(run, current)

    assert state.approved_spend_in_period_chf == Decimal("40.00")
