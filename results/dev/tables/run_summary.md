# Run summary

**DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT**

> DEVELOPMENT VALIDATION - NOT FINAL THESIS RESULT. Tier-1 only: the 5G access context is a synthetic fixture and the WLAN side is 802.1X/EAP-TLS authentication-path emulation. Not a WiFi, RF, 802.11 or 5G measurement.
>
> Generated automatically from `results/dev/raw/` by
> `scripts/process_results.py`. No value here was typed by hand.
> Descriptive statistics only: no inferential test has been performed and
> no statistical significance is claimed.

| scenario | strategy | decisions | latency median (ms) | IQR (ms) | p95 (ms) | engine median (us) | reauth M5 | step-up M6 | state trans. M7 |
|---|---|---|---|---|---|---|---|---|---|
| E01 | ca_ztcf | 2 | 0.789 | 0.417 | 1.164 | 0.0 | 0 | 0 | 0 |
| E01 | independent | 2 | 0.250 | 0.157 | 0.391 | - | 0 | 0 | 0 |
| E01 | static_continuity | 2 | 0.282 | 0.171 | 0.436 | - | 0 | 0 | 0 |
| E02 | ca_ztcf | 2 | 0.551 | 0.202 | 0.733 | 0.0 | 0 | 0 | 0 |
| E02 | independent | 2 | 0.243 | 0.157 | 0.384 | - | 0 | 0 | 0 |
| E02 | static_continuity | 2 | 0.278 | 0.177 | 0.437 | - | 0 | 0 | 0 |
| E03 | ca_ztcf | 3 | 0.581 | 0.227 | 0.752 | 0.0 | 0 | 0 | 2 |
| E03 | independent | 3 | 0.129 | 0.178 | 0.411 | - | 1 | 0 | 2 |
| E03 | static_continuity | 3 | 0.108 | 0.199 | 0.441 | - | 0 | 0 | 0 |
| E04 | ca_ztcf | 3 | 0.564 | 0.225 | 0.738 | 0.0 | 0 | 0 | 2 |
| E04 | independent | 3 | 0.110 | 0.151 | 0.363 | - | 1 | 0 | 2 |
| E04 | static_continuity | 3 | 0.100 | 0.164 | 0.376 | - | 0 | 0 | 0 |
| E05 | ca_ztcf | 6 | 0.544 | 0.054 | 0.723 | 0.0 | 0 | 3 | 1 |
| E05 | independent | 6 | 0.083 | 0.038 | 0.349 | - | 5 | 0 | 1 |
| E05 | static_continuity | 6 | 0.106 | 0.018 | 0.360 | - | 0 | 0 | 0 |
