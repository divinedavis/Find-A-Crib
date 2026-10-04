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
