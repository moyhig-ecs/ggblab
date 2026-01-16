# Binder usage

This repository includes Binder configuration to let you try the `examples` notebooks online without local installation.

- Launch Binder (build may take a few minutes):

  https://mybinder.org/v2/gh/moyhig-ecs/ggblab/main?filepath=examples/example.ipynb

- The Binder environment will install the repository in editable mode and required Python packages listed in `binder/requirements.txt`.

- If you want to run a different example, update the `filepath` query parameter to point to the desired notebook under `examples/`.

Notes:
- The build runs `binder/postBuild`, which installs the package. If you need additional system packages, add them to `binder/apt.txt`.
- For heavy optional dependencies used in some examples, consider adding them to `binder/requirements.txt` to speed interactive use.
