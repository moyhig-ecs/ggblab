FROM jupyter/minimal-notebook:python-3.10

# Use root to install system packages and Python deps
USER root

# Install any minimal system dependencies (uncomment if needed)
# RUN apt-get update \
#     && apt-get install -y --no-install-recommends build-essential \
#     && apt-get clean \
#     && rm -rf /var/lib/apt/lists/*

# Copy requirements if present and install Python packages
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt || true

# Ensure jupyterlab is available (minimal-notebook may not include latest lab)
RUN pip install --no-cache-dir jupyterlab

# Install ggblab (if not provided via requirements)
RUN pip install --no-cache-dir ggblab || true

 # Copy binder helpers into image and make executable
 COPY binder /home/jovyan/binder
 RUN chown -R $NB_UID:$NB_GID /home/jovyan/binder && chmod +x /home/jovyan/binder/start

# Expose default Jupyter port and provide environment-configurable PORT
ENV PORT=8888
EXPOSE ${PORT}

# Switch back to default notebook user for security
USER $NB_UID

# Ensure Lab UI is enabled
ENV JUPYTER_ENABLE_LAB=yes

# Start binder/start (which syncs repo then launches JupyterLab)
ENTRYPOINT ["/home/jovyan/binder/start"]
