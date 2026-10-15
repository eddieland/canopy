from tests import prompt_sizes


def test_no_bundled_prompt_or_definition_grew_past_its_limit() -> None:
    grown = {
        path: f"{prompt_sizes.LIMITS[path]} -> {chars}"
        for path, chars in prompt_sizes.sizes().items()
        if chars > prompt_sizes.LIMITS.get(path, chars)
    }
    assert not grown, (
        f"grew past its recorded size, in characters: {grown}. If the growth is meant, raise its entry in LIMITS in"
        " tests/prompt_sizes.py; `make prompt-sizes` prints every file's size"
    )


def test_every_bundled_prompt_and_definition_has_a_limit() -> None:
    # A new file is held from its first PR, and a renamed or removed one does not leave a limit that holds nothing.
    measured = set(prompt_sizes.sizes())
    assert measured - set(prompt_sizes.LIMITS) == set(), "add these to LIMITS in tests/prompt_sizes.py"
    assert set(prompt_sizes.LIMITS) - measured == set(), "remove these from LIMITS in tests/prompt_sizes.py"
