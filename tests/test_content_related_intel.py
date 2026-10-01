from __future__ import annotations

import unittest


from api.services import content_service
from runtime.content_runtime import RuntimeContentItem, RuntimeContentProvider


class ContentRelatedIntelTestCase(unittest.TestCase):
    def test_related_content_reads_current_permission_filtered_database_view(self):
        calls = []
        ctx = {
            "get_snapshot_payload": lambda *_args, **_kwargs: self.fail("Public content must recheck current rights and expiry"),
            "get_related_content_by_market_id": lambda market_id, limit=8, days=7: calls.append((market_id, limit, days)) or {"scope": "market", "marketId": market_id, "items": []},
            "table_exists": lambda _name: True,
            "query_one": lambda *_args: {},
        }
        payload = content_service.get_related_content_payload(ctx, 42, limit=20, days=30)
        self.assertEqual([], payload["items"])
        self.assertEqual([(42, 20, 30)], calls)

    def test_topic_ranking_keeps_news_when_other_intel_types_are_plentiful(self):
        provider = RuntimeContentProvider(feeds=[])
        topic = {"id": "sports", "label": "Sports", "keywords": ["nba", "player"], "categories": ["Sports"]}

        scored = []
        for index in range(8):
            scored.append((
                90 - index,
                RuntimeContentItem(
                    id=f"research-{index}",
                    content_type="research",
                    source="arXiv",
                    category="Sports",
                    title=f"NBA player performance research paper {index}",
                    url=f"https://arxiv.org/abs/{index}",
                    published_at=f"2026-06-0{index + 1}T00:00:00Z",
                    summary="nba player model",
                ),
            ))
        for index in range(5):
            scored.append((
                45 - index,
                RuntimeContentItem(
                    id=f"news-{index}",
                    content_type="news",
                    source="ESPN",
                    category="Sports",
                    title=f"NBA player lineup news {index}",
                    url=f"https://example.com/news/{index}",
                    published_at=f"2026-06-0{index + 1}T01:00:00Z",
                    summary="nba player update",
                ),
            ))

        ranked = provider._rank_topic_items_with_type_mix(scored=scored, topic=topic, limit=10)

        self.assertGreaterEqual(sum(1 for item in ranked if item.content_type == "news"), 3)
        self.assertLessEqual(len(ranked), 10)

    def test_generic_study_or_analysis_titles_remain_news(self):
        self.assertEqual(
            "news",
            RuntimeContentProvider._infer_content_type(
                source="ESPN",
                title="NBA player performance study changes matchup odds",
                url="https://example.com/nba-player-performance-study",
            ),
        )
        self.assertEqual(
            "research",
            RuntimeContentProvider._infer_content_type(
                source="arXiv",
                title="Regret minimization with adaptive opponents",
                url="https://arxiv.org/abs/1234.5678",
            ),
        )
