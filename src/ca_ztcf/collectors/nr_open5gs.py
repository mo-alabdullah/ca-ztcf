"""Live 5G access-context collector for the Tier-2 software-based testbed.

Consumes events produced by a running Open5GS core with UERANSIM attached, and
normalises them into the existing ``AccessBinding`` schema so that everything
downstream — evidence, predicates, trust engine, policy — is unchanged.

**Provenance.** Events carry ``source_mode = live_testbed`` with
``access_implementation = ueransim`` and ``testbed_type = software_based``.

UERANSIM speaks real 5G NAS, NGAP and GTP-U to Open5GS and creates a real TUN
interface for user-plane traffic. The protocol interaction is genuine. **The radio
is not**: there is no physical RF anywhere in this testbed. Results from it may be
used as evidence about protocol and session transitions, authentication, trust
evaluation, policy enforcement, application continuity and software latency. They
may **not** be used to claim RF propagation performance, physical handover timing
over real radios, interference, channel quality or spectrum coexistence.

**Identity discipline.** The SUPI/IMSI is an access-domain identifier. It is
hashed with this collector's own salt before it reaches a binding and is never
compared with any WLAN identifier, and never used as the CA-ZTCF device identity.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ca_ztcf.collectors.base import AccessImplementation, InfrastructureKind, SourceMode
from ca_ztcf.collectors.nr import NrAccessEvent, NrEventType
from ca_ztcf.errors import CollectorError

LIVE_SOURCE_MODE = SourceMode.LIVE_TESTBED
ACCESS_IMPLEMENTATION = AccessImplementation.UERANSIM
TESTBED_TYPE = InfrastructureKind.SOFTWARE_BASED

# Open5GS AMF, SMF and UPF log formats.
#
# These patterns were derived by reading a RUNNING Open5GS 2.8.0 core with
# UERANSIM attached, not by assuming what the logs would look like. Where the
# real format differed from the earlier synthetic fixture, the fixture was wrong
# and this collector follows reality. See docs/adr/ADR-0008.

# SMF, on PDU session establishment. This is the authoritative source of the
# SUPI-to-UE-address binding:
#   [smf] INFO: UE SUPI[imsi-999700000000001] DNN[internet] IPv4[10.45.0.2] IPv6[]
_SMF_SESSION = re.compile(
    r"UE SUPI\[(?P<supi>imsi-\d+)\]\s+DNN\[(?P<dnn>[^\]]*)\]\s+IPv4\[(?P<ip>[\d.]*)\]", re.I
)

# UPF, on session creation:
#   UE F-SEID[...] APN[internet] PDN-Type[1] IPv4[10.45.0.2] IPv6[]
_UPF_SESSION = re.compile(
    r"APN\[(?P<dnn>[^\]]*)\]\s+PDN-Type\[\d+\]\s+IPv4\[(?P<ip>[\d.]+)\]", re.I
)

# AMF, on registration completion.
_REGISTRATION = re.compile(r"\[(?P<supi>imsi-\d+)\][^\n]*Registration complete", re.I)

# AMF session context, which also carries the PDU session identifier:
#   [imsi-999700000000001:1:11] ...
_AMF_CONTEXT = re.compile(r"\[(?P<supi>imsi-\d+):(?P<psi>\d+):(?P<ctx>\d+)\]")

# Slice identity, available but not currently consumed by the evidence model.
_SNSSAI = re.compile(r"S_NSSAI\[SST:(?P<sst>\d+)(?:\s+SD:(?P<sd>[^\]]+))?\]", re.I)

# Release and deregistration.
_SESSION_RELEASE = re.compile(
    r"\[(?P<supi>imsi-\d+)[^\]]*\][^\n]*(?:Release|Deregistr|De-registr)", re.I
)

# Serving-node identity.
#
# CORRECTION FOUND AGAINST THE RUNNING CORE: Open5GS does not log a gNB
# identifier per session. The only serving-node information available is the N2
# (NGAP) peer address, logged as `gNB-N2[127.0.0.1]`. The earlier synthetic
# fixture assumed a `gnb_id` field that no real deployment emits this way, so the
# collector now reports what actually exists and names it accordingly.
_SERVING_NODE = re.compile(r"gNB-N2\[(?P<addr>[^\]]+)\]", re.I)


@dataclass(frozen=True)
class Open5gsEvent:
    """A normalised event observed from the running 5G core."""

    event_type: str
    supi: str | None
    observed_at: datetime
    peer_address: str | None = None
    dnn: str | None = None
    serving_node: str | None = None
    """The N2 peer address of the serving gNB.

    Not a gNB identifier: Open5GS does not log one per session. This is what the
    core actually exposes about the serving node.
    """
    pdu_session_id: str | None = None
    snssai: str | None = None
    registration_state: str = "REGISTERED"
    pdu_session_active: bool = True
    raw: str = ""

    @property
    def is_release(self) -> bool:
        return self.event_type in {"SESSION_RELEASED", "DEREGISTERED"}


def _parse_timestamp(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(UTC)
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_event_record(record: dict[str, object]) -> Open5gsEvent:
    """Parse a JSON event emitted by the Tier-2 capture script."""
    source_mode = str(record.get("source_mode", LIVE_SOURCE_MODE.value))
    if source_mode != LIVE_SOURCE_MODE.value:
        raise CollectorError(
            f"the live 5G collector refuses an event claiming source_mode "
            f"'{source_mode}'; it only accepts '{LIVE_SOURCE_MODE.value}'"
        )
    implementation = str(record.get("access_implementation", ACCESS_IMPLEMENTATION.value))
    if implementation != ACCESS_IMPLEMENTATION.value:
        raise CollectorError(
            f"the live 5G collector refuses an event claiming access_implementation "
            f"'{implementation}'; this collector only observes UERANSIM"
        )
    testbed = str(record.get("testbed_type", TESTBED_TYPE.value))
    if testbed != TESTBED_TYPE.value:
        raise CollectorError(
            f"Tier-2 events must declare testbed_type '{TESTBED_TYPE.value}'; this "
            f"testbed has no physical radio and must never claim one, got '{testbed}'"
        )

    return Open5gsEvent(
        event_type=str(record.get("event_type", "UNKNOWN")),
        supi=str(record["supi"]) if record.get("supi") else None,
        observed_at=_parse_timestamp(record.get("observed_at")),  # type: ignore[arg-type]
        peer_address=str(record["peer_address"]) if record.get("peer_address") else None,
        dnn=str(record["dnn"]) if record.get("dnn") else None,
        serving_node=(
            str(record["serving_node"])
            if record.get("serving_node")
            else (str(record["gnb_id"]) if record.get("gnb_id") else None)
        ),
        snssai=str(record["snssai"]) if record.get("snssai") else None,
        pdu_session_id=(str(record["pdu_session_id"]) if record.get("pdu_session_id") else None),
        registration_state=str(record.get("registration_state", "REGISTERED")),
        pdu_session_active=bool(record.get("pdu_session_active", True)),
        raw=str(record.get("raw", "")),
    )


def parse_log_line(line: str, *, at: datetime | None = None) -> Open5gsEvent | None:
    """Parse one Open5GS AMF, SMF or UPF log line, or ``None`` if irrelevant.

    Release is checked before establishment: a release line also mentions the
    SUPI, and treating it as an establishment would resurrect a session the core
    has already torn down.
    """
    observed_at = at or datetime.now(UTC)
    slice_id = _SNSSAI.search(line)
    snssai = (
        f"SST:{slice_id.group('sst')}"
        + (f" SD:{slice_id.group('sd')}" if slice_id and slice_id.group("sd") else "")
        if slice_id
        else None
    )
    serving = _SERVING_NODE.search(line)
    context = _AMF_CONTEXT.search(line)

    release = _SESSION_RELEASE.search(line)
    if release:
        return Open5gsEvent(
            event_type="SESSION_RELEASED",
            supi=release.group("supi"),
            observed_at=observed_at,
            pdu_session_active=False,
            registration_state="DEREGISTERED",
            serving_node=serving.group("addr") if serving else None,
            pdu_session_id=context.group("psi") if context else None,
            snssai=snssai,
            raw=line.strip(),
        )

    smf = _SMF_SESSION.search(line)
    if smf:
        return Open5gsEvent(
            event_type="SESSION_ESTABLISHED",
            supi=smf.group("supi"),
            observed_at=observed_at,
            dnn=smf.group("dnn") or None,
            peer_address=smf.group("ip") or None,
            serving_node=serving.group("addr") if serving else None,
            pdu_session_id=context.group("psi") if context else None,
            snssai=snssai,
            raw=line.strip(),
        )

    upf = _UPF_SESSION.search(line)
    if upf:
        return Open5gsEvent(
            event_type="SESSION_ESTABLISHED",
            supi=None,
            observed_at=observed_at,
            dnn=upf.group("dnn") or None,
            peer_address=upf.group("ip"),
            snssai=snssai,
            raw=line.strip(),
        )

    registration = _REGISTRATION.search(line)
    if registration:
        return Open5gsEvent(
            event_type="REGISTERED",
            supi=registration.group("supi"),
            observed_at=observed_at,
            serving_node=serving.group("addr") if serving else None,
            snssai=snssai,
            raw=line.strip(),
        )
    return None


def to_nr_access_event(
    event: Open5gsEvent,
    *,
    peer_address: str | None = None,
    binding_lifetime_s: int | None = 120,
) -> NrAccessEvent | None:
    """Map a live 5G event onto the NR collector's input schema."""
    address = peer_address or event.peer_address
    if address is None:
        # Without a user-plane address there is nothing to bind: a registration on
        # its own does not tell the service domain which address to trust.
        return None

    if event.is_release:
        event_type = NrEventType.SESSION_RELEASED
    elif event.event_type in {"SESSION_ESTABLISHED", "REGISTERED"}:
        event_type = NrEventType.SESSION_ESTABLISHED
    elif event.event_type == "SESSION_REFRESHED":
        event_type = NrEventType.SESSION_REFRESHED
    else:
        return None

    return NrAccessEvent(
        event_type=event_type,
        peer_address=address,
        observed_at=event.observed_at,
        source_mode=LIVE_SOURCE_MODE,
        subscriber_ref=event.supi,
        pdu_session_id=event.pdu_session_id or "1",
        dnn=event.dnn or "internet",
        # The serving node is the N2 peer address, which is what Open5GS actually
        # exposes; it is not a gNB identifier and is not treated as one.
        gnb_id=event.serving_node or "ueransim-gnb-n2",
        rat_type="NR",
        registration_state=event.registration_state,
        pdu_session_active=event.pdu_session_active,
        binding_lifetime_s=binding_lifetime_s,
    )


class Open5gsEventSource:
    """Reads live 5G events from the Tier-2 capture script's JSON Lines output."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0

    @property
    def path(self) -> Path:
        return self._path

    def available(self) -> bool:
        """Whether the source can be read. Unavailability is missing evidence."""
        return self._path.is_file()

    def read_all(self) -> list[Open5gsEvent]:
        if not self.available():
            return []
        events: list[Open5gsEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(parse_event_record(json.loads(stripped)))
            except json.JSONDecodeError:
                parsed = parse_log_line(stripped)
                if parsed is not None:
                    events.append(parsed)
        return events

    def read_new(self) -> list[Open5gsEvent]:
        events = self.read_all()
        fresh = events[self._offset :]
        self._offset = len(events)
        return fresh

    def reset(self) -> None:
        self._offset = 0


def provenance() -> dict[str, str]:
    """Provenance stamped on every Tier-2 5G observation."""
    return {
        "source_mode": LIVE_SOURCE_MODE.value,
        "access_implementation": ACCESS_IMPLEMENTATION.value,
        "testbed_type": TESTBED_TYPE.value,
        "5g_access_mode": ACCESS_IMPLEMENTATION.value,
        "note": (
            "Real 5G NAS/NGAP/GTP-U protocol interaction with Open5GS. Software UE "
            "and gNB; no physical radio and no RF propagation."
        ),
    }


__all__ = [
    "ACCESS_IMPLEMENTATION",
    "LIVE_SOURCE_MODE",
    "TESTBED_TYPE",
    "Open5gsEvent",
    "Open5gsEventSource",
    "parse_event_record",
    "parse_log_line",
    "provenance",
    "to_nr_access_event",
]
