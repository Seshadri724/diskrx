# Use dxcli inside a multi-stage build to catch image bloat early.
# The diagnose step prints what's taking space *before* the layer is sealed.

FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN ./build.sh

# --- Diagnose the builder layer before the final stage ----------------------
RUN pip install --no-cache-dir dxcli \
 && dxcli diagnose / --classify \
 && pip uninstall -y dxcli

# --- Final, slim image ------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/dist /app/dist
CMD ["python", "-m", "myapp"]
