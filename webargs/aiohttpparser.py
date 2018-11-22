# -*- coding: utf-8 -*-
"""aiohttp request argument parsing module.

Example: ::

    import asyncio
    from aiohttp import web

    from webargs import fields
    from webargs.aiohttpparser import use_args


    hello_args = {
        'name': fields.Str(required=True)
    }
    @asyncio.coroutine
    @use_args(hello_args)
    def index(request, args):
        return web.Response(
            body='Hello {}'.format(args['name']).encode('utf-8')
        )

    app = web.Application()
    app.router.add_route('GET', '/', index)
"""
import json
import warnings

import aiohttp
from aiohttp import web
from aiohttp import web_exceptions

from webargs import core
from webargs.asyncparser import AsyncParser

AIOHTTP_MAJOR_VERSION = int(aiohttp.__version__.split(".")[0])
if AIOHTTP_MAJOR_VERSION < 2:
    warnings.warn(
        "Support for aiohttp<2.0.0 is deprecated and is removed in webargs 2.0.0",
        DeprecationWarning,
    )


def is_json_request(req):
    content_type = req.content_type
    return core.is_json(content_type)


class HTTPUnprocessableEntity(web.HTTPClientError):
    status_code = 422


# Mapping of status codes to exception classes
# Adapted from werkzeug
exception_map = {422: HTTPUnprocessableEntity}
# Collect all exceptions from aiohttp.web_exceptions
def _find_exceptions():
    for name in web_exceptions.__all__:
        obj = getattr(web_exceptions, name)
        try:
            is_http_exception = issubclass(obj, web_exceptions.HTTPException)
        except TypeError:
            is_http_exception = False
        if not is_http_exception or obj.status_code is None:
            continue
        old_obj = exception_map.get(obj.status_code, None)
        if old_obj is not None and issubclass(obj, old_obj):
            continue
        exception_map[obj.status_code] = obj


_find_exceptions()
del _find_exceptions


class AIOHTTPParser(AsyncParser):
    """aiohttp request argument parser."""

    __location_map__ = dict(
        match_info="parse_match_info", **core.Parser.__location_map__
    )

    def parse_querystring(self, req, name, field):
        """Pull a querystring value from the request."""
        return core.get_value(req.query, name, field)

    async def parse_form(self, req, name, field):
        """Pull a form value from the request."""
        post_data = self._cache.get("post")
        if post_data is None:
            self._cache["post"] = await req.post()
        return core.get_value(self._cache["post"], name, field)

    async def parse_json(self, req, name, field):
        """Pull a json value from the request."""
        json_data = self._cache.get("json")
        if json_data is None:
            if not (req.body_exists and is_json_request(req)):
                return core.missing
            try:
                json_data = await req.json()
            except json.JSONDecodeError as e:
                if e.doc == "":
                    return core.missing
                else:
                    raise e
            self._cache["json"] = json_data
        return core.get_value(json_data, name, field, allow_many_nested=True)

    def parse_headers(self, req, name, field):
        """Pull a value from the header data."""
        return core.get_value(req.headers, name, field)

    def parse_cookies(self, req, name, field):
        """Pull a value from the cookiejar."""
        return core.get_value(req.cookies, name, field)

    def parse_files(self, req, name, field):
        raise NotImplementedError(
            "parse_files is not implemented. You may be able to use parse_form for "
            "parsing upload data."
        )

    def parse_match_info(self, req, name, field):
        """Pull a value from the request's ``match_info``."""
        return core.get_value(req.match_info, name, field)

    def get_request_from_view_args(self, view, args, kwargs):
        """Get request object from a handler function or method. Used internally by
        ``use_args`` and ``use_kwargs``.
        """
        req = None
        for arg in args:
            if isinstance(arg, web.Request):
                req = arg
                break
            elif isinstance(arg, web.View):
                req = arg.request
                break
        assert isinstance(req, web.Request), "Request argument not found for handler"
        return req

    def handle_error(self, error, req, schema, error_status_code, error_headers):
        """Handle ValidationErrors and return a JSON response of error messages to the client."""
        error_class = exception_map.get(error_status_code or self.DEFAULT_VALIDATION_STATUS)
        if not error_class:
            raise LookupError("No exception for {0}".format(error.status_code))
        headers = error_headers
        raise error_class(
            body=json.dumps(error.messages).encode("utf-8"),
            headers=headers,
            content_type="application/json",
        )


parser = AIOHTTPParser()
use_args = parser.use_args
use_kwargs = parser.use_kwargs
