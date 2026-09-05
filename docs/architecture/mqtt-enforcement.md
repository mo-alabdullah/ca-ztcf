# The MQTT Policy Enforcement Point

```
device agent  ->  ca-ztcf-mqtt-pep : 1884  ->  mosquitto : 1883
                          |
                          v
                    ca-ztcf-core : 8080   (decisions)
```

An asyncio proxy between the device and Mosquitto. It is **not** a broker: it
reads enough of each control packet to apply the active decision and relays the
rest byte for byte. It decides nothing itself — every decision comes from
`POST /v1/decisions/evaluate` on the core, so the MQTT path cannot bypass the
trust engine. This keeps the PE/PEP separation of NIST SP 800-207 intact.

## Packets handled

CONNECT, CONNACK, PUBLISH, PUBACK, SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK,
PINGREQ, PINGRESP, DISCONNECT. Anything else is relayed verbatim rather than
reinterpreted, so the proxy cannot silently alter application semantics.

## Credentials

The device presents its proof-of-possession in the CONNECT password field as
`<nonce>.<signature>`, both base64url. The enforcement point reads it once,
verifies it through the core, and **strips it** before relaying the CONNECT
upstream. The broker never sees credential material and neither does its log;
this is asserted by `test_credentials_are_never_relayed_to_the_broker`.

## Action to broker behaviour

MQTT 3.1.1 offers no "policy denied" code, so every refusal uses the mechanisms
the protocol actually has. Nothing below is invented.

| Action | Behaviour |
|---|---|
| `ALLOW` | Full configured topic scope. |
| `ALLOW_WITH_RESTRICTIONS` | Restricted scope. Publishes outside it are dropped; subscriptions outside it are refused with SUBACK `0x80`. |
| `STEP_UP_AUTHENTICATION` | Connection accepted, protected operations held. A challenge is published on `ctl/<id>/challenge`; the answer is admitted on `ctl/<id>/response` and never relayed upstream. |
| `REAUTHENTICATE` | CONNECT refused with CONNACK `0x05`; an established session is closed. |
| `QUARANTINE` | Only `q/<device_id>/#` is reachable. |
| `DENY` | CONNECT refused with CONNACK `0x05`. |

A denied QoS 1 PUBLISH is still acknowledged, so the client does not retry
indefinitely; the drop and its reason go to the audit log. This mirrors what a
broker does on an ACL denial, and is documented rather than invented.

## Decision lifetime

Each decision carries a TTL. The enforcement point re-consults the trust function
when the TTL expires, so a decision cannot outlive its evidence.

## Observed peer address

The enforcement point decides about the address it actually sees on the socket.
An access-domain collector must hold a binding for that same address, which is the
whole point of binding evidence. The observed address is reported back to the
device on `ctl/<id>/decision` and recorded in the audit record, so a "no binding"
outcome is diagnosable instead of looking like a framework fault.

Behind Docker port publishing every host-side agent shares one bridge address. In
a real deployment devices have their own addresses; the experiment runner works
around the shared address by releasing bindings explicitly between scenarios.

## Broker isolation

Mosquitto publishes no host port and is reachable only from inside the Compose
network. `allow_anonymous` is enabled inside that boundary only because every
client that reaches the broker has already been authorised upstream. The broker
is the protected resource, not a policy decision point.
