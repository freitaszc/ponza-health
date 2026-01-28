"""Gunicorn configuration for Render/Python 3.13 compatibility."""

# Render + Python 3.13 can raise "non-blocking sockets are not supported"
# when Gunicorn tries to use sendfile on non-blocking sockets.
sendfile = False
