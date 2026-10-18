"""What `canopy_sandbox.credentials` takes back from a sandboxed run's OpenCode logins (DESIGN §24).

The run writes its logins, so each check is a validator of untrusted input: it takes a refresh of a login the
operator has, and nothing else, and what it writes is always one OpenCode can read, since OpenCode drops a login it
cannot decode, and the whole of `mcp-auth.json` for one bad entry.
"""

import math
from typing import Any

import pytest
from canopy_sandbox import credentials
from hypothesis import given
from hypothesis import strategies as st

OAUTH = {
    "type": "oauth",
    "refresh": "refresh-1",
    "access": "access-1",
    "expires": 1_000,
    "accountId": "mine",
    "enterpriseUrl": "https://ghe.example.com",
}
MCP = {
    "tokens": {"accessToken": "mcp-1", "refreshToken": "mcp-refresh-1", "expiresAt": 100.5, "scope": "read"},
    "clientInfo": {"clientId": "mine"},
    "serverUrl": "https://mcp.example.com/mcp",
}
REFRESH = {"refresh": "refresh-2", "access": "access-2", "expires": 2_000}
TOKENS = {"accessToken": "mcp-2", "refreshToken": "mcp-refresh-2", "expiresAt": 200, "scope": "write"}

JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=5),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
    max_leaves=10,
)
# Near enough to a login that the checks are reached, with any field of any type.
SOME_TEXT = st.text(min_size=1, max_size=3)
TOKEN = SOME_TEXT | st.just("") | JSON
STAMP = st.integers(-1, 3_000) | st.floats(allow_nan=True) | st.booleans() | JSON
LOGIN = st.fixed_dictionaries(
    {
        "type": st.sampled_from(["oauth", "api", "wellknown"]) | JSON,
        "refresh": TOKEN,
        "access": TOKEN,
        "expires": STAMP,
    },
    optional={"accountId": JSON, "enterpriseUrl": JSON, "key": JSON, "token": JSON},
)
# A refresh, and whatever else a run puts beside its tokens.
REFRESHED = st.fixed_dictionaries(
    {"type": st.just("oauth"), "refresh": SOME_TEXT, "access": SOME_TEXT, "expires": st.integers(1_001, 10**15)},
    optional={"accountId": JSON, "enterpriseUrl": JSON, "key": JSON, "metadata": JSON},
)
MCP_TOKENS = st.fixed_dictionaries(
    {"accessToken": TOKEN, "expiresAt": STAMP}, optional={"refreshToken": TOKEN | st.none(), "scope": TOKEN}
)
MCP_LOGIN = st.fixed_dictionaries(
    {
        "tokens": MCP_TOKENS | JSON,
        "serverUrl": st.sampled_from([MCP["serverUrl"], "https://evil.example.com/mcp"]) | JSON,
    },
    optional={"clientInfo": JSON, "codeVerifier": JSON},
)
MCP_REFRESHED = st.fixed_dictionaries(
    {
        "tokens": st.fixed_dictionaries(
            {"accessToken": SOME_TEXT, "expiresAt": st.integers(101, 10**12) | st.floats(100.6, 1e12)},
            optional={"refreshToken": SOME_TEXT | st.none(), "scope": SOME_TEXT | st.none(), "extra": JSON},
        ),
        "serverUrl": st.just(MCP["serverUrl"]),
    },
    optional={"clientInfo": JSON, "codeVerifier": JSON, "oauthState": JSON},
)


@pytest.mark.parametrize(
    ("theirs", "taken"),
    [
        pytest.param({**OAUTH, **REFRESH}, {**OAUTH, **REFRESH}, id="a-refresh"),
        pytest.param(
            {**REFRESH, "type": "oauth", "accountId": "theirs", "enterpriseUrl": "https://evil.example.com"},
            {**OAUTH, **REFRESH},
            id="only-the-tokens",
        ),
        pytest.param({**OAUTH, **REFRESH, "expires": 1_000}, None, id="not-later"),
        pytest.param({**OAUTH, **REFRESH, "expires": 999}, None, id="earlier"),
        pytest.param({**OAUTH, **REFRESH, "expires": 2_000.5}, None, id="not-whole"),
        pytest.param({**OAUTH, **REFRESH, "expires": True}, None, id="a-bool"),
        pytest.param({**OAUTH, **REFRESH, "expires": "2000"}, None, id="a-string"),
        pytest.param({**OAUTH, **REFRESH, "refresh": ""}, None, id="an-empty-token"),
        pytest.param({**OAUTH, **REFRESH, "access": None}, None, id="no-token"),
        pytest.param({**OAUTH, **REFRESH, "access": "x" * (credentials.MAX_TOKEN + 1)}, None, id="a-huge-token"),
        pytest.param({**REFRESH, "type": "wellknown", "key": "https://evil.example.com", "token": "t"}, None),
        pytest.param({"type": "api", "key": "theirs"}, None, id="an-api-key"),
        pytest.param([OAUTH], None, id="not-an-object"),
    ],
)
def test_a_login_is_taken_back_only_when_it_is_a_later_oauth_refresh(theirs: object, taken: object) -> None:
    assert credentials.refreshed_login(OAUTH, theirs) == taken


@pytest.mark.parametrize("ours", [{"type": "api", "key": "mine"}, {**OAUTH, "expires": None}, "oauth", None])
def test_only_an_oauth_login_with_an_expiry_takes_a_refresh(ours: object) -> None:
    assert credentials.refreshed_login(ours, {**OAUTH, **REFRESH}) is None


@pytest.mark.parametrize(
    ("theirs", "taken"),
    [
        pytest.param({**MCP, "tokens": TOKENS}, {**MCP, "tokens": TOKENS}, id="a-refresh"),
        pytest.param(
            {"tokens": {**TOKENS, "extra": "x"}, "serverUrl": MCP["serverUrl"], "clientInfo": {"clientId": "theirs"}},
            {**MCP, "tokens": TOKENS},
            id="only-the-tokens",
        ),
        pytest.param(
            {**MCP, "tokens": {"accessToken": "mcp-2", "expiresAt": 200}},
            {
                **MCP,
                "tokens": {"accessToken": "mcp-2", "refreshToken": "mcp-refresh-1", "expiresAt": 200, "scope": "read"},
            },
            id="a-refresh-that-sends-no-refresh-token",
        ),
        pytest.param({**MCP, "tokens": {**TOKENS, "expiresAt": 100.5}}, None, id="not-later"),
        pytest.param({**MCP, "tokens": {**TOKENS, "expiresAt": float("inf")}}, None, id="infinite"),
        pytest.param({**MCP, "tokens": {**TOKENS, "expiresAt": False}}, None, id="a-bool"),
        pytest.param({**MCP, "tokens": {**TOKENS, "refreshToken": 7}}, None, id="a-number-for-a-token"),
        pytest.param({**MCP, "tokens": {**TOKENS, "scope": ["read"]}}, None, id="a-list-for-a-scope"),
        pytest.param({**MCP, "tokens": TOKENS, "serverUrl": "https://evil.example.com/mcp"}, None, id="another-url"),
        pytest.param({"tokens": TOKENS}, None, id="no-url"),
        pytest.param({**MCP, "tokens": [TOKENS]}, None, id="tokens-not-an-object"),
    ],
)
def test_an_mcp_login_is_taken_back_only_when_it_is_a_later_refresh_for_the_same_server(
    theirs: object, taken: object
) -> None:
    assert credentials.refreshed_mcp_login(MCP, theirs) == taken


def test_an_mcp_login_that_never_expires_takes_no_refresh() -> None:
    ours = {**MCP, "tokens": {"accessToken": "mcp-1"}}

    assert credentials.refreshed_mcp_login(ours, {**MCP, "tokens": TOKENS}) is None


@given(theirs=st.one_of(REFRESHED, LOGIN, JSON))
def test_whatever_a_run_writes_a_login_taken_back_is_ours_with_its_tokens_alone(theirs: object) -> None:
    """The fields that say where a token goes and whose it is stay the operator's, and the entry stays one OpenCode
    decodes: an OAuth login with string tokens and a whole, later expiry."""
    taken = credentials.refreshed_login(OAUTH, theirs)

    if taken is not None:
        changed = {k for k in OAUTH if taken[k] != OAUTH[k]}
        assert taken.keys() == OAUTH.keys()
        assert changed <= {"refresh", "access", "expires"}
        assert is_token(taken["refresh"])
        assert is_token(taken["access"])
        expires: Any = taken["expires"]
        assert type(expires) is int
        assert expires > OAUTH["expires"]


@given(theirs=st.one_of(MCP_REFRESHED, MCP_LOGIN, JSON))
def test_whatever_a_run_writes_an_mcp_login_taken_back_is_ours_with_its_tokens_alone(theirs: object) -> None:
    taken = credentials.refreshed_mcp_login(MCP, theirs)

    if taken is not None:
        assert {k: v for k, v in taken.items() if k != "tokens"} == {k: v for k, v in MCP.items() if k != "tokens"}
        tokens: Any = taken["tokens"]
        assert set(tokens) <= {"accessToken", "refreshToken", "expiresAt", "scope"}
        assert "accessToken" in tokens
        assert all(is_token(tokens[k]) for k in ("accessToken", "refreshToken", "scope") if k in tokens)
        assert type(tokens["expiresAt"]) in {int, float}
        assert math.isfinite(tokens["expiresAt"])  # OpenCode reads JSON, which has no infinity
        assert tokens["expiresAt"] > MCP["tokens"]["expiresAt"]


def is_token(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= credentials.MAX_TOKEN
