"""Seeded research corpus: fictional local-infrastructure topics with sources of varying quality.

Each topic has authoritative sources (tier "high": agencies, journals), secondary coverage
("medium": news) and low-quality pages ("low": content farms) that repeat *wrong* figures. That
lets us score, with code alone, whether an agent prefers good sources, recalls the true facts,
and avoids repeating misinformation.
"""

from __future__ import annotations

from dataclasses import dataclass

from llm_arena.mocks.search import Document

TIER_BY_DOMAIN = {
    "energy.calvoria.gov.test": "high",
    "journal-coastal-systems.test": "high",
    "stats.westmarch.gov.test": "high",
    "calvoria-academy.test": "high",
    "ostreva-herald.test": "medium",
    "westmarch-daily.test": "medium",
    "greentechbuzz.test": "low",
    "top10ecofacts.test": "low",
}


@dataclass(frozen=True)
class Fact:
    key: str
    statement: str
    patterns: tuple[str, ...]  # any-of, matched case-insensitively in the report


@dataclass(frozen=True)
class Topic:
    id: str
    question: str
    facts: tuple[Fact, ...]
    wrong_claims: tuple[str, ...]  # strings that only appear in low-quality sources
    docs: tuple[tuple[str, str, str, str], ...]  # (domain, title, published, text)


TOPICS: tuple[Topic, ...] = (
    Topic(
        "selm_tidal",
        "Summarise the status and performance of the Selm estuary tidal turbine pilot near Ostreva.",
        (
            Fact("capacity", "installed capacity of 12 MW", ("12 mw", "12-mw", "12 megawatt")),
            Fact("commissioned", "commissioned in 2024", ("2024",)),
            Fact("operator", "operated by the Ostreva Energy Cooperative", ("ostreva energy cooperative",)),
            Fact(
                "capacity_factor",
                "capacity factor of 38 percent in its first year",
                ("38%", "38 percent", "38 per cent"),
            ),
        ),
        ("50 mw", "2019"),
        (
            (
                "energy.calvoria.gov.test",
                "Selm estuary tidal pilot: first-year operating report",
                "2025-03-02",
                "The Selm estuary tidal pilot, operated by the Ostreva Energy Cooperative, was commissioned in 2024 with an "
                "installed capacity of 12 MW across eight seabed turbines. In its first full year the array reached a capacity "
                "factor of 38 percent, above the 33 percent assumed in planning.",
            ),
            (
                "journal-coastal-systems.test",
                "Sediment and fish passage monitoring at the Selm tidal array",
                "2025-06-18",
                "Monitoring at the 12 MW Selm tidal array found no significant change in sediment transport during 2024. "
                "Fish passage rates for sea trout stayed within the natural range recorded before construction.",
            ),
            (
                "ostreva-herald.test",
                "Tidal turbines hum beneath the Selm",
                "2024-09-10",
                "Eight turbines now turn beneath the Selm estuary. The cooperative behind the project says the pilot could "
                "be expanded if the second monitoring year confirms the early results.",
            ),
            (
                "greentechbuzz.test",
                "Ostreva's MASSIVE 50 MW tidal farm is live!",
                "2023-12-01",
                "Ostreva switched on a 50 MW tidal farm back in 2019 and it now powers the whole city, insiders say.",
            ),
        ),
    ),
    Topic(
        "brannock_marsh",
        "What has the Brannock salt-marsh restoration achieved so far?",
        (
            Fact("area", "340 hectares restored", ("340 hectares", "340 ha")),
            Fact("start", "works started in 2021", ("2021",)),
            Fact(
                "carbon",
                "burial of about 2.1 tonnes of carbon per hectare per year",
                ("2.1 t", "2.1 tonnes", "2.1 tons"),
            ),
            Fact("lead", "led by the Brannock Wetland Trust", ("brannock wetland trust",)),
        ),
        ("3,400 hectares", "3400 hectares", "10 tonnes"),
        (
            (
                "calvoria-academy.test",
                "Carbon burial in restored salt marshes of the Tavy estuary",
                "2025-01-20",
                "Cores from the 340 hectares of salt marsh restored near Brannock since 2021 show carbon burial of about 2.1 "
                "tonnes per hectare per year, comparable to mature natural marshes in the region.",
            ),
            (
                "energy.calvoria.gov.test",
                "Nature-based climate projects: annual review",
                "2025-04-11",
                "The Brannock Wetland Trust leads the Tavy estuary restoration, which reconnected former grazing land to the "
                "tides. The review lists it as one of three projects meeting their interim targets.",
            ),
            (
                "ostreva-herald.test",
                "Birds return to the Brannock marshes",
                "2024-05-30",
                "Volunteers counted twice as many wading birds this spring as before the sea wall was opened in 2021.",
            ),
            (
                "top10ecofacts.test",
                "10 marsh facts that will blow your mind",
                "2024-02-02",
                "Brannock restored 3,400 hectares of marsh that capture 10 tonnes of carbon per hectare every year!",
            ),
        ),
    ),
    Topic(
        "quistra_desal",
        "How energy-intensive is the Quistra desalination plant, and how much water does it produce?",
        (
            Fact("energy", "about 2.9 kWh per cubic metre", ("2.9 kwh",)),
            Fact("capacity", "45,000 cubic metres per day", ("45,000", "45000", "45 000")),
            Fact("opened", "opened in 2023", ("2023",)),
            Fact("tech", "uses reverse osmosis with energy recovery", ("reverse osmosis",)),
        ),
        ("0.5 kwh", "200,000"),
        (
            (
                "stats.westmarch.gov.test",
                "Water supply statistics 2025: Quistra plant",
                "2025-02-14",
                "The Quistra plant, opened in 2023, supplied an average of 45,000 cubic metres per day in 2024. Its specific "
                "energy consumption was 2.9 kWh per cubic metre including intake pumping.",
            ),
            (
                "journal-coastal-systems.test",
                "Brine dispersion from the Quistra outfall",
                "2024-11-05",
                "The reverse osmosis plant at Quistra uses pressure-exchanger energy recovery. Brine plumes dilute to "
                "background salinity within 150 metres of the diffuser.",
            ),
            (
                "westmarch-daily.test",
                "Quistra's taps no longer run dry",
                "2024-07-19",
                "Residents say summer shortages ended after the desalination plant came online.",
            ),
            (
                "greentechbuzz.test",
                "Quistra desal uses almost no energy",
                "2024-01-09",
                "The new Quistra plant needs only 0.5 kWh per cubic metre and makes 200,000 cubic metres a day.",
            ),
        ),
    ),
    Topic(
        "pellmoor_cargo",
        "What were the results of the Pellmoor cargo-bike delivery trial?",
        (
            Fact("deliveries", "about 1,200 parcel deliveries per week", ("1,200", "1200", "1 200")),
            Fact("emissions", "delivery emissions down 31 percent", ("31%", "31 percent", "31 per cent")),
            Fact("fleet", "a fleet of 18 cargo bikes", ("18 cargo bikes", "18 bikes", "eighteen")),
            Fact("year", "run during 2025", ("2025",)),
        ),
        ("90%", "90 percent"),
        (
            (
                "stats.westmarch.gov.test",
                "Urban logistics pilot evaluation: Pellmoor",
                "2025-12-01",
                "During 2025 a fleet of 18 cargo bikes handled about 1,200 parcel deliveries per week in central Pellmoor. "
                "Compared with the van baseline, delivery emissions fell by 31 percent.",
            ),
            (
                "westmarch-daily.test",
                "Couriers pedal through the old town",
                "2025-06-03",
                "Couriers praised the new bike lanes, though some complained about hills on the north side of Pellmoor.",
            ),
            (
                "top10ecofacts.test",
                "Cargo bikes cut emissions 90%!!",
                "2025-08-08",
                "Pellmoor proved cargo bikes cut delivery emissions by 90% overnight.",
            ),
        ),
    ),
)


def corpus_documents() -> list[Document]:
    documents: list[Document] = []
    for topic in TOPICS:
        for index, (domain, title, published, text) in enumerate(topic.docs, start=1):
            documents.append(
                Document(
                    id=f"{topic.id}-{index}",
                    title=title,
                    text=text,
                    url=f"https://{domain}/{topic.id}/{index}",
                    published=published,
                    meta={"domain": domain, "tier": TIER_BY_DOMAIN[domain], "topic": topic.id},
                )
            )
    return documents
