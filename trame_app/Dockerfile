FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    git \
    curl \
    ca-certificates \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgomp1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade --no-cache-dir pip setuptools wheel

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml .
# Stub package so pip can resolve deps without the full source tree
RUN mkdir -p diadema && touch diadema/__init__.py && \
    pip install --no-cache-dir ".[dev]" && \
    pip install --no-cache-dir \
        "girdermedviewer @ git+https://github.com/KitwareMedical/GirderMedViewer.git"

# Patch upstream bug: set_vector_field_arrow_length and set_vector_field_arrow_thickness
# are imported in __init__.py but missing from vtk_utils.py
RUN python3 - <<'EOF'
import site, pathlib, textwrap

vtk_utils = pathlib.Path(site.getsitepackages()[0]) / \
    "girdermedviewer/app/widgets/utils/vtk/vtk_utils.py"

patch = textwrap.dedent("""

def set_vector_field_arrow_length(glyph_actor, arrow_length):
    if glyph_actor is None:
        return False
    mapper = glyph_actor.GetMapper()
    if mapper is None or mapper.GetScaleFactor() == arrow_length:
        return False
    mapper.SetScaleFactor(arrow_length)
    return True


def set_vector_field_arrow_thickness(glyph_actor, arrow_thickness):
    if glyph_actor is None:
        return False
    mapper = glyph_actor.GetMapper()
    if mapper is None:
        return False
    src_conn = mapper.GetInputConnection(1, 0)
    if src_conn is None:
        return False
    arrow_source = src_conn.GetProducer()
    if arrow_source is None or arrow_source.GetShaftRadius() == arrow_thickness:
        return False
    arrow_source.SetShaftRadius(arrow_thickness)
    return True
""")

content = vtk_utils.read_text()
if "def set_vector_field_arrow_length" not in content:
    vtk_utils.write_text(content + patch)
    print("Patch applied.")
else:
    print("Already patched, skipping.")
EOF

# Copy application source (invalidates cache only when source changes)
COPY diadema/ ./diadema/

EXPOSE 8888

CMD ["python3", "-m", "diadema.app", "--port", "8888", "--host", "0.0.0.0"]
