"""Main module of the API.

It contains the FastAPI instance and the root endpoint.
"""

from echoroo.system import create_app, get_settings

settings = get_settings()
app = create_app(settings)
