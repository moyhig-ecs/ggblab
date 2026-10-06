# ggblab

GeoGebra applets in Jupyter notebooks, driven from Python and Julia kernels.

**Current version: 2.0.0rc1** ([PyPI](https://pypi.org/project/ggblab/2.0.0rc1/), 2026-09-29) — a rewrite of version 1, not an upgrade.
The code of version 2 lives on the [`v2` branch](https://github.com/moyhig-ecs/ggblab/tree/v2); this `main` branch still holds
version 1 (1.8.1, a JupyterLab extension). Documentation for both: <https://ggblab.readthedocs.io/>.

## What version 2 is

- The applet is mounted by a trusted HTML output of a notebook cell. There is no JupyterLab extension to build or install.
- The kernel talks to the applet through a mailbox on its own Jupyter server (`ggblab.host.relay`, a Jupyter Server extension).
  The kernel is an HTTP client of that server. No comm, no comm target, no ipywidgets.
- The same mailbox and the same JavaScript serve every kernel language. Python and Julia hosts are included.
- The interface is a closed set of ten verbs over the GeoGebra Apps API: four writes (`eval`, `new`, `delete`, `xml_in`),
  three reads (`xml_out`, `value`, `kind`), one subscription (`listen`) and two projections (`png`, `svg`).
- Constructions written as text are parsed by a closed-world parser: 28 GeoGebra commands, labels referenced as `:label`.
  An unknown command is an error, not a guess.
- Runs under JupyterLab and JupyterHub on Kubernetes; a headless holder (no notebook open) is on the way for 2.0.0rc2.

## Install

Python 3.11 or later.

```bash
pip install ggblab==2.0.0rc1             # the core: applet host, server extension, parser
pip install "ggblab[extra]==2.0.0rc1"    # plus ggblab_extra: construction I/O, geometry IR, SymPy objects
```

Without a version, `pip install ggblab` installs 1.8.1 while 2.0.0 is a release candidate.

```python
from ggblab import GeoGebra
g = GeoGebra()          # displaying g mounts the applet in the cell output
g
g.command("A = (0, 0)", "B = (4, 0)", "C = (1, 3)", "Polygon(A, B, C)")
g.value("A")
```

Julia: `ggb"A = (0, 0)"` string macro and the same verbs, from the `GGBLab` package shipped inside the wheel (`julia/`).

## Links

- Documentation: <https://ggblab.readthedocs.io/> (quickstart, the ten verbs, the parser, Julia, reference)
- Version 2 source and changelog: [`v2` branch](https://github.com/moyhig-ecs/ggblab/tree/v2) ·
  [CHANGELOG](https://github.com/moyhig-ecs/ggblab/blob/v2/CHANGELOG.md) · [releases](https://github.com/moyhig-ecs/ggblab/releases)
- PyPI: <https://pypi.org/project/ggblab/>
- Blog: <https://moyhig-ecs.github.io/ggblab/>

## Version 1 (this branch)

Version 1 (1.8.1) is a JupyterLab extension with an IPython comm and an out-of-band socket. Its README is kept as
[README_v1.md](README_v1.md); install it with `pip install ggblab==1.8.1`. Version 2 does not read or extend version 1's code
and has no compatibility layer; the differences are tabulated in the
[v2 changelog](https://github.com/moyhig-ecs/ggblab/blob/v2/CHANGELOG.md).

## Funding

Development is supported by JSPS KAKENHI Grant Numbers JP26K06399 and JP21K18505 (Osaka University, D3 Center).

## License

See [LICENSE](LICENSE).
