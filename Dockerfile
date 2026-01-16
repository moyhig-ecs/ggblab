FROM jupyter/minimal-notebook:python-3.10

# Install minimal system deps if needed, then install ggblab
USER root

# RUN apt-get update \
#     && apt-get install -y --no-install-recommends build-essential \
#     && apt-get clean \
#     && rm -rf /var/lib/apt/lists/*

# Install ggblab (assumes prebuilt wheels are available on PyPI)
RUN pip install --no-cache-dir ggblab

# Switch back to default notebook user
USER $NB_UID

ENV JUPYTER_ENABLE_LAB=yes

# Keep default entrypoint from base image (start-notebook.sh)
