"""flyer_reader.main re-reads a flyer whose cached reading came from an older
model (Haiku 4.5 merged household rows, 2026-11-12), and keeps serving that
old reading for flyers past the nightly limit until their turn."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flyer_reader as fr  # noqa: E402
import claude_features as cf  # noqa: E402


def run(cached_models, limit):
    d = tempfile.mkdtemp()
    listings = [{"href": f"https://x.test/{i}.pdf", "href_kind": "flyer", "address": f"{i} Main St"} for i in range(len(cached_models))]
    json.dump({"listings": listings}, open(os.path.join(d, "featured.json"), "w"))
    reads = []
    old = {n: getattr(fr, n) for n in ("rest", "rpc", "read_one", "source_text", "prewarm_apply_help", "Gateway")}

    def rest(path, method="GET", body=None, prefer=None):
        if method != "GET":
            return None
        i = next(k for k in range(len(listings)) if fr.hashlib.sha1(listings[k]["href"].encode()).hexdigest() in path)
        m = cached_models[i]
        return [{"payload": {"units": [{"old": True}], "verified": True, "model": m,
                             "reader": fr.READER if m == cf.HAIKU else None}}] if m else []

    class GW:
        def __init__(self, *a): pass
        def record(self, *a, **k): return 0

    fr.rest, fr.rpc, fr.Gateway = rest, (lambda *a, **k: 0), GW
    fr.read_one = lambda l: (reads.append(l["href"]) or ({"units": [{"new": True}], "verified": True, "model": cf.HAIKU},
                                                         {"model": cf.HAIKU, "input_tokens": 1, "output_tokens": 1,
                                                          "cache_write_tokens": 0, "cache_read_tokens": 0}))
    fr.source_text = lambda l: ""
    fr.prewarm_apply_help = lambda *a, **k: None
    argv = sys.argv
    sys.argv = ["flyer_reader.py", "--docroot", d, "--limit", str(limit)]
    try:
        fr.main()
    finally:
        sys.argv = argv
        for n, v in old.items():
            setattr(fr, n, v)
    return reads, json.load(open(os.path.join(d, "featured_units.json")))["listings"]


def test_older_model_is_reread_and_current_model_is_kept():
    reads, table = run(["claude-haiku-4-5", cf.HAIKU, None], limit=10)
    assert reads == ["https://x.test/0.pdf", "https://x.test/2.pdf"], reads
    assert table["https://x.test/0.pdf"]["units"] == [{"new": True}]
    assert table["https://x.test/1.pdf"]["units"] == [{"old": True}]


def test_past_the_limit_the_old_reading_stays_up():
    reads, table = run(["claude-haiku-4-5", "claude-haiku-4-5", "claude-haiku-4-5"], limit=1)
    assert reads == ["https://x.test/0.pdf"], reads
    assert table["https://x.test/1.pdf"]["units"] == [{"old": True}]
    assert table["https://x.test/2.pdf"]["units"] == [{"old": True}]



def test_printed_cents_become_whole_dollars_for_the_app():
    out = fr.whole_dollars({"units": [{"rent": 3249.65, "income_min": 115771, "income_max": 198510.4, "beds": 1}]})
    u = out["units"][0]
    assert (u["rent"], u["income_min"], u["income_max"]) == (3250, 115771, 198510), u
    assert all(isinstance(u[k], int) for k in fr.MONEY)
    nums = fr.source_numbers({"address": "2180 Arthur Avenue"}, "1 Bedroom $3,249.65 1 1-3 people $115,771 – $198,510")
    assert not cf.ungrounded("3249.65", nums) and cf.ungrounded("3299.65", nums)


def test_a_bedroom_groups_rent_fills_its_household_rows():
    rows = [{"beds": 0, "rent": 3543, "units_available": 2}, {"beds": 0, "rent": None, "units_available": None},
            {"beds": 1, "rent": 3600, "units_available": 8}, {"beds": 1, "rent": None, "units_available": None},
            {"beds": 1, "rent": 3784, "units_available": 37}, {"beds": 1, "rent": None, "units_available": None},
            {"beds": 2, "rent": None, "units_available": 1}]
    out = fr.fill_down_rent({"units": rows})["units"]
    assert [u["rent"] for u in out] == [3543, 3543, 3600, 3600, 3784, 3784, None]
    assert [u["units_available"] for u in out] == [2, None, 8, None, 37, None, 1]


if __name__ == "__main__":
    test_older_model_is_reread_and_current_model_is_kept()
    test_past_the_limit_the_old_reading_stays_up()
    test_printed_cents_become_whole_dollars_for_the_app()
    test_a_bedroom_groups_rent_fills_its_household_rows()
    print("ok flyer model refresh")
