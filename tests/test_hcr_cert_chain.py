"""scrape_hcr repairs its own certificate chain, and never by trusting more.

HousingSearch.ny.gov does not send its GlobalSign intermediate. The scraper
pinned one in hcr_chain.pem, and on 2026-11-23 the portal renewed onto a new
quarterly intermediate: every hourly run failed verification and hcr.json went
ten hours stale before a person swapped the file. heal_chain() now fetches the
named intermediate itself. These pin the two halves of that: the feed comes
back without a person, and nothing a stranger hands us is trusted.

No test here opens a socket: urlopen, the opener and the certificate fetch are
all replaced. The one real subprocess is `openssl` on a throwaway certificate.
"""
import shutil
import ssl
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import scrape_hcr as S

ROOT = Path(__file__).resolve().parent.parent
GOOD = "http://secure.globalsign.com/cacert/gsatlasr46ovtlsca2026q4.crt"
PEM = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"


def bad_chain():
    return urllib.error.URLError(ssl.SSLCertVerificationError(1, "unable to get local issuer certificate"))


class Reply:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


def text_with(url):
    return mock.Mock(stdout=f"   Authority Information Access:\n      OCSP - URI:http://ocsp.example\n"
                            f"      CA Issuers - URI:{url}\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name, value in (("_healed", False), ("_ctx", mock.Mock()), ("CHAIN_AUTO", self.dir / "auto.pem")):
            p = mock.patch.object(S, name, value)
            p.start()
            self.addCleanup(p.stop)

    def opener(self, body):
        op = mock.Mock()
        op.open.return_value = Reply(body)
        return mock.patch.object(S.urllib.request, "build_opener", return_value=op), op


class GetRetries(Base):
    def test_a_broken_chain_on_the_portal_is_repaired_and_the_request_retried(self):
        with mock.patch.object(S.urllib.request, "urlopen", side_effect=[bad_chain(), Reply(b"<html>ok")]) as uo, \
             mock.patch.object(S, "heal_chain", return_value=True) as heal:
            self.assertEqual(S.get(S.SITE + "/housing/s/"), "<html>ok")
        heal.assert_called_once_with()
        self.assertEqual(uo.call_count, 2)

    def test_a_repair_that_fails_leaves_the_original_error(self):
        with mock.patch.object(S.urllib.request, "urlopen", side_effect=[bad_chain()]), \
             mock.patch.object(S, "heal_chain", return_value=False):
            with self.assertRaises(urllib.error.URLError):
                S.get(S.SITE + "/housing/s/")

    def test_another_host_with_a_bad_certificate_is_never_repaired(self):
        # the geocoders go through get() too; a bad certificate there is theirs to fix
        for url in (S.GEOSEARCH + "?text=x", "https://housingsearch.hcr.ny.gov.evil.example/housing/s/"):
            with mock.patch.object(S.urllib.request, "urlopen", side_effect=[bad_chain()]), \
                 mock.patch.object(S, "heal_chain") as heal:
                with self.assertRaises(urllib.error.URLError):
                    S.get(url)
            heal.assert_not_called()

    def test_a_timeout_is_not_a_certificate_problem(self):
        with mock.patch.object(S.urllib.request, "urlopen", side_effect=[urllib.error.URLError(TimeoutError())]), \
             mock.patch.object(S, "heal_chain") as heal:
            with self.assertRaises(urllib.error.URLError):
                S.get(S.SITE + "/housing/s/")
        heal.assert_not_called()


class Heal(Base):
    def run_heal(self, body, trusted=True, url=GOOD):
        patch_opener, op = self.opener(body)
        with mock.patch.object(S.ssl, "get_server_certificate", return_value=PEM), \
             mock.patch.object(S, "aia_url", return_value=url), patch_opener, \
             mock.patch.object(S, "chains_to_a_trusted_root", return_value=trusted) as check:
            return S.heal_chain(), op, check

    def test_a_vouched_for_intermediate_is_loaded_and_saved(self):
        ok, op, check = self.run_heal(PEM.encode())
        self.assertTrue(ok)
        check.assert_called_once_with(PEM)
        S._ctx.load_verify_locations.assert_called_once_with(cadata=PEM)
        self.assertEqual(S.CHAIN_AUTO.read_text(), PEM)
        self.assertEqual(op.open.call_args[0][0].full_url, GOOD)

    def test_the_binary_form_the_ca_serves_is_accepted(self):
        der = ssl.PEM_cert_to_DER_cert(PEM)
        ok, _, check = self.run_heal(der)
        self.assertTrue(ok)
        self.assertEqual(ssl.PEM_cert_to_DER_cert(check.call_args[0][0]), der)

    def test_an_intermediate_no_root_vouches_for_is_thrown_away(self):
        ok, _, _ = self.run_heal(PEM.encode(), trusted=False)
        self.assertFalse(ok)
        S._ctx.load_verify_locations.assert_not_called()
        self.assertFalse(S.CHAIN_AUTO.exists())

    def test_no_usable_address_means_no_download(self):
        ok, op, check = self.run_heal(PEM.encode(), url=None)
        self.assertFalse(ok)
        op.open.assert_not_called()
        check.assert_not_called()

    def test_an_oversized_download_is_refused(self):
        ok, _, check = self.run_heal(b"x" * (S.AIA_MAX + 1))
        self.assertFalse(ok)
        check.assert_not_called()

    def test_it_runs_once_per_run(self):
        self.assertTrue(self.run_heal(PEM.encode())[0])
        ok, op, _ = self.run_heal(PEM.encode())
        self.assertFalse(ok)
        op.open.assert_not_called()

    def test_a_network_failure_is_a_no_not_a_crash(self):
        with mock.patch.object(S.ssl, "get_server_certificate", side_effect=OSError("down")):
            self.assertFalse(S.heal_chain())

    def test_a_read_only_checkout_still_repairs_this_run(self):
        with mock.patch.object(S, "CHAIN_AUTO", self.dir / "missing-dir" / "auto.pem"):
            ok, _, _ = self.run_heal(PEM.encode())
        self.assertTrue(ok)

    def test_redirects_are_not_followed(self):
        self.assertIsNone(S._NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://10.0.0.1/"))


class Address(unittest.TestCase):
    def url_for(self, printed):
        with mock.patch.object(S.subprocess, "run", return_value=text_with(printed)):
            return S.aia_url(PEM)

    def test_the_ca_address_is_returned(self):
        self.assertEqual(self.url_for(GOOD), GOOD)

    def test_addresses_off_the_list_are_refused(self):
        # the certificate is unverified when this is read: it must not be able
        # to point the server at an address of its choosing
        for bad in ("http://169.254.169.254/metadata/v1/", "http://localhost/x.crt",
                    "http://evil.example/secure.globalsign.com.crt",
                    "http://secure.globalsign.com.evil.example/x.crt",
                    "http://secure.globalsign.com:8080/x.crt",
                    "http://user@evil.example/x.crt",
                    "file:///etc/passwd", "ftp://secure.globalsign.com/x.crt"):
            self.assertIsNone(self.url_for(bad), bad)

    def test_no_address_or_no_openssl_is_none(self):
        with mock.patch.object(S.subprocess, "run", return_value=mock.Mock(stdout="no extensions")):
            self.assertIsNone(S.aia_url(PEM))
        with mock.patch.object(S.subprocess, "run", side_effect=FileNotFoundError("openssl")):
            self.assertIsNone(S.aia_url(PEM))


@unittest.skipUnless(shutil.which("openssl"), "needs the openssl command")
class RealOpenssl(unittest.TestCase):
    def test_a_certificate_someone_signed_for_themselves_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            made = subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                 "-keyout", f"{d}/k.pem", "-out", f"{d}/c.pem", "-days", "1",
                 "-subj", "/CN=GlobalSign Atlas R46 OV TLS CA 2026 Q4"], capture_output=True)
            if made.returncode:
                self.skipTest("this openssl cannot make a test certificate")
            with open(f"{d}/c.pem") as f:
                pem = f.read()
        self.assertFalse(S.chains_to_a_trusted_root(pem))
        self.assertEqual(S.aia_url(pem), None)

    def test_rubbish_is_not_trusted(self):
        self.assertFalse(S.chains_to_a_trusted_root("not a certificate"))


class Files(unittest.TestCase):
    def test_every_checked_in_certificate_loads(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cafile=str(ROOT / "pipeline" / "hcr_chain.pem"))
        names = [dict(x[0] for x in c["subject"])["commonName"] for c in ctx.get_ca_certs()]
        self.assertIn("GlobalSign Atlas R46 OV TLS CA 2026 Q4", names)

    def test_the_fetched_copy_is_never_committed(self):
        self.assertIn("hcr_chain.auto.pem", (ROOT / ".gitignore").read_text().split())
        self.assertEqual(S.CHAIN_AUTO.name, "hcr_chain.auto.pem")
        self.assertEqual(S.AIA_HOSTS, {"secure.globalsign.com"})


if __name__ == "__main__":
    unittest.main()
