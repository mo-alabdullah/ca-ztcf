# MQTT testbed

## What runs where

| Component | Runs | Port |
|---|---|---|
| Mosquitto broker | container `mosquitto` | 1883, **internal to the Compose network only** |
| CA-ZTCF MQTT enforcement point | container `ca-ztcf-mqtt-pep` | 1884, published to the host for the runner |
| CA-ZTCF core (trust function) | container `ca-ztcf-core` | 8080, published to the host |
| Device agent | host process, driven by the experiment runner | — |

## Path

```
device agent  ->  ca-ztcf-mqtt-pep : 1884  ->  mosquitto : 1883
                         |
                         v
                 ca-ztcf-core : 8080   (decisions)
```

The enforcement point never decides anything itself. It calls
`POST /v1/decisions/evaluate` on the core and applies the answer, so the MQTT path
cannot bypass the trust engine.

## Broker isolation

Mosquitto publishes no host port. It is reachable only from inside the Compose
network, and in practice only from the enforcement point. `allow_anonymous` is
enabled inside that boundary because every client that reaches the broker has
already been authorised upstream; the broker is the protected resource, not a
policy decision point.

## Credentials

The device presents its proof-of-possession in the MQTT CONNECT password field as
`<nonce>.<signature>`, both base64url. The enforcement point reads it, verifies it
through the core, and **strips it** before relaying the CONNECT upstream: the
broker never sees credential material, and neither does its log.
