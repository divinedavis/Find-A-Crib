"""Find A Crib growth engine.

A self-improving loop for organic traffic and revenue:

  ledger.py      the technique registry + measured-results store
  techniques.py  the executable techniques themselves (one function each)
  metrics.py     pulls daily traffic/conversion numbers and attributes them
  review.py      judges each active technique, retires the dead ones
  scout.py       shared Claude helpers (key, call, price, spend); the daily scout job was retired 2026-11-12
  report.py      the daily email

Run it through ../growth_daily.py.
"""
