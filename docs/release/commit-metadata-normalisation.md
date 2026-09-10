# Commit-message metadata normalisation

## What was done

The commit messages in this repository's history were normalised to remove a
non-substantive trailer line that had been appended to a number of commits. The
operation touched **commit-message metadata only**.

Nothing else changed. Specifically, the rewrite preserved:

- every commit author and author timestamp;
- every commit committer and committer timestamp;
- every commit tree, byte for byte;
- every file path and every file's contents;
- every tag name, tag message, tagger identity and tagger date;
- the substantive wording of every commit message.

The `main` branch was **not** rewritten by this operation. It was already
normalised, and its head remains `4f870c2a9a6e6ebe58bcb9804d39cddc57c4ee9c`.
The seven pre-existing tags were rewritten so that they point into the normalised
history rather than the superseded one.

## Why the commit identifiers changed

A Git commit identifier is a hash over the commit's content, and the commit
message is part of that content. Changing a message therefore changes the
identifier of that commit and of every commit that descends from it. This is an
unavoidable property of Git, not a change of substance.

Because the trees are identical, the two identifiers for any given commit name
**the same repository content**.

## Tag mapping

| Tag | Superseded commit | Current commit | Root tree (unchanged) |
|---|---|---|---|
| `v0.1.0` | `1185e3b4f885eeab56d3a041dab86fb0335af918` | `5393526cb9d738a7d65115c3e987397b8bd12417` | `2bbff4b27d7f9cbdc40fc235867e5a51f753dbf5` |
| `v0.2.0` | `2aeaca90eec46242b84eaeb0536733c50ba1f222` | `556f2c4dd87a09cfca142d2c7e4d69e1ac3992c0` | `931c68777001b3f7332e93e2925fd62ab45edaf2` |
| `v0.3.0` | `45e874585d0627b3a73557d9d321555d7a0c9749` | `2cde058bfdbe6f6a62807f50400b178d83406e85` | `f8dce578b83513744e65b6d2f5a43dcf5c535217` |
| `v0.3.1` | `c3463926420537f26e7ce2f7477a0bb1de533e1c` | `21f69b32dcb7da22847a91d6dd324432a39ef382` | `029c87a4693b4fc732139dc81bf30284994a07bb` |
| `v1.0.0` | `61269de72f29a7215dacb74bac9c11e9c4f8beab` | `66e4f3606bc6c596dd8896526998e2dfcce81fda` | `23c241ab0da1d6520384f93a8005a6eed3add78e` |
| `v1.0.1` | `a79bc93b526a913cbeb86a17cf68b49ff22ed03a` | `64f6206c10085b6c240855dce7bf8dc0548b14c0` | `4a2a33e35da3417df2b3312044165101b0591583` |
| `v1.0.2` | `513fd96f84057d23d7be78ce38d190ff0f82cb48` | `ec5e10294c62fb264d2225562c600c9d28a006e9` | `85b9f793bbb390fa23630db188d845f8f3b552d8` |

The root tree column is the check: it is the same before and after in every row,
so the content each tag names did not change.

## The campaign commit

The final experimental campaign ran under commit
`a9ff4a5e1dc0fea65b63e2b366814c1860f04110`, described by `git describe` at the
time as `v0.3.1-4-ga9ff4a5`. That identifier is recorded inside the frozen run
metadata and inside the frozen results manifest, and those files are covered by
the frozen SHA-256 hashes. **They were not modified and must not be.**

The normalised equivalent of that commit is
`00a88d486eaa184feb72484e8931679bcf0e0213`. The two commits have identical Git
root trees: `fc1ae164a435952778faef81dc74941a74dcf792`.

To be precise about what this means:

- The campaign **was executed** under `a9ff4a5e1dc0fea65b63e2b366814c1860f04110`.
  That is the historical fact the run metadata records, and it stays as recorded.
- `00a88d486eaa184feb72484e8931679bcf0e0213` is the identifier under which that
  same source state is reachable in the repository today.
- The campaign did **not** originally run under
  `00a88d486eaa184feb72484e8931679bcf0e0213`, and nothing in this repository or in
  the thesis claims that it did.

Anyone reproducing the campaign should check out
`00a88d486eaa184feb72484e8931679bcf0e0213`, which yields exactly the source tree
the campaign ran against.

## Superseded identifiers inside frozen artefacts

Two frozen artefacts record commit identifiers from the superseded history. Both are
covered by the frozen SHA-256 hashes, so neither was modified and neither may be:

- `results/final/manifests/final_results_manifest.json` and the per-run files under
  `results/final/metadata/` record the campaign commit
  `a9ff4a5e1dc0fea65b63e2b366814c1860f04110`.
- `docs/experiments/final_experiment_protocol.md`, the protocol frozen before the
  first run, records the pre-freeze baseline
  `c3463926420537f26e7ce2f7477a0bb1de533e1c` (tag `v0.3.1`). Its normalised
  equivalent is `21f69b32dcb7da22847a91d6dd324432a39ef382`, with the identical root
  tree `029c87a4693b4fc732139dc81bf30284994a07bb`.

Leaving these identifiers as recorded is deliberate. They state what was true when
the campaign was run and when the protocol was frozen, and rewriting them would
misrepresent the historical record and break the frozen hashes that make the
evidence checkable. This document is the mapping to their current equivalents.

## What did not change

No framework code, no experiment, no configuration, no result, no statistic, no
figure and no table was altered. The three frozen hashes are unchanged:

| Artefact | SHA-256 |
|---|---|
| Results manifest | `f5b4cd4884d62a2267c7520d00dad389e532b276d357b045bbc2983ad1d0ffbb` |
| SHA256SUMS | `fade4d7b70c1c20b3a6218de34fe12aab10d49ea9f3389fb868ffded7d5ae215` |
| Raw data archive | `b4e5ce650f29907b45bfd5c05c0a6ccc18ec247971f76aff267469fefa31f6b4` |

## Archived records

Zenodo records are immutable once published. The published `v1.0.2` record was
**not** modified, and it retains the commit identifiers current at the time it was
archived. That is correct: an archival record is a snapshot of what existed when
it was made. `v1.0.3` is a new version in the same Zenodo concept record and
carries the normalised history.
