"""`familiarity_from_rows` is the one definition of "a shop I use regularly".

The offline replay command and the production worker must count familiarity
the same way, or the replay loop stops predicting what the worker will do.
"""

from __future__ import annotations

from api.services import familiarity_from_rows

_ROWS = [
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
    {
        "card_id": "CA0001",
        "status": "declined",
        "merchant_id": "ME0002",
        "customer_device_id": "DVC-2",
    },
    {
        "card_id": "CA0099",
        "status": "approved",
        "merchant_id": "ME0003",
        "customer_device_id": "DVC-3",
    },
]


def test_counts_only_approved_rows_for_the_named_card() -> None:
    merchants, devices = familiarity_from_rows(_ROWS, "CA0001")
    assert merchants == {"ME0001": 2}, "declined rows and other cards must not count"
    assert devices == {"DVC-1": 2}


def test_unknown_card_has_no_history() -> None:
    assert familiarity_from_rows(_ROWS, "CA1234") == ({}, {})


def test_blank_card_id_is_not_a_wildcard() -> None:
    assert familiarity_from_rows(_ROWS, "") == ({}, {})
