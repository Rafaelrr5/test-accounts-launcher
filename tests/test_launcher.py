import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import launcher as s  # noqa: E402

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # gitleaks:allow - public RFC 6238 test key ("12345678901234567890")


class TotpTest(unittest.TestCase):
    def test_rfc6238_vectors(self):  # RFC values are 8 digits; the 6-digit code is their last 6
        for t, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
            self.assertEqual(s.totp(RFC_SECRET, t), code)

    def test_normalize_key(self):
        self.assertEqual(s.normalize_key("gezd gnbv gy3t qojq"), "GEZDGNBVGY3TQOJQ")
        with self.assertRaises(Exception):
            s.normalize_key("not-a-key!")


class ParsingTest(unittest.TestCase):
    def test_key_and_recovery_codes_from_page_text(self):
        text = "Escaneie o QR code\nABCD EFGH IJKL MNOP\nSalve estes códigos\nab12-cd34-ef56-gh78\nzz99-yy88-xx77-ww66"
        self.assertEqual(s.KEY_RE.search(text).group(1), "ABCD EFGH IJKL MNOP")
        self.assertEqual(s.RECOVERY_RE.findall(text), ["ab12-cd34-ef56-gh78", "zz99-yy88-xx77-ww66"])

    def test_normalize_url(self):
        self.assertEqual(s.normalize_url(" https://app.example.com/new/login "), "https://app.example.com/new/login")
        self.assertEqual(s.normalize_url("http://localhost:3000/login"), "http://localhost:3000/login")
        for bad in ("app.example.com/login", "https://app.example.com/", "http://app.example.com/login"):
            with self.assertRaises(ValueError):
                s.normalize_url(bad)

    def test_logged_in(self):
        login = "https://app.example.com/new/login"
        self.assertTrue(s.is_logged_in("https://app.example.com/new/", login))
        self.assertTrue(s.is_logged_in("https://app.example.com/new/#/home", login))
        self.assertFalse(s.is_logged_in("https://app.example.com/new/login?step=2fa", login))
        self.assertFalse(s.is_logged_in("https://app.example.com/new/login/mfa", login))
        self.assertFalse(s.is_logged_in("https://other.example.com/new/", login))


class LinuxLauncherTest(unittest.TestCase):
    def test_desktop_exec_quoting(self):  # freedesktop spec: quote args, escape " ` $ \, then double \ and %
        self.assertEqual(s.desktop_exec(["/home/a b/py", "50%"]), '"/home/a b/py" "50%%"')
        self.assertEqual(s.desktop_exec(['x$y"z']), '"x\\\\$y\\\\"z"')


if __name__ == "__main__":
    unittest.main()
