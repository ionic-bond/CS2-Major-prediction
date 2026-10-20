import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data.pipeline.core import DEFAULT_ROOT, FetchError, Store, atomic_write, digest, json_bytes
from data.pipeline.hltv import collect_match, match_url, parse_match, parse_results, soup_html, sync_matches
from data.pipeline.hltv_browser import HltvBrowser


URL = "https://www.hltv.org/matches/123/a-vs-b-test"
META = {"url": URL, "fetched_at": "2026-10-20T00:00:00+00:00", "sha256": "fixture",
        "transport": "chrome_cdp", "representation": "http_response_body"}


def html_fixture():
    stamp = int(datetime(2026, 10, 18, 12, tzinfo=timezone.utc).timestamp() * 1000)
    maps = []
    for index, (name, a, b) in enumerate((("Nuke", 13, 11), ("Cache", 4, 13), ("Anubis", 13, 10)), 1):
        maps.append(f'<div class="mapholder"><div class="mapname">{name}</div><div class="results played">'
                    f'<div class="results-left"><div class="results-teamname">A</div><div class="results-team-score">{a}</div></div>'
                    f'<div class="results-right"><div class="results-teamname">B</div><div class="results-team-score">{b}</div></div>'
                    f'<a class="results-stats" href="/stats/matches/mapstatsid/{index}/a-vs-b">STATS</a></div></div>')
    groups = []
    for group in ("all", "1", "2", "3"):
        tables = []
        for tid, name in ((202, "B"), (101, "A")):
            players = []
            for index in range(5):
                pid = tid * 10 + index
                players.append(f'<tr><td class="players"><a href="/player/{pid}/p{pid}">'
                               f'<span class="player-nick">p{pid}</span><div class="smartphone-only">p{pid}</div></a></td>'
                               '<td class="kd traditional-data">20-12</td><td class="kd eco-adjusted-data hidden">22-10</td>'
                               '<td class="adr traditional-data">80</td><td class="adr eco-adjusted-data hidden">85</td>'
                               '<td class="kast traditional-data">70%</td><td class="kast eco-adjusted-data hidden">75%</td>'
                               '<td class="roundSwing">+1.50%</td><td class="rating">1.25</td></tr>')
            tables.append(f'<table class="table totalstats"><tr class="header-row"><td><a class="teamName" href="/team/{tid}/{name}">{name}</a>'
                          '<span class="ratingDesc">3.0</span></td></tr>' + "".join(players) + "</table>")
        groups.append(f'<div class="stats-content" id="{group}-content">' + "".join(tables) + "</div>")
    return ('<html><head><title>A vs B | HLTV.org</title></head><body><div class="match-page">'
            f'<div class="timeAndEvent"><div data-unix="{stamp}">Wrong localized display date</div>'
            '<div class="event"><a href="/events/7/test">Test</a></div><div class="countdown">Match over</div></div>'
            '<div class="team1-gradient"><a href="/team/101/a"><div class="teamName">A</div></a><div class="won">2</div></div>'
            '<div class="team2-gradient"><a href="/team/202/b"><div class="teamName">B</div></a><div class="lost">1</div></div>'
            '<div class="veto-box">Best of 3 (Online)</div><div class="veto-box">1. A removed Inferno</div>'
            + "".join(maps) + "".join(groups) + "</div></body></html>").encode()


def result_fixture(ids=(123,)):
    return ('<div class="results-all">' + "".join(
        f'<div class="result-con" data-zonedgrouping-entry-unix="1792328400000"><a class="a-reset" '
        f'href="/matches/{mid}/a-vs-b-test"></a><div class="map-text">bo3</div></div>' for mid in ids) + '</div>').encode()


class FakeHltv:
    def __init__(self, body=None):
        self.body = body or html_fixture()

    def get(self, url, **kwargs):
        if "/results?" in url:
            return result_fixture((123, 124)), {**META, "url": url}
        return self.body, {**META, "url": url}


class HltvTests(unittest.TestCase):
    def setUp(self):
        parent = DEFAULT_ROOT / "processed" / "test-temp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_realistic_scoreboards_keep_identity_scope_and_metric_semantics(self):
        match, rows = parse_match(html_fixture(), URL, META)
        self.assertEqual(match["series_score"], {"team1": 2, "team2": 1})
        self.assertEqual(sum(m["team1_rounds"] for m in match["maps"]), 30)
        self.assertEqual(sum(m["team2_rounds"] for m in match["maps"]), 34)
        self.assertEqual(match["winner"], "team1")
        self.assertEqual(match["played_at_utc"], "2026-10-18T12:00:00+00:00")
        self.assertIsNone(match["completed_at_utc"])
        self.assertTrue(match["collection_complete"])
        self.assertEqual(len(rows), 40)
        self.assertEqual(sum(r["scope"] == "series" for r in rows), 10)
        self.assertEqual(rows[0]["team"], "team2")  # Tables need not follow series team order.
        self.assertEqual(rows[0]["player_id"], "hltv:2020")
        self.assertEqual(rows[0]["player_nick"], "p2020")
        self.assertEqual((rows[0]["kills"], rows[0]["deaths"], rows[0]["adr"], rows[0]["kast"]), (20, 12, 80, 70))
        self.assertEqual(rows[0]["source_metrics"]["eco_adr"], 85)
        self.assertEqual(rows[0]["source_metrics"]["round_swing_pct"], 1.5)
        self.assertEqual(rows[0]["rating_version"], "3.0")
        self.assertNotIn("bo3_rating", rows[0])

    def test_unknown_fields_are_missing_and_do_not_become_zero(self):
        body = html_fixture().replace(b'kast traditional-data', b'changed-kast traditional-data')
        match, rows = parse_match(body, URL, META)
        self.assertFalse(match["collection_complete"])
        self.assertIsNone(rows[0]["kast"])
        self.assertEqual(len(match["stats_missing"]), 4)
        with self.assertRaises(ValueError):
            parse_match(html_fixture().replace(b'70%', b'170%'), URL, META)

    def test_default_map_awards_are_not_played_rounds_or_missing_statistics(self):
        soup = soup_html(html_fixture())
        for holder, a, b in zip(soup.select('.mapholder'), (0, 1), (1, 0)):
            holder.select_one('.mapname').string = 'Default'
            holder.select_one('.results-left .results-team-score').string = str(a)
            holder.select_one('.results-right .results-team-score').string = str(b)
            holder.select_one('.results-stats').extract()
        match, rows = parse_match(str(soup).encode(), URL, META)
        self.assertEqual(match["series_score"], {"team1": 2, "team2": 1})
        self.assertEqual(len(rows), 20)  # Series plus the one actual map.
        self.assertTrue(match["collection_complete"])
        self.assertEqual(match["stats_missing"], [])
        self.assertIn("default_maps_present", match["issues"])
        self.assertFalse(match["maps"][0]["played"])
        self.assertIsNone(match["maps"][0]["team1_rounds"])
        self.assertEqual(match["maps"][0]["awarded_winner"], "team2")
        self.assertEqual(match["maps"][0]["source_default_score"], {"team1": 0, "team2": 1})

    def test_rating_version_is_read_and_duplicate_players_are_rejected(self):
        _, rows = parse_match(html_fixture().replace(b'>3.0<', b'>2.1<'), URL, META)
        self.assertTrue(all(r["rating_version"] == "2.1" for r in rows))
        with self.assertRaises(ValueError):
            parse_match(html_fixture().replace(b'/player/2021/', b'/player/2020/'), URL, META)

    def test_challenges_unfinished_pages_and_foreign_urls_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_results(b'<title>Just a moment...</title>')
        with self.assertRaises(ValueError):
            parse_match(html_fixture().replace(b'Match over', b'LIVE'), URL, META)
        with self.assertRaises(ValueError):
            match_url('https://example.com/matches/123/a')
        rows = parse_results(result_fixture((123, 123)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], URL)

    def test_refresh_replaces_atomically_without_dropping_good_data(self):
        with Store(self.root) as store:
            collect_match(store, FakeHltv(), URL)
            collect_match(store, FakeHltv(), URL, refresh=True)
            self.assertEqual(store.summary()["player_stats"]["count"], 40)
            before = copy.deepcopy(store.get("matches", "hltv:123"))
            bad = html_fixture().replace(b'kast traditional-data', b'changed-kast traditional-data')
            with self.assertRaises(ValueError):
                collect_match(store, FakeHltv(bad), URL, refresh=True)
            self.assertEqual(store.get("matches", "hltv:123"), before)
            self.assertEqual(store.summary()["player_stats"]["count"], 40)
            original_put = store.put
            def fail_player(kind, *args):
                if kind == "player_stats":
                    raise ValueError("injected save failure")
                return original_put(kind, *args)
            with patch.object(store, "put", side_effect=fail_player), self.assertRaises(ValueError):
                collect_match(store, FakeHltv(), URL, refresh=True)
            self.assertEqual(store.get("matches", "hltv:123"), before)
            self.assertEqual(store.summary()["player_stats"]["count"], 40)

    def test_date_window_and_existing_import_are_preserved(self):
        with Store(self.root) as store:
            _, saved = collect_match(store, FakeHltv(), URL, since="2026-10-19", until="2026-10-20")
            self.assertFalse(saved)
            self.assertEqual(store.summary(), {})
            legacy = {"source": "legacy_hltv", "match_id": "hltv:123", "date": "2026-10-18"}
            store.put("matches", "hltv:123", "2026-10-18", legacy)
            store.db.commit()
            with self.assertRaises(ValueError):
                collect_match(store, FakeHltv(), URL, refresh=True)
            self.assertEqual(store.get("matches", "hltv:123"), legacy)

    def test_bounded_repeated_sync_eventually_scans_all_candidates(self):
        with Store(self.root) as store:
            first = sync_matches(store, FakeHltv(), "2026-10-18", "2026-10-20", max_matches=1)
            self.assertEqual(first["stop_reason"], "max_matches")
            self.assertFalse(first["window_complete"])
            second = sync_matches(store, FakeHltv(), "2026-10-18", "2026-10-20", max_matches=1)
            self.assertEqual(second["already_complete"], 1)
            self.assertTrue(second["window_complete"])
            self.assertEqual(store.summary()["player_stats"]["count"], 80)
            explicit = sync_matches(store, FakeHltv(), "2026-10-18", "2026-10-20", urls=[URL])
            self.assertTrue(explicit["requested_urls_complete"])
            self.assertFalse(explicit["window_complete"])

    def test_offline_browser_replays_cache_without_starting_chrome(self):
        body = html_fixture()
        folder = self.root / "raw" / "http" / digest(URL.encode())
        metadata = {**META, "sha256": digest(body), "body_file": digest(body) + ".body"}
        atomic_write(folder / metadata["body_file"], body)
        atomic_write(folder / "latest.json", json_bytes(metadata))
        with HltvBrowser(self.root, offline=True) as http, patch.object(http, "_start", side_effect=AssertionError("browser must not start")):
            self.assertEqual(http.get(URL, refresh=True)[0], body)
            self.assertFalse(http.lifecycle["started"])
            with self.assertRaises(FetchError):
                http.get(URL.replace("/123/", "/124/"))

    def test_loaded_statistics_do_not_wait_for_unrelated_page_resources(self):
        state = {"url": URL, "title": "A vs B | HLTV.org", "ready": "interactive", "valid": True,
                 "html": html_fixture().decode()}
        def protocol(method, params):
            return {"result": {"value": json.dumps(state)}} if method == "Runtime.evaluate" else {}
        with HltvBrowser(self.root, interval=0) as http, patch.object(http, "_start"), patch.object(http, "_call", side_effect=protocol), patch("data.pipeline.hltv_browser.time.sleep"):
            body, metadata = http.get(URL)
            self.assertEqual(metadata["representation"], "rendered_dom")
            self.assertEqual(len(parse_match(body, URL, metadata)[1]), 40)


if __name__ == "__main__":
    unittest.main()
