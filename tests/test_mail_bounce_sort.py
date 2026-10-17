import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mail_bounce_sort as s


class FakeIMAP:
    def __init__(self, hits): self.hits, self.asked = hits, []
    def uid(self, cmd, charset, key, val):
        self.asked.append(val)
        return "OK", [b" ".join(self.hits.get(val.strip('"'), []))]


class BounceSortTest(unittest.TestCase):
    def test_union_of_senders_sorted_numerically(self):
        M = FakeIMAP({"Mail Delivery": [b"10", b"9"], "MAILER-DAEMON": [b"9", b"100"]})
        self.assertEqual(s.bounce_uids(M), [b"9", b"10", b"100"])
        self.assertEqual(M.asked, ['"Mail Delivery"', '"MAILER-DAEMON"', '"postmaster@"'])

    def test_nothing_to_move(self):
        self.assertEqual(s.bounce_uids(FakeIMAP({})), [])

    def test_imap_host_from_smtp(self):
        os.environ.pop("IMAP_HOST", None); os.environ["SMTP_HOST"] = "smtp.privateemail.com"
        self.assertEqual(s.imap_host(), "mail.privateemail.com")


if __name__ == "__main__":
    unittest.main()
