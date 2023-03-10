FROM jupyterhub/jupyterhub:3.1.0 as base-image

# Update system packages
COPY scripts/install-base-packages.sh .
RUN ./install-base-packages.sh && rm install-base-packages.sh

FROM base-image as dependencies-image

# Install system packages only needed for building dependencies.
COPY scripts/install-dependency-packages.sh .
RUN ./install-dependency-packages.sh && rm install-dependency-packages.sh

# Install the app's Python runtime dependencies
COPY requirements/main.txt ./requirements.txt
RUN pip install --quiet --no-cache-dir -r requirements.txt

FROM dependencies-image as runtime-image

# Install the nublado2 python module
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir .

# Create a non-root user to run the Hub
# Set the UID / GID to be 768.
# Note this is also used in the nublado2's values.yaml
RUN groupadd --gid 768 jovyan
RUN useradd --create-home jovyan --uid 768 --gid 768
WORKDIR /home/jovyan

USER jovyan
EXPOSE 8000
EXPOSE 8081
