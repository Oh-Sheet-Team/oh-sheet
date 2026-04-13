"""FakeRefineClient — typed fake for anthropic.AsyncAnthropic (D-11).

Mimics the subset of the Anthropic SDK that RefineService (Plan 03) uses.
Implemented as explicit dataclasses and hand-written methods (not
``unittest.mock`` objects) so that when the service's SDK surface
changes, attribute-access or signature drift surfaces at import time
rather than silently passing through auto-spec.

Usage pattern (Plans 03, 04, 05, 06):
    from tests.fakes.refine_client import FakeRefineClient, FakeParseResponse
    from shared.contracts import RefineEditOp

    edits = [RefineEditOp(op="delete", target_note_id="r-0005", rationale="ghost_note_removal")]
    parsed = RefinedEditOpList(edits=edits, citations=[])  # Pydantic, defined in Plan 03
    fake = FakeRefineClient(responses=[FakeParseResponse(parsed=parsed)])
    svc = RefineService(client=fake, validator=..., settings=...)
    result = await svc.run(perf, metadata={"title": "x", "composer": "y"})
    assert fake.calls[0]["model"] == "claude-sonnet-4-6"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeUsage:
    """Mirrors anthropic.types.Usage — only the two fields RefineService reads."""
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class FakeParseResponse:
    """Mirrors the subset of anthropic.types.Message that RefineService reads.

    ``parsed`` is typed Any because the service-layer type
    ``RefinedEditOpList`` is defined in Plan 03; this fake sits beneath
    the service and must remain agnostic.
    """
    parsed: Any
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)
    model: str = "claude-sonnet-4-6"
    content: list = field(default_factory=list)
    id: str = "msg_fake_001"


class FakeMessages:
    """Stand-in for ``anthropic.AsyncAnthropic().messages``."""

    def __init__(self, client: "FakeRefineClient") -> None:
        self._client = client

    async def parse(self, **kwargs: Any) -> FakeParseResponse:
        self._client.calls.append(dict(kwargs))
        if self._client._raise_on_call is not None:
            exc = self._client._raise_on_call
            # Raise once per call if raise_each_call, otherwise only first time.
            if not self._client.raise_each_call:
                self._client._raise_on_call = None
            raise exc
        if self._client._cursor >= len(self._client.responses):
            raise RuntimeError(
                f"FakeRefineClient exhausted after {self._client._cursor} calls "
                f"(queued {len(self._client.responses)} responses)"
            )
        resp = self._client.responses[self._client._cursor]
        self._client._cursor += 1
        return resp


class FakeRefineClient:
    """Typed fake replacement for anthropic.AsyncAnthropic (D-11).

    Parameters
    ----------
    responses:
        Queue of canned FakeParseResponse objects. Each ``messages.parse``
        call consumes one entry in order.
    raises:
        If set, the first parse call raises this exception instead of
        returning a queued response. Use for retry + skip-on-failure tests.
    raise_each_call:
        If True and ``raises`` is set, every call raises (not just the
        first). Useful for tenacity exhaustion tests.
    """

    def __init__(
        self,
        responses: list[FakeParseResponse] | None = None,
        raises: Exception | None = None,
        raise_each_call: bool = False,
    ) -> None:
        self.responses: list[FakeParseResponse] = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.raise_each_call = raise_each_call
        self._raise_on_call: Exception | None = raises
        self._cursor: int = 0
        self.messages = FakeMessages(self)

    @property
    def call_count(self) -> int:
        return len(self.calls)
