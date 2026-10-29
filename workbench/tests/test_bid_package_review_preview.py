from packages.domain.bid_package_review_policy import physical_gaps


def test_shared_ranges_are_unioned_without_hiding_unassigned_physical_pages():
    package = {
        "members": [
            {
                "member_id": "one",
                "page_count": 9,
                "parts": [
                    {"first_page": 1, "last_page": 3},
                    {"first_page": 2, "last_page": 5},
                    {"first_page": 7, "last_page": 8},
                ],
            }
        ]
    }
    assert physical_gaps(package, "target") == [
        {"role": "target", "member_id": "one", "first_page": 6, "last_page": 6},
        {"role": "target", "member_id": "one", "first_page": 9, "last_page": 9},
    ]


def test_unknown_page_count_does_not_invent_page_numbers_and_empty_parts_keep_entire_gap():
    assert (
        physical_gaps(
            {"members": [{"member_id": "unknown", "page_count": None, "parts": []}]}, "authority"
        )
        == []
    )
    assert physical_gaps(
        {"members": [{"member_id": "empty", "page_count": 9007199254740991, "parts": []}]},
        "authority",
    ) == [
        {"role": "authority", "member_id": "empty", "first_page": 1, "last_page": 9007199254740991}
    ]
