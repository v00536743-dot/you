from shortskit.config import H
from shortskit.engine import layout as L


def test_center_at_least_55_percent_in_every_mode():
    for mode in L.MODES:
        lay = L.compute({"mode": mode}, ["youtube_shorts"])
        assert lay.center_pct >= 55, mode
        assert lay.center.y % 8 == 0 and lay.center.h % 8 == 0


def test_panel_sizes_and_removal():
    lay = L.compute({"mode": "three", "top": {"height_pct": 20}, "bottom": {"height_pct": 16}}, ["youtube_shorts"])
    assert lay.top.h == 384 and lay.bottom.h == 304 and lay.center.h == H - 384 - 304
    assert L.compute({"mode": "center_only"}, ["youtube_shorts"]).top is None
    assert L.compute({"mode": "top_center"}, ["youtube_shorts"]).bottom is None
    assert L.compute({"mode": "center_bottom"}, ["youtube_shorts"]).top is None


def test_safe_zone_youtube_numbers():
    z = L.safe_zone(["youtube_shorts"]).rect
    assert (z.x, z.y, z.x1, z.y1) == (48, 288, 1080 - 192, 1920 - 672)


def test_safe_zone_intersection_and_tiktok_column():
    z = L.safe_zone(["youtube_shorts", "tiktok", "reels"])
    assert z.rect.x == 120 and z.rect.y == 288 and z.rect.y1 == 1920 - 672
    assert z.exclusions  # tiktok action column
    lay = L.compute({"mode": "three"}, ["youtube_shorts", "tiktok"])
    # caption band is clipped left of the TikTok action column and stays inside the zone
    assert lay.caption_band.x1 <= 780
    assert z.allows(lay.caption_band)
    assert z.allows(lay.cta_box)


def test_caption_band_is_lower_third_of_safe_zone():
    lay = L.compute({"mode": "three"}, ["youtube_shorts"])
    s = lay.safe.rect
    assert lay.caption_band.y >= s.y + s.h * 0.6
    assert lay.caption_band.y1 <= 1920 - 672  # never in the bottom 672 px
