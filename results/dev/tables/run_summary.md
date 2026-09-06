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
| E01 | ca_ztcf | 2 | 0.836 | 0.467 | 1.257 | 0.0 | 0 | 0 | 0 |
| E01 | independent | 2 | 0.290 | 0.161 | 0.435 | - | 0 | 0 | 0 |
| E01 | static_continuity | 2 | 0.253 | 0.156 | 0.393 | - | 0 | 0 | 0 |
| E02 | ca_ztcf | 2 | 0.564 | 0.198 | 0.743 | 0.0 | 0 | 0 | 0 |
| E02 | independent | 2 | 0.284 | 0.179 | 0.445 | - | 0 | 0 | 0 |
| E02 | static_continuity | 2 | 0.256 | 0.162 | 0.402 | - | 0 | 0 | 0 |
| E03 | ca_ztcf | 3 | 0.549 | 0.214 | 0.710 | 0.0 | 0 | 0 | 2 |
| E03 | independent | 3 | 0.111 | 0.157 | 0.371 | - | 1 | 0 | 2 |
| E03 | static_continuity | 3 | 0.106 | 0.215 | 0.458 | - | 0 | 0 | 0 |
| E04 | ca_ztcf | 3 | 0.536 | 0.226 | 0.734 | 0.0 | 0 | 0 | 2 |
| E04 | independent | 3 | 0.106 | 0.160 | 0.374 | - | 1 | 0 | 2 |
| E04 | static_continuity | 3 | 0.111 | 0.176 | 0.401 | - | 0 | 0 | 0 |
| E05 | ca_ztcf | 6 | 0.563 | 0.035 | 0.692 | 0.0 | 0 | 3 | 1 |
| E05 | independent | 6 | 0.081 | 0.031 | 0.336 | - | 5 | 0 | 1 |
| E05 | static_continuity | 6 | 0.084 | 0.017 | 0.332 | - | 0 | 0 | 0 |
| E06 | ca_ztcf | 4 | 0.431 | 0.261 | 0.757 | 0.0 | 0 | 1 | 3 |
| E06 | independent | 4 | 0.114 | 0.103 | 0.423 | - | 1 | 0 | 2 |
| E06 | static_continuity | 4 | 0.106 | 0.104 | 0.416 | - | 0 | 0 | 0 |
| E07 | ca_ztcf | 4 | 0.600 | 0.078 | 0.711 | 0.0 | 0 | 0 | 1 |
| E07 | independent | 4 | 0.200 | 0.260 | 0.466 | - | 1 | 0 | 1 |
| E07 | static_continuity | 4 | 0.199 | 0.241 | 0.395 | - | 0 | 0 | 0 |
| E08 | ca_ztcf | 2 | 0.668 | 0.077 | 0.738 | 0.0 | 0 | 0 | 1 |
| E08 | independent | 2 | 0.264 | 0.149 | 0.398 | - | 1 | 0 | 1 |
| E08 | static_continuity | 2 | 0.253 | 0.151 | 0.389 | - | 0 | 0 | 0 |
| E09 | ca_ztcf | 10 | 0.542 | 0.017 | 0.649 | 0.0 | 0 | 2 | 2 |
| E09 | independent | 10 | 0.078 | 0.014 | 0.379 | - | 8 | 0 | 1 |
| E09 | static_continuity | 10 | 0.073 | 0.014 | 0.281 | - | 0 | 0 | 0 |
| E10 | ca_ztcf | 2 | 0.671 | 0.069 | 0.734 | 0.0 | 1 | 0 | 1 |
| E10 | independent | 2 | 0.434 | 0.105 | 0.529 | - | 0 | 0 | 0 |
| E10 | static_continuity | 2 | 0.267 | 0.149 | 0.401 | - | 0 | 0 | 0 |
| E11 | ca_ztcf | 3 | 0.373 | 0.206 | 0.743 | 0.0 | 0 | 1 | 2 |
| E11 | independent | 3 | 0.099 | 0.186 | 0.415 | - | 0 | 0 | 0 |
| E11 | static_continuity | 3 | 0.108 | 0.190 | 0.425 | - | 0 | 0 | 0 |
| E12 | ca_ztcf | 30 | 0.512 | 0.039 | 0.651 | 0.0 | 0 | 0 | 20 |
| E12 | independent | 30 | 0.270 | 0.199 | 0.328 | - | 10 | 0 | 20 |
| E12 | static_continuity | 30 | 0.078 | 0.205 | 0.309 | - | 0 | 0 | 0 |
| E13 | ca_ztcf | 50 | 0.534 | 0.040 | 0.656 | 0.0 | 0 | 0 | 25 |
| E13 | independent | 50 | 0.209 | 0.195 | 0.289 | - | 25 | 0 | 25 |
| E13 | static_continuity | 50 | 0.188 | 0.199 | 0.340 | - | 0 | 0 | 0 |
| E14 | ca_ztcf | 50 | 0.526 | 0.021 | 0.600 | 0.0 | 0 | 8 | 7 |
| E14 | independent | 50 | 0.078 | 0.008 | 0.292 | - | 40 | 0 | 4 |
| E14 | static_continuity | 50 | 0.078 | 0.016 | 0.285 | - | 0 | 0 | 0 |
| E15 | ca_ztcf | 55 | 0.500 | 0.037 | 0.544 | 0.0 | 2 | 0 | 9 |
| E15 | independent | 55 | 0.263 | 0.030 | 0.286 | - | 6 | 0 | 6 |
| E15 | static_continuity | 55 | 0.069 | 0.006 | 0.265 | - | 0 | 0 | 0 |
