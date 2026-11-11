# madgraph_double_counting

A MadGraph5_aMC@NLO plugin that reports Feynman diagrams shared by two or
more process definitions.

This targets **LO tree diagrams** only. NLO and loop-induced amplitudes are
rejected explicitly.

## Install

From a checkout:

```bash
./install.sh --mg5 /path/to/MG5_aMC_v3_8_1 --from-local
```

Or, after the repository is published:

```bash
./install.sh --mg5 /path/to/MG5_aMC_v3_8_1
```

`install.sh` copies the plugin into `MG5_aMC/PLUGIN/double_counting` and
creates `bin/mg5_aMC_double_counting`.

## Run

```bash
/path/to/MG5_aMC_v3_8_1/bin/mg5_aMC --mode=double_counting
```

or:

```bash
/path/to/MG5_aMC_v3_8_1/bin/mg5_aMC_double_counting
```

All normal MG5 commands remain available in this shell.

## Usage

After generating a process:

```text
generate p p > w+ w- b b~
check double_counting { p p > t t~, t > b w+, t~ > b~ w- }
```

Or with two explicit sets:

```text
check double_counting { A... } { B... }
```

A file with named process sets is also accepted:

```text
check double_counting processes.txt
```

## Output

```text
check double_counting ... --show=raw
check double_counting ... --show=chain
check double_counting ... --show=chain-all
```

`chain` shows `u u~ > t t~ > w+ w- b b~`; `chain-all` also shows virtual
intermediates such as the gluon.

The repeated diagrams can be written to PDF:

```text
check double_counting ... --save
check double_counting ... --save=reports/dc/repeated.pdf
check double_counting ... --save=reports/dc/
```

The PDF uses MG5's drawing code and Ghostscript. Each page is labelled with
the process sets where the diagram appears.

## Scope

- The comparison is on the full diagram, not only the final state.
- Decay chains are spliced onto their production diagrams before comparison.
- Multiparticle definitions and BSM particle names are supported.
- Only LO tree diagrams are accepted.

A MadGraph7 adapter would need a separate port; the MG5 plugin API is not
shared with MadGraph7.

## Test

Install the plugin first, then run the full suite:

```bash
PYTHONPATH="$PWD:$PWD/MG5_aMC_v3_8_1" \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

For a quick installation/PDF check:

```bash
./tests/smoke.sh
```

Set `MG5` and `PYTHON` when needed:

```bash
MG5=/path/to/MG5_aMC_v3_8_1 PYTHON=~/miniconda3/envs/py310/bin/python ./tests/smoke.sh
```

GitHub Actions runs the full suite on every push and pull request.
