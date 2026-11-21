"""featured_rerentals.gallery_pick — which photos on a listing page are its own."""
import featured_rerentals as F


def c(u, w=1280):
    return {"u": u, "w": w}


def test_house_number_keeps_this_buildings_photos():
    cands = [c("https://mgny.com/wp/111-Willoughby-St-Photo-1-1024x683.jpg"),
             c("https://mgny.com/wp/111-Willoughby-St-Photo-2.jpg"),
             c("https://mgny.com/wp/1025_Willoughby_The-Michaels-1.jpg"),
             c("https://mgny.com/wp/og-default-mgny-1200x630-1.jpg", 0)]
    got = F.gallery_pick(cands, "111 Willoughby Street, Brooklyn NY 11201")
    assert len(got) == 2 and all("111-Willoughby" in u for u in got)


def test_opaque_names_kept_but_noise_dropped():
    cands = [c("https://cdn.example.com/28453124.png", 2000),
             c("https://cdn.example.com/logo.png", 2000),
             c("https://cdn.example.com/Cove-Max-rents-1.png", 757),
             c("https://cdn.example.com/28453138.png", 300),       # thumbnail
             c("https://cdn.example.com/28453143.jpg", 2000)]
    assert F.gallery_pick(cands, "75 Dupont Street Unit 421") == [
        "https://cdn.example.com/28453124.png", "https://cdn.example.com/28453143.jpg"]


def test_wordpress_sizes_of_one_photo_count_once():
    cands = [c("https://x.com/a/photo-768x512.jpg"), c("https://x.com/a/photo.jpg")]
    assert len(F.gallery_pick(cands, "")) == 1


def test_one_named_thumbnail_does_not_drop_the_real_photos():
    # iAfford, 2026-10-04: one "1420-stebbins..." hero beside opaque photo ids.
    cands = [c("https://ik.io/1420-stebbins-avenue-the-bronx.jpg", 840),
             c("https://ik.io/1adc6e14-45fb.jpeg", 3264), c("https://ik.io/3b2a4d76-6b10.jpeg", 3264)]
    assert len(F.gallery_pick(cands, "1420 Stebbins avenue apartments")) == 3


# --- the 1600 px copies the app's full-screen gallery zooms into (2026-11-21)
import os
import tempfile
from unittest import mock


def _gallery(folder, on_disk, meta, fetched):
    """save_gallery over a temp photo folder, with the network and the
    photo-likeness check swapped out. `fetched` collects what was asked for."""
    def fake(src):
        fetched.append(src)
        wide = "small" not in src
        return b"tile", ".jpg", 2000 if wide else 700, (b"large" if wide else None)
    rec = {"image": "/featured/img/lead.jpg", "image_large": "/featured/img/lead_l.jpg",
           "gallery_src": ["https://a.example/one.jpg", "https://a.example/small.jpg"]}
    with mock.patch.object(F, "IMGDIR", folder), mock.patch.object(F, "ahash", lambda path: path), \
         mock.patch.object(F, "same_photo", lambda h, hashes: False), mock.patch.object(F, "fetch_best_image", fake):
        F.save_gallery(rec, on_disk, meta, True)
    return rec


def test_gallery_photos_keep_a_large_copy_listed_beside_them():
    with tempfile.TemporaryDirectory() as folder:
        rec = _gallery(folder, {}, {}, [])
        assert len(rec["images"]) == 3 and len(rec["images_large"]) == 3
        assert rec["images_large"][0] == "/featured/img/lead_l.jpg"
        one = rec["images"][1].rsplit("/", 1)[1].split(".")[0]
        assert rec["images_large"][1] == "/featured/img/" + one + "_l.jpg"
        assert open(os.path.join(folder, one + "_l.jpg"), "rb").read() == b"large"
        assert rec["images_large"][2] is None      # no wider than the tile copy: nothing to add


def test_a_photo_saved_earlier_is_fetched_once_more_for_its_large_copy():
    with tempfile.TemporaryDirectory() as folder:
        on_disk, meta, fetched = {}, {}, []
        _gallery(folder, on_disk, meta, fetched)
        for m in meta.values():                     # as saved before 2026-11-21
            m.pop("lv"); m["large"] = False
        fetched.clear()
        rec = _gallery(folder, on_disk, meta, fetched)
        assert len(fetched) == 2 and rec["images_large"][1]
        fetched.clear()
        _gallery(folder, on_disk, meta, fetched)
        assert fetched == []                        # asked once, not every night


def test_large_copies_survive_the_prune():
    with tempfile.TemporaryDirectory() as folder:
        for f in ("lead.jpg", "lead_l.jpg", "gabc.jpg", "gabc_l.jpg", "gone.jpg", "gone_l.jpg", "meta.json"):
            open(os.path.join(folder, f), "wb").write(b"x")
        rec = {"image": "/featured/img/lead.jpg", "image_large": "/featured/img/lead_l.jpg",
               "images": ["/featured/img/lead.jpg", "/featured/img/gabc.jpg"],
               "images_large": ["/featured/img/lead_l.jpg", "/featured/img/gabc_l.jpg"]}
        with mock.patch.object(F, "IMGDIR", folder):
            assert F.prune_images([rec], True) == 2
        assert sorted(os.listdir(folder)) == ["gabc.jpg", "gabc_l.jpg", "lead.jpg", "lead_l.jpg", "meta.json"]
