#!/usr/bin/env bash
# Provision deterministic research subscribers in the Open5GS UDR.
#
# Every value here is a SYNTHETIC RESEARCH IDENTIFIER. The PLMN 999/70 is the
# 3GPP-reserved test network, and the keys are laboratory values that exist only
# in this testbed. No production credential and no real subscriber identifier
# appears anywhere.
#
# Note for the framework: the IMSI/SUPI below is an ACCESS-DOMAIN identifier. It
# is never the CA-ZTCF device identity, which is a service-domain identity bound
# to a device-held key pair.
set -euo pipefail

COUNT="${1:-5}"
MCC="${MCC:-999}"
MNC="${MNC:-70}"
# Laboratory test vectors, not secrets: identical values ship in the Open5GS
# documentation and have no meaning outside this isolated testbed.
KEY="${SUBSCRIBER_KEY:-465B5CE8B199B49FAA5F0A2EE238A6BC}"
OPC="${SUBSCRIBER_OPC:-E8ED289DEBA952E4283B54E88E6183CA}"
DNN="${DNN:-internet}"

command -v mongosh >/dev/null 2>&1 || { echo "mongosh not found" >&2; exit 1; }

echo "provisioning ${COUNT} synthetic research subscriber(s) in PLMN ${MCC}/${MNC}"
for index in $(seq 0 $((COUNT - 1))); do
  imsi=$(printf "%s%s%010d" "${MCC}" "${MNC}" $((1 + index)))
  mongosh --quiet open5gs --eval "
    db.subscribers.deleteOne({imsi: '${imsi}'});
    db.subscribers.insertOne({
      schema_version: 1,
      imsi: '${imsi}',
      msisdn: [], imeisv: [], mme_host: [], mm_realm: [], purge_flag: [],
      security: {
        k: '${KEY}', op: null, opc: '${OPC}', amf: '8000',
        sqn: NumberLong(0)
      },
      ambr: { downlink: { value: 1, unit: 3 }, uplink: { value: 1, unit: 3 } },
      slice: [{
        sst: 1, default_indicator: true,
        session: [{
          name: '${DNN}', type: 3,
          qos: { index: 9, arp: { priority_level: 8,
                 pre_emption_capability: 1, pre_emption_vulnerability: 1 } },
          ambr: { downlink: { value: 1, unit: 3 }, uplink: { value: 1, unit: 3 } }
        }]
      }],
      access_restriction_data: 32,
      subscriber_status: 0,
      network_access_mode: 0,
      subscribed_rau_tau_timer: 12
    });
  " >/dev/null
  echo "  ${imsi}"
done

echo "total subscribers: $(mongosh --quiet open5gs --eval 'db.subscribers.countDocuments({})')"
