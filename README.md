# Question Research

Question Research is a local-first research workspace for organizing questions, sources, claims and evidence. It keeps source collection, human review and answer export as separate steps.

## Install and try a synthetic project

```sh
python -m pip install .
research-poc --help
research-poc init "Which conditions affect a fictional seed trial?" --project ./demo-research
research-poc add-source --project ./demo-research --title "Fictional sample" --url https://example.com/ --quality unknown
research-poc plan-research --project ./demo-research
```

These steps create and plan a local project. Source and evidence review determine whether an answer export is ready. Optional browser, video and model integrations depend on separately configured tools. Base installation and the offline suite use public dependencies.

```sh
python -m pip install ".[test]"
python -m pytest -q
```

The first public source edition adapts the installation metadata, documentation and Web UI project default, and includes portable tests with synthetic records. Keep generated research projects and credentials outside version control.

Apache-2.0. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
