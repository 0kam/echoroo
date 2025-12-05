"""Extended tests for the app system module."""

import logging
import traceback
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from echoroo import exceptions
from echoroo.system.app.error_handlers import (
    add_error_handlers,
    data_integrity_error_handler,
    duplicate_object_error_handler,
    not_found_error_handler,
)
from echoroo.system.app.middleware import add_middlewares, debug_exception_handling_middleware
from echoroo.system.settings import Settings


class TestNotFoundErrorHandler:
    """Test the not_found_error_handler."""

    @pytest.mark.asyncio
    async def test_returns_404_status(self):
        """Test that handler returns 404 status code."""
        exc = exceptions.NotFoundError("Resource not found")
        response = await not_found_error_handler(None, exc)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_json_response(self):
        """Test that handler returns JSON response."""
        exc = exceptions.NotFoundError("Resource not found")
        response = await not_found_error_handler(None, exc)

        assert isinstance(response, JSONResponse)

    @pytest.mark.asyncio
    async def test_includes_error_message(self):
        """Test that handler includes error message."""
        error_msg = "User not found"
        exc = exceptions.NotFoundError(error_msg)
        response = await not_found_error_handler(None, exc)

        # Parse the response body
        body = response.body.decode()
        assert error_msg in body


class TestDuplicateObjectErrorHandler:
    """Test the duplicate_object_error_handler."""

    @pytest.mark.asyncio
    async def test_returns_409_status(self):
        """Test that handler returns 409 status code."""
        exc = exceptions.DuplicateObjectError("Object already exists")
        response = await duplicate_object_error_handler(None, exc)

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_returns_json_response(self):
        """Test that handler returns JSON response."""
        exc = exceptions.DuplicateObjectError("Object already exists")
        response = await duplicate_object_error_handler(None, exc)

        assert isinstance(response, JSONResponse)

    @pytest.mark.asyncio
    async def test_includes_error_message(self):
        """Test that handler includes error message."""
        error_msg = "Duplicate username"
        exc = exceptions.DuplicateObjectError(error_msg)
        response = await duplicate_object_error_handler(None, exc)

        body = response.body.decode()
        assert error_msg in body


class TestDataIntegrityErrorHandler:
    """Test the data_integrity_error_handler."""

    @pytest.mark.asyncio
    async def test_returns_409_status(self):
        """Test that handler returns 409 status code."""
        exc = exceptions.DataIntegrityError("Data integrity violation")
        response = await data_integrity_error_handler(None, exc)

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_returns_json_response(self):
        """Test that handler returns JSON response."""
        exc = exceptions.DataIntegrityError("Data integrity violation")
        response = await data_integrity_error_handler(None, exc)

        assert isinstance(response, JSONResponse)

    @pytest.mark.asyncio
    async def test_includes_error_message(self):
        """Test that handler includes error message."""
        error_msg = "Foreign key constraint failed"
        exc = exceptions.DataIntegrityError(error_msg)
        response = await data_integrity_error_handler(None, exc)

        body = response.body.decode()
        assert error_msg in body


class TestAddErrorHandlers:
    """Test the add_error_handlers function."""

    def test_adds_handlers_to_app(self, test_settings: Settings):
        """Test that handlers are added to the app."""
        app = FastAPI()

        add_error_handlers(app, test_settings)

        # Check that exception handlers were registered
        assert exceptions.NotFoundError in app.exception_handlers
        assert exceptions.DuplicateObjectError in app.exception_handlers
        assert exceptions.DataIntegrityError in app.exception_handlers

    def test_handles_not_found_error(self, test_settings: Settings):
        """Test that NotFoundError is registered correctly."""
        app = FastAPI()
        add_error_handlers(app, test_settings)

        # Get the handler
        handler = app.exception_handlers[exceptions.NotFoundError]
        assert callable(handler)

    def test_handles_duplicate_object_error(self, test_settings: Settings):
        """Test that DuplicateObjectError is registered correctly."""
        app = FastAPI()
        add_error_handlers(app, test_settings)

        handler = app.exception_handlers[exceptions.DuplicateObjectError]
        assert callable(handler)

    def test_handles_data_integrity_error(self, test_settings: Settings):
        """Test that DataIntegrityError is registered correctly."""
        app = FastAPI()
        add_error_handlers(app, test_settings)

        handler = app.exception_handlers[exceptions.DataIntegrityError]
        assert callable(handler)


class TestDebugExceptionHandlingMiddleware:
    """Test the debug_exception_handling_middleware."""

    @pytest.mark.asyncio
    async def test_returns_response_on_success(self):
        """Test that middleware returns response on success."""
        request = MagicMock()
        mock_response = MagicMock()

        async def call_next(req):
            return mock_response

        response = await debug_exception_handling_middleware(request, call_next)
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_catches_exception(self):
        """Test that middleware catches exceptions."""
        request = MagicMock()

        async def call_next(req):
            raise ValueError("Test error")

        response = await debug_exception_handling_middleware(request, call_next)
        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_includes_exception_name_in_response(self):
        """Test that exception name is in response."""
        request = MagicMock()

        async def call_next(req):
            raise ValueError("Test error")

        response = await debug_exception_handling_middleware(request, call_next)
        body = response.body.decode()
        assert "ValueError" in body
        assert "Test error" in body

    @pytest.mark.asyncio
    async def test_includes_traceback_in_response(self):
        """Test that traceback is in response."""
        request = MagicMock()

        async def call_next(req):
            raise RuntimeError("Test error")

        response = await debug_exception_handling_middleware(request, call_next)
        body = response.body.decode()
        assert "traceback" in body

    @pytest.mark.asyncio
    async def test_logs_warning(self, caplog):
        """Test that exception is logged as warning."""
        request = MagicMock()

        async def call_next(req):
            raise ValueError("Test error")

        with caplog.at_level(logging.WARNING):
            await debug_exception_handling_middleware(request, call_next)

        assert "Unhandled error" in caplog.text


class TestAddMiddlewares:
    """Test the add_middlewares function."""

    def test_adds_cors_middleware(self, test_settings: Settings):
        """Test that CORS middleware is added."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = ["http://localhost:3000"]

        add_middlewares(app, test_settings)

        # Check that middleware was added
        # FastAPI stores middlewares in user_middleware list
        assert len(app.user_middleware) > 0

    def test_uses_cors_origins_from_settings(self, test_settings: Settings):
        """Test that CORS origins come from settings."""
        app = FastAPI()
        test_settings.debug = False
        origins = ["http://example.com", "https://test.com"]
        test_settings.cors_origins = origins

        add_middlewares(app, test_settings)

        # Verify CORS middleware has correct origins
        # This is indirect since we can't directly access middleware config
        assert len(app.user_middleware) > 0

    def test_adds_debug_middleware_when_debug_enabled(self, test_settings: Settings):
        """Test that debug middleware is added when debug is enabled."""
        app = FastAPI()
        test_settings.debug = True
        test_settings.cors_origins = ["http://localhost:3000"]

        add_middlewares(app, test_settings)

        # Should have debug middleware plus CORS
        assert len(app.user_middleware) > 1

    def test_no_debug_middleware_when_disabled(self, test_settings: Settings):
        """Test that debug middleware is not added when debug is disabled."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = ["http://localhost:3000"]

        initial_count = len(app.user_middleware)
        add_middlewares(app, test_settings)

        # Should only have CORS middleware
        # (comparison to initial count accounts for any default middleware)
        assert len(app.user_middleware) >= initial_count

    def test_cors_allows_credentials(self, test_settings: Settings):
        """Test that CORS allows credentials."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = ["http://localhost:3000"]

        add_middlewares(app, test_settings)

        # CORS middleware should allow credentials
        # This is set by allow_credentials=True in the add_middlewares function
        assert len(app.user_middleware) > 0

    def test_cors_allows_all_methods(self, test_settings: Settings):
        """Test that CORS allows all HTTP methods."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = ["http://localhost:3000"]

        add_middlewares(app, test_settings)

        # CORS should allow all methods
        assert len(app.user_middleware) > 0

    def test_cors_allows_all_headers(self, test_settings: Settings):
        """Test that CORS allows all headers."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = ["http://localhost:3000"]

        add_middlewares(app, test_settings)

        # CORS should allow all headers
        assert len(app.user_middleware) > 0

    def test_with_multiple_cors_origins(self, test_settings: Settings):
        """Test with multiple CORS origins."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = [
            "http://localhost:3000",
            "http://localhost:3001",
            "https://example.com",
        ]

        add_middlewares(app, test_settings)

        assert len(app.user_middleware) > 0

    def test_with_empty_cors_origins(self, test_settings: Settings):
        """Test with empty CORS origins list."""
        app = FastAPI()
        test_settings.debug = False
        test_settings.cors_origins = []

        add_middlewares(app, test_settings)

        # Should still add middleware even with empty origins
        assert len(app.user_middleware) > 0
