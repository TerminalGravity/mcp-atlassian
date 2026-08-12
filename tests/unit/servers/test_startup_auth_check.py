"""Startup credential verification.

Regression cover for the failure mode where an expired/revoked API token (or a
token minted under a different Atlassian account than JIRA_USERNAME) left the
server running happily and every Jira call returning an empty result that was
indistinguishable from a legitimate "no matches".
"""

from unittest.mock import MagicMock, patch

from mcp_atlassian.servers.main import _verify_jira_credentials


def _config() -> MagicMock:
    config = MagicMock()
    config.url = "https://example.atlassian.net"
    return config


def _patch_fetcher(myself_result=None, myself_error=None):
    fetcher = MagicMock()
    if myself_error is not None:
        fetcher.jira.myself.side_effect = myself_error
    else:
        fetcher.jira.myself.return_value = myself_result
    return patch("mcp_atlassian.servers.main.JiraFetcher", return_value=fetcher)


def _http_error(status: int) -> Exception:
    error = Exception(f"HTTP {status}")
    error.response = MagicMock()
    error.response.status_code = status
    return error


class TestVerifyJiraCredentials:
    def test_returns_identity_on_success(self):
        with _patch_fetcher({"emailAddress": "jfelke@example.com"}):
            assert _verify_jira_credentials(_config()) == "jfelke@example.com"

    def test_falls_back_through_identity_fields(self):
        with _patch_fetcher({"accountId": "712020:abc"}):
            assert _verify_jira_credentials(_config()) == "712020:abc"

    def test_returns_none_on_401(self):
        with _patch_fetcher(myself_error=_http_error(401)):
            assert _verify_jira_credentials(_config()) is None

    def test_returns_none_on_403(self):
        with _patch_fetcher(myself_error=_http_error(403)):
            assert _verify_jira_credentials(_config()) is None

    def test_returns_none_when_response_is_not_a_dict(self):
        # atlassian-python-api can return the raw non-JSON error body instead
        # of raising when the site rejects the credentials.
        with _patch_fetcher("Client must be authenticated to access this resource."):
            assert _verify_jira_credentials(_config()) is None

    def test_transport_failure_does_not_disable_tools(self):
        # A network blip at startup must not take Jira offline for the session.
        with _patch_fetcher(myself_error=ConnectionError("connection reset")):
            assert _verify_jira_credentials(_config()) == "unverified"
