'''Stubs for tornado HTTP clients'''
from __future__ import absolute_import

import functools
from six import BytesIO

from tornado import httputil
from tornado.httpclient import HTTPResponse

from vcr.errors import CannotOverwriteExistingCassetteException
from vcr.request import Request


def vcr_fetch_impl(cassette, real_fetch_impl):

    @functools.wraps(real_fetch_impl)
    def new_fetch_impl(self, request, callback):
        headers = dict(request.headers)
        if request.user_agent:
            headers.setdefault('User-Agent', request.user_agent)

        # TODO body_producer, header_callback, and streaming_callback are not
        # yet supported.

        unsupported_call = (
            request.body_producer is not None or
            request.header_callback is not None or
            request.streaming_callback is not None
        )
        if unsupported_call:
            response = HTTPResponse(
                request,
                599,
                error=Exception(
                    "The request (%s) uses AsyncHTTPClient functionality "
                    "that is not yet supported by VCR.py. Please make the "
                    "request outside a VCR.py context." % repr(request)
                ),
            )
            return callback(response)

        vcr_request = Request(
            request.method,
            request.url,
            request.body,
            headers,
        )

        if cassette.can_play_response_for(vcr_request):
            vcr_response = cassette.play_response(vcr_request)
            headers = httputil.HTTPHeaders()

            recorded_headers = vcr_response['headers']
            if isinstance(recorded_headers, dict):
                recorded_headers = recorded_headers.items()
            for k, vs in recorded_headers:
                for v in vs:
                    headers.add(k, v)
            response = HTTPResponse(
                request,
                code=vcr_response['status']['code'],
                reason=vcr_response['status']['message'],
                headers=headers,
                buffer=BytesIO(vcr_response['body']['string']),
            )
            return callback(response)
        else:
            if cassette.write_protected and cassette.filter_request(
                vcr_request
            ):
                response = HTTPResponse(
                    request,
                    599,
                    error=CannotOverwriteExistingCassetteException(
                        "No match for the request (%r) was found. "
                        "Can't overwrite existing cassette (%r) in "
                        "your current record mode (%r)."
                        % (vcr_request, cassette._path, cassette.record_mode)
                    ),
                )
                return callback(response)

            def new_callback(response):
                headers = [
                    (k, response.headers.get_list(k))
                    for k in response.headers.keys()
                ]

                vcr_response = {
                    'status': {
                        'code': response.code,
                        'message': response.reason,
                    },
                    'headers': headers,
                    'body': {'string': response.body},
                }
                cassette.append(vcr_request, vcr_response)
                return callback(response)

            real_fetch_impl(self, request, new_callback)

    return new_fetch_impl