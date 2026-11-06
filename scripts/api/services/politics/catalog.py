"""Public sources and explicit coverage. Credentials are optional extensions."""
from dataclasses import dataclass
from datetime import datetime, timezone
from . import normalizers as n


@dataclass(frozen=True)
class SourceSpec:
    key: str
    owner: str
    url: str
    cadence: int
    parse: object


def catalog():
    year = datetime.now(timezone.utc).year
    cycle = year + year % 2
    congress = (year - 1789) // 2 + 1
    # Election-specific files are pinned scopes, not automatically relabelled each January.
    nc = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/"
    return [
        SourceSpec("decision-labs", "elections", "https://www.decisionlabs.ai/api/export/polls", 3600, n.polls),
        SourceSpec("nc-early-20261103", "elections", nc + "2026_11_03/absentee_spoiled_outstanding_20261103.zip", 3600, n.early_vote),
        SourceSpec("nc-results-20261103", "elections", nc + "2026_11_03/results_pct_20261103.zip", 3600, n.nc_results),
        SourceSpec("nc-primary-20260303", "elections", nc + "2026_03_03/results_pct_20260303.zip", 86400, n.nc_results),
        SourceSpec(f"fec-{cycle}", "campaign-finance", f"https://www.fec.gov/files/bulk-downloads/{cycle}/weball{str(cycle)[-2:]}.zip", 21600, n.finance),
        SourceSpec("house-roster", "government", "https://clerk.house.gov/xml/lists/MemberData.xml", 1800, n.house),
        SourceSpec(f"bills-{congress}", "government", "https://www.govinfo.gov/rss/bills.xml", 1800, lambda body: n.bill_feed(body, congress)),
        SourceSpec("presidential-nominations", "government", "https://www.whitehouse.gov/presidential-actions/feed/?s=nominations", 1800, n.announcements),
        SourceSpec("funding-law-119-103", "government", "https://www.govinfo.gov/content/pkg/PLAW-119publ103/html/PLAW-119publ103.htm", 86400, n.funding_law),
    ]
