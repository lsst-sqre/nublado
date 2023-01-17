from httpx import Response


class SpawnerError(Exception):
    def __init__(self, response: Response) -> None:
        self._response = response

    def __str__(self) -> str:
        r = self._response
        sc = r.status_code
        rp = r.reason_phrase
        txt = r.text
        url = r.url
        return f"Request for {url}: status code {sc} ({rp}): '{txt}'"
