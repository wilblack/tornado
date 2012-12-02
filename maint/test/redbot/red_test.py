#!/usr/bin/env python

import logging
from redbot.droid import ResourceExpertDroid
import redbot.speak as rs
import thor
import threading
from tornado import gen
from tornado.options import parse_command_line
from tornado.testing import AsyncHTTPTestCase, LogTrapTestCase
from tornado.web import RequestHandler, Application, asynchronous
import unittest

class HelloHandler(RequestHandler):
    def get(self):
        self.write("Hello world")

class RedirectHandler(RequestHandler):
    def get(self, path):
        self.redirect(path, status=int(self.get_argument('status', '302')))

class PostHandler(RequestHandler):
    def post(self):
        assert self.get_argument('foo') == 'bar'
        self.redirect('/hello', status=303)

class ChunkedHandler(RequestHandler):
    @asynchronous
    @gen.engine
    def get(self):
        self.write('hello ')
        yield gen.Task(self.flush)
        self.write('world')
        yield gen.Task(self.flush)
        self.finish()

class TestMixin(object):
    def get_handlers(self):
        return [
            ('/hello', HelloHandler),
            ('/redirect(/.*)', RedirectHandler),
            ('/post', PostHandler),
            ('/chunked', ChunkedHandler),
            ]

    def get_app_kwargs(self):
        return dict(static_path='.')

    def check_url(self, path, method='GET', body=None, headers=None,
                  expected_status=200, allowed_warnings=None):
        url = self.get_url(path)
        state = self.run_redbot(url, method, body, headers)
        if not state.res_complete:
            if isinstance(state.res_error, Exception):
                logging.warning((state.res_error.desc, vars(state.res_error), url))
                raise state.res_error
            else:
                raise Exception("unknown error; incomplete response")

        self.assertEqual(int(state.res_status), expected_status)

        allowed_warnings = tuple(allowed_warnings or ())
        # We can't set a non-heuristic freshness at the framework level,
        # so just ignore this error.
        allowed_warnings += (rs.FRESHNESS_HEURISTIC,)

        errors = []
        warnings = []
        for msg in state.messages:
            if msg.level == 'bad':
                logger = logging.error
                errors.append(msg)
            elif msg.level == 'warning':
                logger = logging.warning
                if not isinstance(msg, allowed_warnings):
                    warnings.append(msg)
            elif msg.level in ('good', 'info', 'uri'):
                logger = logging.info
            else:
                raise Exception('unknown level' + msg.level)
            logger('%s: %s (%s)', msg.category, msg.show_summary('en'),
                   msg.__class__.__name__)
            logger(msg.show_text('en'))

        self.assertEqual(len(warnings) + len(errors), 0,
                         'Had %d unexpected warnings and %d errors' %
                         (len(warnings), len(errors)))

    def run_redbot(self, url, method, body, headers):
        red = ResourceExpertDroid(url, method=method, req_body=body,
                                  req_hdrs=headers)
        def work():
            red.run(thor.stop)
            thor.run()
            self.io_loop.add_callback(self.stop)
        thread = threading.Thread(target=work)
        thread.start()
        self.wait()
        thread.join()
        return red.state

    def test_hello(self):
        self.check_url('/hello')

    def test_static(self):
        # TODO: 304 responses SHOULD return the same etag that a full
        # response would.  We currently do for If-None-Match, but not
        # for If-Modified-Since (because IMS does not otherwise
        # require us to read the file from disk)
        self.check_url('/static/red_test.py',
                       allowed_warnings=[rs.MISSING_HDRS_304])

    def test_static_versioned_url(self):
        self.check_url('/static/red_test.py?v=1234',
                       allowed_warnings=[rs.MISSING_HDRS_304])

    def test_redirect(self):
        self.check_url('/redirect/hello', expected_status=302)

    def test_permanent_redirect(self):
        self.check_url('/redirect/hello?status=301', expected_status=301)

    def test_404(self):
        self.check_url('/404', expected_status=404)

    def test_post(self):
        body = 'foo=bar'
        # Without an explicit Content-Length redbot will try to send the
        # request chunked.
        self.check_url(
            '/post', method='POST', body=body,
            headers=[('Content-Length', str(len(body))),
                     ('Content-Type', 'application/x-www-form-urlencoded')],
            expected_status=303)

    def test_chunked(self):
        self.check_url('/chunked')

class DefaultHTTPTest(AsyncHTTPTestCase, LogTrapTestCase, TestMixin):
    def get_app(self):
        return Application(self.get_handlers(), **self.get_app_kwargs())

if __name__ == '__main__':
    parse_command_line()
    unittest.main()
