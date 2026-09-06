# Reproducing the final results

Everything in `results/final/` comes from the raw runs, and the raw runs come from
a testbed this repository provisions. Nothing was typed by hand.

There are two things you might want to do, and they need different amounts of
work.

## 1. Regenerate every derived artefact from the raw data

This needs no testbed. It checks that the processed data, tables, figures and
statistics actually follow from the runs.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

# The raw runs and the audit trail ship as a deterministic archive.
sha256sum -c results/final/manifests/ca-ztcf-v1.0.1-final-results.tar.zst.sha256
tar --zstd -xf results/final/manifests/ca-ztcf-v1.0.1-final-results.tar.zst -C results/

python scripts/verify_final_results.py
```

The verifier moves `processed/`, `tables/`, `statistics/` and `figures/` aside,
regenerates them and compares. Text artefacts must be byte-identical. Figures are
compared by **decoded pixels**, because matplotlib writes a creation timestamp into
PNG metadata and their bytes will therefore differ; that is stated rather than
dressed up as byte identity.

To check the frozen checksums:

```bash
cd results/final && sha256sum -c manifests/SHA256SUMS
```

## 2. Re-run the campaign

This needs the Tier-2 testbed: a Linux VM with Open5GS, UERANSIM and
`mac80211_hwsim`. [`testbed/tier2/README.md`](../../testbed/tier2/README.md) has
the full provisioning sequence; in outline:

```bash
make tier2-up                     # Lima VM, Ubuntu 24.04
limactl shell ca-ztcf-tier2

sudo bash /opt/ca-ztcf/testbed/tier2/scripts/install_ueransim.sh
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/provision_subscribers.sh 25
sudo bash /opt/ca-ztcf/testbed/tier2/scripts/start_services.sh
sudo UE_COUNT=25 bash /opt/ca-ztcf/testbed/tier2/scripts/start_5g.sh
sudo STA_COUNT=25 bash /opt/ca-ztcf/testbed/tier2/scripts/start_wlan.sh
sudo bash /opt/ca-ztcf/testbed/tier2/network/capture_events.sh start

# prove the 5G application path is deterministic before measuring anything
sudo /opt/ca-ztcf-venv/bin/python \
  /opt/ca-ztcf/testbed/tier2/network/verify_ue_path.py

cd /opt/ca-ztcf
sudo bash -c 'env PYTHONPATH=/opt/ca-ztcf/src:/opt/ca-ztcf \
  /opt/ca-ztcf-venv/bin/python scripts/run_final_campaign.py \
  --campaign primary --access-source tier2 --out results/final'
sudo bash -c 'env PYTHONPATH=/opt/ca-ztcf/src:/opt/ca-ztcf \
  /opt/ca-ztcf-venv/bin/python scripts/run_final_campaign.py \
  --campaign sensitivity --access-source tier2 --out results/final'
```

Then, on the host:

```bash
python scripts/collect_tier2_environment.py
python scripts/process_final_results.py
python scripts/verify_final_results.py
python scripts/freeze_final_results.py
```

### What will and will not match

**Will match.** Every decision, trust state, policy action, confusion count and
ground-truth outcome. The scenario clock is frozen and the seeds are fixed, so the
sequence of decisions is deterministic given the same commit and configuration
hash.

**Will not match.** Every measured duration, and CPU and memory. These are physical
measurements of a particular machine under a particular load. A campaign on
different hardware will produce different latencies; that is the measurement
working, not a reproducibility failure.

### If a run fails

The campaign driver records every attempt in `results/final/run_ledger.csv` and is
restartable: rerun the same command and it skips whatever is already recorded
`VALID`. An infrastructure failure is retried with the **same seed**, never
replaced by a different one. A failure it cannot attribute to infrastructure stops
the campaign, because that is how a software defect is supposed to be found.

## What the results can and cannot support

Read
[`results/final/processed/experimental_limitations.md`](../../results/final/processed/experimental_limitations.md)
before drawing any conclusion. In short: **both radios are simulated**, the
validated ceiling is **25 logical devices sharing one 802.11 association**, the
validated rate ceiling is **25 transitions per second**, and the CPU and memory
figures measure the experiment process rather than an IoT device.
