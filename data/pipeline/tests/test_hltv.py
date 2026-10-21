import copy
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data.pipeline.__main__ import main
from data.pipeline.core import DEFAULT_ROOT, FetchError, Store, atomic_write, digest, json_bytes, stats_key
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

    def test_adjusted_kast_retains_values_above_100_without_relaxing_ordinary_kast(self):
        body = html_fixture().replace(b'>75%<', b'>104.7%<')
        match, rows = parse_match(body, URL, META)
        self.assertTrue(match["collection_complete"])
        self.assertEqual(match["adapter_version"], 3)
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(r["kast"] == 70 and r["source_metrics"]["eco_kast"] == 104.7 for r in rows))
        with self.assertRaises(ValueError):
            parse_match(body.replace(b'>70%<', b'>170%<'), URL, META)
        for nonfinite in (b'NaN%', b'inf%'):
            with self.subTest(value=nonfinite), self.assertRaises(ValueError):
                parse_match(body.replace(b'>104.7%<', b'>' + nonfinite + b'<'), URL, META)

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

    def test_forfeit_tba_slots_without_result_blocks_remain_unplayed(self):
        soup = soup_html(html_fixture())
        holders = soup.select('.mapholder')
        holders[0].select_one('.mapname').string = 'Default'
        holders[0].select_one('.results-left .results-team-score').string = '0'
        holders[0].select_one('.results-right .results-team-score').string = '1'
        holders[0].select_one('.results-stats').extract()
        for holder in holders[1:]:
            holder.select_one('.mapname').string = 'TBA'
            holder.select_one('.results').extract()
        for content in soup.select('.stats-content'):
            content.extract()
        match, rows = parse_match(str(soup).encode(), URL, META)
        self.assertEqual([m['name'] for m in match['maps']], ['Default', 'TBA', 'TBA'])
        self.assertTrue(all(not m['played'] for m in match['maps']))
        self.assertEqual(match['maps'][0]['awarded_winner'], 'team2')
        self.assertTrue(all(m['team1_rounds'] is None and m['team2_rounds'] is None for m in match['maps']))
        self.assertFalse(match['collection_complete'])
        self.assertEqual(rows, [])
        # A missing participant on a scored map is still a structural failure.
        broken = soup_html(html_fixture())
        broken.select_one('.results-right').extract()
        with self.assertRaisesRegex(ValueError, 'participant block missing'):
            parse_match(str(broken).encode(), URL, META)

    def test_named_optional_maps_on_a_forfeit_remain_unplayed_without_hiding_broken_results(self):
        soup = soup_html(html_fixture())
        holders = soup.select('.mapholder')
        holders[0].select_one('.mapname').string = 'Default'
        holders[0].select_one('.results-left .results-team-score').string = '1'
        holders[0].select_one('.results-right .results-team-score').string = '0'
        holders[0].select_one('.results-stats').extract()
        soup.select_one('.team1-gradient .won').string = '1'
        soup.select_one('.team2-gradient .lost').string = '0'
        for holder, name in zip(holders[1:], ('Dust2', 'Ancient')):
            # Structure observed on hltv:2393546: a named optional slot, no results.
            holder.clear()
            slot = soup_html(f'<div class="optional"><div class="map-name-holder">'
                             f'<div class="mapname">{name}</div></div></div>')
            holder.append(slot.div)
        for content in soup.select('.stats-content'):
            content.extract()
        match, rows = parse_match(str(soup).encode(), URL, META)
        self.assertEqual([m['name'] for m in match['maps']], ['Default', 'Dust2', 'Ancient'])
        self.assertEqual(match['series_score'], {'team1': 1, 'team2': 0})
        self.assertTrue(all(not m['played'] for m in match['maps']))
        self.assertTrue(all(m['team1_rounds'] is None and m['team2_rounds'] is None for m in match['maps']))
        self.assertFalse(match['collection_complete'])
        self.assertEqual(match['stats_missing'], ['All maps', 'played_maps'])
        self.assertEqual(rows, [])
        # Optional markup cannot excuse an incomplete scored result block.
        broken = soup_html(str(soup))
        broken.select('.mapholder')[1].append(soup_html(
            '<div class="results played"><div class="results-left">'
            '<div class="results-teamname">A</div><div class="results-team-score">13</div>'
            '</div></div>').div)
        with self.assertRaisesRegex(ValueError, 'participant block missing'):
            parse_match(str(broken).encode(), URL, META)
        # A named slot without either results or an explicit optional marker is ambiguous.
        soup.select('.mapholder')[1].select_one('.optional').unwrap()
        with self.assertRaisesRegex(ValueError, 'participant block missing'):
            parse_match(str(soup).encode(), URL, META)

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

    def test_opt_in_cli_replacement_archives_legacy_and_retains_archive_on_refresh(self):
        legacy, rows = parse_match(html_fixture(), URL, META)
        legacy.update(source="legacy_hltv", series_score={"team1": 1, "team2": 2})
        player = {**rows[0], "source": "legacy_hltv", "player_id": None, "player_nick": "unresolved"}
        player_key = stats_key(player)
        with Store(self.root) as store:
            store.put("matches", "hltv:123", legacy["date"], legacy)
            store.put("player_stats", player_key, legacy["date"], player)
        body = html_fixture()
        folder = self.root / "raw/http" / digest(URL.encode())
        atomic_write(folder / (digest(body) + ".body"), body)
        atomic_write(folder / "latest.json", json_bytes({**META, "sha256": digest(body),
                                                        "body_file": digest(body) + ".body"}))
        args = ["--data-dir", str(self.root), "--offline", "sync-hltv", "--since", "2026-10-18",
                "--until", "2026-10-18", "--match-url", URL]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
            report = json.loads((self.root / "reports/latest.json").read_text())
            self.assertEqual(report["result"]["existing_import_retained"], 1)
            # Resume must reuse a verified cache even for IDs still owned by the legacy import.
            online = [arg for arg in args if arg != "--offline"]
            with patch.object(HltvBrowser, "_start", side_effect=AssertionError("cached upgrade must not start Chrome")):
                self.assertEqual(main(online + ["--replace-legacy"]), 0)
        report = json.loads((self.root / "reports/latest.json").read_text())
        self.assertEqual(report["result"]["legacy_replaced"], 1)
        with Store(self.root) as store:
            current = store.get("matches", "hltv:123")
            self.assertEqual(current["source"], "hltv")
            self.assertEqual(current["series_score"], {"team1": 2, "team2": 1})
            self.assertEqual(store.summary()["player_stats"]["count"], 40)
            self.assertIsNone(store.get("player_stats", player_key))
            archive = current["legacy_archive"]
            archived = (self.root / archive["path"]).read_bytes()
            self.assertEqual(digest(archived), archive["sha256"])
            self.assertEqual(json.loads(archived)["match"], legacy)
            self.assertEqual(json.loads(archived)["player_stats"], [player])
            repeat = sync_matches(store, FakeHltv(), legacy["date"], legacy["date"],
                                  urls=[URL], replace_legacy=True)
            self.assertEqual((repeat["already_complete"], repeat["legacy_replaced"]), (1, 0))
            collect_match(store, FakeHltv(), URL, refresh=True)
            self.assertEqual(store.get("matches", "hltv:123")["legacy_archive"], archive)

    def test_legacy_replacement_keeps_old_statistics_on_incomplete_parse_or_save_failure(self):
        legacy = {"source": "legacy_hltv", "match_id": "hltv:123", "date": "2026-10-18"}
        player = {"match_id": "hltv:123", "source": "legacy_hltv", "player_nick": "unresolved"}
        with Store(self.root) as store:
            store.put("matches", "hltv:123", legacy["date"], legacy)
            store.put("player_stats", "nickname-only", legacy["date"], player)
            store.db.commit()
            bad = html_fixture().replace(b'kast traditional-data', b'changed-kast traditional-data')
            with self.assertRaisesRegex(ValueError, "previous legacy statistics retained"):
                collect_match(store, FakeHltv(bad), URL, replace_legacy=True)
            self.assertEqual(store.get("matches", "hltv:123"), legacy)
            self.assertEqual(store.get("player_stats", "nickname-only"), player)
            original_put = store.put
            def fail_player(kind, *args):
                if kind == "player_stats":
                    raise ValueError("injected save failure")
                return original_put(kind, *args)
            with patch.object(store, "put", side_effect=fail_player), self.assertRaises(ValueError):
                collect_match(store, FakeHltv(), URL, replace_legacy=True)
            self.assertEqual(store.get("matches", "hltv:123"), legacy)
            self.assertEqual(store.get("player_stats", "nickname-only"), player)
            self.assertEqual(store.summary()["player_stats"]["count"], 1)

    def test_next_day_result_timestamp_does_not_exclude_an_in_window_start(self):
        next_day = int(datetime(2026, 10, 19, 1, tzinfo=timezone.utc).timestamp() * 1000)
        results = result_fixture().replace(b'1792328400000', str(next_day).encode())
        http = FakeHltv()
        get = http.get
        def late_result(url, **kwargs):
            return (results, META) if "/results?" in url else get(url, **kwargs)
        with Store(self.root) as store, patch.object(http, "get", side_effect=late_result):
            report = sync_matches(store, http, "2026-10-18", "2026-10-18")
            self.assertEqual(report["collected"], 1)
            self.assertTrue(report["window_complete"])
            self.assertEqual(store.get("matches", "hltv:123")["date"], "2026-10-18")

    def test_partial_legacy_exception_is_id_scoped_and_archives_all_old_statistics(self):
        urls = [URL, URL.replace('/123/', '/124/')]
        with Store(self.root) as store:
            for url in urls:
                match, rows = parse_match(html_fixture(), url, {**META, 'url': url})
                match.update(source='legacy_hltv', collection_complete=False)
                store.put('matches', match['match_id'], match['date'], match)
                for row in rows:
                    row.update(source='legacy_hltv', rating_version='unknown')
                    store.put('player_stats', stats_key(row), row['date'], row)
            store.db.commit()
            soup = soup_html(html_fixture())
            soup.find('div', id='1-content').extract()
            partial = FakeHltv(str(soup).encode())
            result = sync_matches(store, partial, '2026-10-18', '2026-10-18', urls=urls,
                                  replace_legacy=True, allow_partial_legacy=['hltv:123'])
            self.assertEqual((result['legacy_replaced'], result['partial_legacy_replaced']), (1, 1))
            self.assertEqual(len(result['errors']), 1)
            self.assertEqual(result['errors'][0]['url'], urls[1])
            current = store.get('matches', 'hltv:123')
            self.assertEqual(current['stats_missing'], ['Nuke'])
            self.assertFalse(current['collection_complete'])
            archive = current['legacy_archive']
            self.assertTrue(archive['replacement_incomplete'])
            archived = (self.root / archive['path']).read_bytes()
            self.assertEqual(digest(archived), archive['sha256'])
            self.assertEqual(len(json.loads(archived)['player_stats']), 40)
            self.assertEqual(store.get('matches', 'hltv:124')['source'], 'legacy_hltv')
            self.assertEqual(store.summary()['player_stats']['count'], 70)
            # The exception cannot downgrade a complete direct-source record.
            collect_match(store, FakeHltv(), urls[0], refresh=True)
            with self.assertRaisesRegex(ValueError, 'previous complete data retained'):
                collect_match(store, partial, urls[0], refresh=True, replace_legacy=True,
                              allow_partial_legacy=True)

    def test_pause_preserves_current_match_and_resume_skips_it(self):
        stop_file = self.root / "pause.request"
        http = FakeHltv()
        get = http.get
        def request_pause(url, **kwargs):
            response = get(url, **kwargs)
            if "/matches/" in url:
                stop_file.touch()
            return response

        with Store(self.root) as store, patch.object(http, "get", side_effect=request_pause) as fetch:
            stopped = sync_matches(store, http, "2026-10-18", "2026-10-20",
                                   stop_requested=stop_file.exists)
            self.assertEqual(stopped["stop_reason"], "stop_requested")
            self.assertFalse(stopped["window_complete"])
            self.assertEqual(stopped["collected"], 1)
            self.assertEqual(store.summary()["player_stats"]["count"], 40)
            self.assertIsNone(store.get("matches", "hltv:124"))
            fetch.reset_mock()
            sync_matches(store, http, "2026-10-18", "2026-10-20", stop_requested=stop_file.exists)
            fetch.assert_not_called()  # An existing pause request also prevents list discovery.
            stop_file.unlink()
            resumed = sync_matches(store, FakeHltv(), "2026-10-18", "2026-10-20",
                                   stop_requested=stop_file.exists)
            self.assertTrue(resumed["window_complete"])
            self.assertEqual(resumed["already_complete"], 1)
            self.assertEqual(store.summary()["player_stats"]["count"], 80)

    def test_url_file_and_pause_reports_with_cached_data(self):
        manifest = self.root / "matches.txt"
        manifest.write_text("", encoding="utf-8")
        args = ["--data-dir", str(self.root), "--offline", "sync-hltv", "--since", "2026-10-18",
                "--until", "2026-10-20", "--match-urls-file", str(manifest)]
        def run(extra=()):
            with redirect_stdout(io.StringIO()):
                code = main(args + list(extra))
            return code, json.loads((self.root / "reports/latest.json").read_text(encoding="utf-8"))
        code, report = run()
        self.assertEqual(code, 1)
        self.assertIn("manifest is empty", report["error"])
        self.assertFalse(report["browser_lifecycle"]["started"])
        body = html_fixture()
        folder = self.root / "raw/http" / digest(URL.encode())
        atomic_write(folder / (digest(body) + ".body"), body)
        atomic_write(folder / "latest.json", json_bytes({**META, "sha256": digest(body),
                                                        "body_file": digest(body) + ".body"}))
        manifest.write_text(URL + "\n", encoding="utf-8-sig")
        code, report = run()
        self.assertEqual((code, report["status"]), (0, "ok"))
        self.assertEqual(report["match_urls_file"]["sha256"], digest(manifest.read_bytes()))
        self.assertTrue(report["result"]["requested_urls_complete"])
        self.assertFalse(report["result"]["window_complete"])
        stop_file = self.root / "pause.request"
        stop_file.touch()
        code, report = run(["--stop-file", str(stop_file)])
        self.assertEqual((code, report["status"]), (0, "paused"))
        self.assertFalse(report["browser_lifecycle"]["started"])

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
