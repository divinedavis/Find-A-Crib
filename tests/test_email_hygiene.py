#!/usr/bin/env python3
"""Bounces stop the mail (owner, 2026-10-20: "im seeing a lot of delivery
status notification (delay) emails, why?"). mail_bounce_sort.py reads each
notice; emailkit.send() skips suppressed addresses; sign-up catches typos."""
import os
import re
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import mail_bounce_sort as mb  # noqa: E402
from growth import emailkit  # noqa: E402

DSN = """From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
Subject: Delivery Status Notification ({kind})
MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary="b"

--b
Content-Type: text/plain

Your message wasn't delivered.

--b
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; {rcpt}
Action: failed
Status: {status}
Diagnostic-Code: smtp; {diag}

--b--
"""


def dsn(rcpt, status, diag, kind="Failure"):
    return DSN.format(rcpt=rcpt, status=status, diag=diag, kind=kind).encode()


class Classify(unittest.TestCase):
    def test_dead_addresses_are_hard(self):
        for st, d in [("5.1.1", "550-5.1.1 The email account that you tried to reach does not exist"),
                      ("5.7.1", "554 5.7.1 <mahad.h@maio.com>: Recipient address rejected: user does not exist"),
                      ("5.0.0", "DNS Error: DNS error occurred while resolving the Mail Exchange (MX) server"),
                      ("5.2.2", "552-5.2.2 The recipient's inbox is out of storage space and inactive")]:
            self.assertEqual(mb.classify("Delivery Status Notification (Failure)", st, d), "hard", d)

    def test_full_inbox_and_delays_are_soft(self):
        self.assertEqual(mb.classify("Delivery Status Notification (Delay)", "4.2.2",
                                     "452-4.2.2 The recipient's inbox is out of storage space."), "soft")

    def test_a_refusal_of_our_sender_is_not_theirs(self):
        self.assertIsNone(mb.classify("Undelivered", "5.0.0", "550 5.1.1 <divine@findacrib.com>: unauthorized sender"))

    def test_parse_reads_the_recipient_and_kind(self):
        b = mb.parse_bounce(dsn("Testing@Gmail.com", "5.1.1", "550-5.1.1 does not exist"))
        self.assertEqual(b[:2], ("testing@gmail.com", "hard"))
        self.assertEqual(mb.parse_bounce(dsn("x@privaterelay.appleid.com", "5.0.0",
                                             "550 5.1.1 <divine@findacrib.com>: unauthorized sender")), None)
        self.assertIsNone(mb.parse_bounce(dsn("divine@findacrib.com", "5.1.1", "does not exist")), "never ourselves")


class SendSkipsSuppressed(unittest.TestCase):
    def test_suppressed_address_is_not_sent(self):
        emailkit._SUPPRESSED.update(at=time.time(), set=frozenset({"testing@gmail.com"}))
        self.assertTrue(emailkit.suppressed(" Testing@gmail.com "))
        self.assertFalse(emailkit.suppressed("someone@gmail.com"))
        self.assertIs(emailkit.send("testing@gmail.com", "s", "<p>h</p>", "t"), False, "returns before touching SMTP")


class SignupTypos(unittest.TestCase):
    def test_web_and_app_share_one_typo_list(self):
        web = open(os.path.join(ROOT, "index.html")).read()
        web_keys = set(re.findall(r"'([a-z.]+)': '[a-z.]+'", web[web.index("EMAIL_DOMAIN_FIX = {"):][:1200].split("};")[0]))
        swift = open(os.path.join(ROOT, "ios/FindACrib/Models/EmailCheck.swift")).read()
        app_keys = set(re.findall(r'"([a-z.]+)": "[a-z.]+"', swift))
        self.assertTrue(web_keys and web_keys == app_keys, web_keys ^ app_keys)
        self.assertIn("gmail.ckm", web_keys)

    def test_signup_checks_before_creating_the_account(self):
        web = open(os.path.join(ROOT, "index.html")).read()
        sub = web[web.index("authForm.addEventListener('submit'"):][:1500]
        self.assertLess(sub.index("emailFix(email)"), sub.index("supaClient.auth[fn]"))


if __name__ == "__main__":
    unittest.main()
