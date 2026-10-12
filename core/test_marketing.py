from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from .marketing import zoominfo_enabled


@override_settings(ALLOWED_HOSTS=["aibiz.guru", "www.aibiz.guru", "localhost", "127.0.0.1", "preview.onrender.com"])
class ZoomInfoPlacementTests(SimpleTestCase):
    def request(self, path="/", host="aibiz.guru", authenticated=False):
        request = RequestFactory().get(path, HTTP_HOST=host)
        request.user = SimpleNamespace(is_authenticated=True) if authenticated else AnonymousUser()
        request.resolver_match = resolve(request.path_info)
        return request

    def test_public_tag_is_once_at_end_of_head(self):
        for path in ("/", "/demo/", "/industries/", "/growth-assessment/?mode=in-person"):
            request = self.request(path)
            html = render_to_string("base.html", request=request)
            self.assertEqual(html.count("52bd8117e51791833995"), 1)
            self.assertLess(html.index("52bd8117e51791833995"), html.index("</head>"))
        self.assertTrue(zoominfo_enabled(self.request(host="www.aibiz.guru")))

    def test_local_staging_and_signed_in_visitors_are_excluded(self):
        for host in ("localhost:8007", "127.0.0.1:8007", "preview.onrender.com"):
            self.assertFalse(zoominfo_enabled(self.request(host=host)))
        self.assertFalse(zoominfo_enabled(self.request(authenticated=True)))

    def test_private_routes_and_booking_confirmation_have_no_tag_even_when_signed_out(self):
        for path in ("/accounts/login/", "/accounts/signup/", "/crm/", "/training/",
                     "/owner/calendar/", "/demo/automotive/crm/", "/growth-assessment/confirmed/example-token/"):
            request = self.request(path)
            self.assertFalse(zoominfo_enabled(request))
            self.assertNotIn("52bd8117e51791833995", render_to_string("base.html", request=request))
