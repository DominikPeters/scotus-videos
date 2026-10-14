# Video presentation

`renderer/` contains the production HTML, JavaScript, circuit map and asset
manifest. `formatters/` retains the established argument/description formatting
and timestamp-comment sources. `reference/` retains the original local
preprocess/build/upload scripts for reference; cloud workers use their dedicated
workflow implementations instead.

`sources.json` records source provenance and checksums. The Python modules are
`scotus_cloud/presentation_sources.py` (verified source loading),
`presentation_data.py` (Court/CTC data adaptation) and `formatters.py` (public
output formatting). Presentation sources remain protected from recovery edits;
data adaptation remains editable by planning recovery. The October 14 cleanup
moved these sources without changing their contents.
