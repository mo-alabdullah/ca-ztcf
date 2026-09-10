# CA-ZTCF Research Artefact Citation

The authoritative citation reference for the master's thesis. Every value below was read
from the Zenodo record and the git repository, not transcribed from memory.

## Identity

| | |
|---|---|
| Research artefact | CA-ZTCF: Coexistence-Aware Zero Trust Continuity Framework |
| Author | Mohammed Alabdullah |
| Affiliation | Iran University of Science and Technology |
| Version | 1.0.3 |
| Year | 2026 |
| Publisher | Zenodo |
| Type | Software |
| Licence | Apache-2.0 (code); CC BY 4.0 (documentation and results) |

| | |
|---|---|
| GitHub repository | https://github.com/mo-alabdullah/ca-ztcf |
| GitHub release | https://github.com/mo-alabdullah/ca-ztcf/releases/tag/v1.0.3 |
| Zenodo record | https://zenodo.org/records/22694612 |
| **Version DOI** | **10.5281/zenodo.22694612** |
| Concept DOI | 10.5281/zenodo.22544764 |
| Release commit | `9eb4970d133e7e335e94c2c5e3a84676320bdc85` |

## Which DOI to cite

**In the thesis, cite the version DOI: `10.5281/zenodo.22694612`.**

It identifies one exact archived release — one commit, one configuration hash, one
set of frozen measurements. A reader following it arrives at the precise implementation the
study was run on. A DOI that could later resolve to different code would not let anyone
check a reported number against what produced it.

The version DOI `10.5281/zenodo.22544765` identifies the earlier `v1.0.2` archive. It does not
identify `v1.0.3` and must not be used as though it did. That record remains published and
unmodified, because Zenodo versions are immutable.

**Use the concept DOI, `10.5281/zenodo.22544764`, for project-level references** — a
repository listing, a CV entry, a project page, a README badge — where persistence across
future versions matters more than identifying one. It always resolves to the most recent
version.

Do not substitute one for the other. The distinction is what makes the artefact citable and
the results checkable.

## Frozen research result hashes

These identify the experimental evidence. They are unchanged from `v1.0.1`, which is the
check that no measurement was touched when either archival release was cut.

| Artefact | SHA-256 |
|---|---|
| Results manifest | `f5b4cd4884d62a2267c7520d00dad389e532b276d357b045bbc2983ad1d0ffbb` |
| SHA256SUMS | `fade4d7b70c1c20b3a6218de34fe12aab10d49ea9f3389fb868ffded7d5ae215` |
| Raw results archive | `b4e5ce650f29907b45bfd5c05c0a6ccc18ec247971f76aff267469fefa31f6b4` |

The campaign ran under commit `a9ff4a5e1dc0fea65b63e2b366814c1860f04110`
(`v0.3.1-4-ga9ff4a5`) under configuration hash
`a1d260b660c93e47a466deb9c00f26c880973356f7da4eda00cb8ec57cab044d`. That identifier is what the
frozen run metadata records, and it is covered by the frozen hashes above.

Commit-message metadata was normalised in `v1.0.3`, which changed commit identifiers without
changing any commit tree. The normalised equivalent of the campaign commit is
`00a88d486eaa184feb72484e8931679bcf0e0213`; both commits have the identical root tree
`fc1ae164a435952778faef81dc74941a74dcf792`, so they name the same source state. Reproduction
should check out `00a88d486eaa184feb72484e8931679bcf0e0213`. See
[`commit-metadata-normalisation.md`](commit-metadata-normalisation.md).

The raw archive keeps its `ca-ztcf-v1.0.1-final-results.tar.zst` filename and the manifest
keeps its recorded version of `1.0.1`. Both describe the v1.0.1 campaign, which `v1.0.2` and
`v1.0.3` carry unchanged; renaming them would imply a regeneration that did not happen.

## A. IEEE-style citation

```
M. Alabdullah, "CA-ZTCF: Coexistence-Aware Zero Trust Continuity Framework,"
version 1.0.3, Zenodo, 2026. doi: 10.5281/zenodo.22694612.
```

With an access date, where the thesis style guide requires one for software:

```
M. Alabdullah, "CA-ZTCF: Coexistence-Aware Zero Trust Continuity Framework,"
version 1.0.3, Zenodo, 2026. doi: 10.5281/zenodo.22694612. [Online].
Available: https://doi.org/10.5281/zenodo.22694612
```

Zenodo is the publisher of the archived record; GitHub hosts the repository. No journal,
volume, issue or page numbers exist for this artefact and none should be invented.

## B. BibTeX

`@software` is the correct entry type. `biblatex` supports it directly; with plain BibTeX
under a style that does not, use `@misc` with the same fields.

```bibtex
@software{alabdullah_caztcf_2026,
  author    = {Alabdullah, Mohammed},
  title     = {{CA-ZTCF}: {Coexistence-Aware} {Zero} {Trust} {Continuity} {Framework}},
  version   = {1.0.3},
  year      = {2026},
  month     = sep,
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.22694612},
  url       = {https://doi.org/10.5281/zenodo.22694612}
}
```

Project-level variant, for a reference that should follow future versions:

```bibtex
@software{alabdullah_caztcf,
  author    = {Alabdullah, Mohammed},
  title     = {{CA-ZTCF}: {Coexistence-Aware} {Zero} {Trust} {Continuity} {Framework}},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.22544764},
  url       = {https://doi.org/10.5281/zenodo.22544764}
}
```

The double braces preserve capitalisation under styles that would otherwise lowercase the
title. No journal, volume, issue, pages, editor or ISBN field is included, because Zenodo
supports none of them for this record.

## C. Reproducibility paragraph

Reference material for the methodology section. Factual statements only — not thesis prose,
and to be rewritten in the author's own voice before use.

> The CA-ZTCF implementation is archived on Zenodo as release v1.0.3, version DOI
> 10.5281/zenodo.22694612, with the source repository at
> https://github.com/mo-alabdullah/ca-ztcf and the release frozen at commit
> 9eb4970d133e7e335e94c2c5e3a84676320bdc85. The archive contains the framework, both
> testbed definitions, the experiment infrastructure, the experiment protocol committed
> before the first run, the complete raw output of all 2160 runs, the run ledger recording
> every attempt, the processed results, figures, tables and statistics, and the scripts that
> regenerate every derived artefact from the raw data. The integrity of the experimental
> evidence is fixed by three SHA-256 digests: the results manifest
> (f5b4cd4884d62a2267c7520d00dad389e532b276d357b045bbc2983ad1d0ffbb), the file checksum list
> (fade4d7b70c1c20b3a6218de34fe12aab10d49ea9f3389fb868ffded7d5ae215) and the raw data
> archive (b4e5ce650f29907b45bfd5c05c0a6ccc18ec247971f76aff267469fefa31f6b4).

## Scope, when citing results from this artefact

The evaluation runs on a reproducible software-based 5G/WiFi coexistence testbed: Open5GS
2.8.0 with UERANSIM v3.2.6 for real 5G NAS, NGAP and GTP-U, and mac80211_hwsim with hostapd
2.10 and wpa_supplicant 2.10 for a real IEEE 802.11 association and EAP-TLS exchange.

**Both radios are simulated.** No result from this artefact supports a claim about RF
propagation, physical radio handover performance, interference, signal strength, spectrum
efficiency, channel-quality behaviour, or performance on a production mobile network.

**Logical-device scalability is validated to 25 devices**, which share one 802.11
association. That is service-domain scalability, not independent WiFi-radio association
scalability, and nothing is extrapolated beyond 25 devices or 25 transitions per second.

Read `results/final/processed/experimental_limitations.md` and
`results/final/processed/non_findings.md` before citing any measured value. The second lists
what the campaign did *not* establish, including the metrics that were never measured rather
than measured as zero.

## Provenance note

The DOI values above were recorded in a documentation commit made **after** `v1.0.3` was tagged
and archived. A DOI cannot exist before the release it identifies, so the frozen `v1.0.3` commit
and its Zenodo snapshot do not contain it. That sequence is correct and is not a discrepancy
between the repository and the archive; the same sequence was followed for `v1.0.2`.

`v1.0.3` is a metadata-only release. Commit-message metadata in the repository's history was
normalised: no framework change, no experiment change, no configuration change, no result change,
no statistical change, and no figure or table change. The frozen results are byte-identical to
`v1.0.2`.
