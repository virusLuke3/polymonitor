"""Public sources and explicit coverage. Credentials are optional extensions."""

from data_sources import source_value
from dataclasses import dataclass
from datetime import datetime, timezone
from . import normalizers as n
from . import evidence as e


@dataclass(frozen=True)
class SourceSpec:
    key: str
    owner: str
    url: str
    cadence: int
    parse: object
    max_bytes: int = 8 * 1024**2


def catalog():
    year = datetime.now(timezone.utc).year
    cycle = year + year % 2
    congress = (year - 1789) // 2 + 1
    # Election-specific files are pinned scopes, not automatically relabelled each January.
    nc = source_value('POLYMONITOR_URL_S3_AMAZONAWS_COM_DL_NCSBE_GOV_ENRS_53AADF')
    return [
        SourceSpec("decision-labs", "elections", source_value('POLYMONITOR_URL_WWW_DECISIONLABS_AI_API_EXPORT_POLLS_13507C'), 3600, n.polls),
        SourceSpec("nc-early-20261103", "elections", nc + "2026_11_03/absentee_spoiled_outstanding_20261103.zip", 3600, n.early_vote),
        SourceSpec("nc-results-20261103", "elections", nc + "2026_11_03/results_pct_20261103.zip", 3600, n.nc_results),
        SourceSpec("nc-primary-20260303", "elections", nc + "2026_03_03/results_pct_20260303.zip", 86400, n.nc_results),
        SourceSpec("nc-certification-20261103", "elections", source_value("POLYMONITOR_POLITICS_NC_CERTIFICATION_URL"), 3600, e.nc_certification),
        SourceSpec("dnc-roll-call-2024", "elections", source_value("POLYMONITOR_POLITICS_DNC_ROLL_CALL_URL"), 86400, e.dnc_roll_call),
        SourceSpec(f"fec-{cycle}", "campaign-finance", f"{source_value('POLYMONITOR_URL_WWW_FEC_GOV_FILES_BULK_DOWNLOADS_AB50B3')}{cycle}/weball{str(cycle)[-2:]}.zip", 21600, n.finance),
        SourceSpec(f"fec-independent-{cycle}", "campaign-finance", source_value("POLYMONITOR_POLITICS_FEC_IE_URL_TEMPLATE").replace("{cycle}", str(cycle)), 21600, e.independent_expenditures, 32 * 1024**2),
        SourceSpec("house-roster", "government", source_value('POLYMONITOR_URL_CLERK_HOUSE_GOV_XML_LISTS_MEMBERDATA_XML_99EDD0'), 1800, n.house),
        SourceSpec(f"bills-{congress}", "government", source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_RSS_BILLS_XML_F459D1'), 1800, lambda body: n.bill_feed(body, congress)),
        SourceSpec("presidential-nominations", "government", source_value('POLYMONITOR_URL_WWW_WHITEHOUSE_GOV_PRESIDENTIAL_ACTIONS_FEED_7F2194'), 1800, n.announcements),
        SourceSpec("judicial-confirmations", "government", source_value("POLYMONITOR_POLITICS_JUDICIAL_CONFIRMATIONS_URL"), 1800, e.judicial_confirmations),
        SourceSpec("nomination-hearings", "government", source_value("POLYMONITOR_POLITICS_HEARINGS_FEED_URL"), 3600, e.hearings_feed),
        SourceSpec("funding-law-119-103", "government", source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_CONTENT_PKG_PLAW_119PUBL103_HTML_PLAW_119PUBL103_HTM_9E9799'), 86400, n.funding_law),
    ]
