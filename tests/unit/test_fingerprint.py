from app.domain.fingerprint import hash_source, payload_fingerprint


def test_hash_source_is_stable() -> None:
    assert hash_source("first string") == hash_source("first string")


def test_hash_source_is_case_sensitive() -> None:
    assert hash_source("first string") != hash_source("FIRST STRING")


def test_hash_source_handles_non_ascii() -> None:
    assert len(hash_source("перший рядок")) == 64


def test_payload_fingerprint_is_stable_for_the_same_input() -> None:
    first, second = ["a", "b"], ["x", "y"]

    assert payload_fingerprint(first, second) == payload_fingerprint(first, second)


def test_payload_fingerprint_depends_on_which_list_is_which() -> None:
    assert payload_fingerprint(["a"], ["x"]) != payload_fingerprint(["x"], ["a"])


def test_payload_fingerprint_depends_on_item_order() -> None:
    assert payload_fingerprint(["a", "b"], ["x", "y"]) != payload_fingerprint(
        ["b", "a"], ["x", "y"]
    )


def test_payload_fingerprint_does_not_confuse_item_boundaries() -> None:
    """A string containing the separator must not collide with two strings."""
    assert payload_fingerprint(["a,b"], ["x"]) != payload_fingerprint(["a", "b"], ["x"])


def test_payload_fingerprint_depends_on_list_2() -> None:
    """Guards the collision mutation testing found: a fingerprint that ignored
    list_2 entirely passed every other test in this file."""
    assert payload_fingerprint(["a"], ["x"]) != payload_fingerprint(["a"], ["y"])


def test_payload_fingerprint_depends_on_item_order_in_list_2() -> None:
    assert payload_fingerprint(["a", "b"], ["x", "y"]) != payload_fingerprint(
        ["a", "b"], ["y", "x"]
    )
