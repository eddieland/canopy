# canopy-http

The HTTP client the programs canopy ships use for every request they make (D130): today the GitHub programs
(`canopy-github`) and the Jira connector (`canopy-jira`). It is a library, with no command of its own, and imports
nothing from canopy. The harness never uses it: it opens no connection and holds no token (TRUST_MODEL T2).

```python
import canopy_http

client = canopy_http.Client("https://api.github.com", name="GitHub", headers={"Authorization": f"Bearer {token}"})
data = client.json("POST", "/graphql", body={"query": QUERY}, again=True)
```

What it promises:

- **One origin.** A `Client` is bound to the origin it is made with. A URL naming another is refused before it is
  sent, and a redirect is never followed, so a credential in its headers goes nowhere else.
- **The system's certificates**, so an Enterprise host with its own CA works, and the environment's proxy
  (`HTTPS_PROXY`) and certificates (`SSL_CERT_FILE`).
- **One account of what went wrong.** Every failure is an `HttpError`, and its `certain` says whether the request is
  known not to have been carried out, so a caller knows whether sending it again could do it twice:

  | Error              | When                                                     | `certain` |
  | ------------------ | -------------------------------------------------------- | --------- |
  | `RefusedError`     | a 4xx, or a redirect                                     | yes       |
  | `RateLimitedError` | a 429, or a 403 naming `Retry-After`                     | yes       |
  | `NotSentError`     | no connection could be made                              | yes       |
  | `UntrustedError`   | the service's certificate is not one the system trusts   | yes       |
  | `FailedError`      | a server error, or a reply that broke off or is not JSON | no        |
  | `TimedOutError`    | no answer in time                                        | no        |

- **Retries only where safe.** A request is sent again, after each of `Retry.pauses`, when that cannot do it twice:
  it never left, or the service refused it and said how long to wait, for no longer than `Retry.longest_wait`. One
  sent with `again=True`, as a read is, is also sent again after a failure that may have been carried out. A timed-out
  request is never sent again.

`send` returns the 2xx `Reply`; `json` asks for JSON and returns it parsed. httpx2 is the transport.
