"""A small, hand-authored fictional world rendered as encyclopedia articles.

Fictional entities keep multi-hop questions contamination-free: no model can answer them from
pre-training, so correct answers require using the tools. Questions are generated from the
relations below, so gold answers are exact.
"""

from __future__ import annotations

from dataclasses import dataclass

from llm_arena.core.task import Task


@dataclass(frozen=True)
class Country:
    name: str
    capital: str
    currency: str


@dataclass(frozen=True)
class City:
    name: str
    country: str
    founded: int
    river: str | None
    population: int


@dataclass(frozen=True)
class Person:
    name: str
    born: int
    birth_city: str
    occupation: str
    mentor: str | None = None


@dataclass(frozen=True)
class Company:
    name: str
    founded: int
    founder: str
    headquarters: str
    product: str


@dataclass(frozen=True)
class Invention:
    name: str
    year: int
    inventor: str
    purpose: str


COUNTRIES = [
    Country("Calvoria", "Ostreva", "calvorian mark"),
    Country("Westmarch", "Pellmoor", "westmarch crown"),
    Country("Norrisk", "Varrel", "norrisk thaler"),
]
CITIES = [
    City("Ostreva", "Calvoria", 1204, "Selm", 412_000),
    City("Brannock", "Calvoria", 1350, "Tavy", 96_000),
    City("Durnhollow", "Calvoria", 1621, "Ember", 150_000),
    City("Pellmoor", "Westmarch", 1512, "Selm", 233_000),
    City("Quistra", "Westmarch", 1188, None, 61_000),
    City("Varrel", "Norrisk", 1402, "Oskel", 288_000),
    City("Hemsby Cross", "Norrisk", 1733, "Oskel", 34_000),
]
PEOPLE = [
    Person("Ilse Varga", 1871, "Brannock", "engineer"),
    Person("Tomas Arkwright", 1894, "Quistra", "chemist", mentor="Ilse Varga"),
    Person("Mirela Osk", 1902, "Varrel", "physicist", mentor="Ilse Varga"),
    Person("Benedikt Salo", 1915, "Durnhollow", "industrialist", mentor="Tomas Arkwright"),
    Person("Agathe Renn", 1920, "Hemsby Cross", "cartographer", mentor="Mirela Osk"),
    Person("Caspar Lindqvist", 1933, "Pellmoor", "architect", mentor="Agathe Renn"),
    Person("Noor Havel", 1948, "Ostreva", "entrepreneur", mentor="Benedikt Salo"),
]
COMPANIES = [
    Company("Selmworks", 1921, "Benedikt Salo", "Durnhollow", "river turbines"),
    Company("Kestrel Optics", 1956, "Mirela Osk", "Varrel", "survey lenses"),
    Company("Havel & Daughters", 1979, "Noor Havel", "Pellmoor", "prefabricated housing"),
    Company("Arkwright Dyes", 1925, "Tomas Arkwright", "Brannock", "mineral pigments"),
]
INVENTIONS = [
    Invention("Varga governor", 1899, "Ilse Varga", "regulating steam engine speed"),
    Invention("Osk interferometer", 1931, "Mirela Osk", "measuring lens curvature"),
    Invention("Renn projection", 1952, "Agathe Renn", "mapping coastlines with less distortion"),
    Invention("Lindqvist truss", 1964, "Caspar Lindqvist", "spanning halls without columns"),
]


COUNTRY = {country.name: country for country in COUNTRIES}
CITY = {city.name: city for city in CITIES}
PERSON = {person.name: person for person in PEOPLE}


def articles() -> dict[str, str]:
    """Title → article text. Each fact lives in exactly one article, forcing multi-hop lookups."""
    docs: dict[str, str] = {}
    for country in COUNTRIES:
        docs[country.name] = (
            f"{country.name} is a country whose capital is {country.capital}. Its currency is the {country.currency}."
        )
    for city in CITIES:
        river = (
            f"The river {city.river} flows through the city."
            if city.river
            else "The city lies on the coast and has no river."
        )
        docs[city.name] = (
            f"{city.name} is a city in {city.country}, founded in {city.founded}. {river} "
            f"It has a population of about {city.population:,}."
        )
    for person in PEOPLE:
        mentor = f" {person.name.split()[0]} trained under {person.mentor}." if person.mentor else ""
        docs[person.name] = (
            f"{person.name} (born {person.born} in {person.birth_city}) was a {person.occupation}.{mentor}"
        )
    for company in COMPANIES:
        docs[company.name] = (
            f"{company.name} is a manufacturer of {company.product}, founded in {company.founded} by {company.founder}. "
            f"Its headquarters are in {company.headquarters}."
        )
    for invention in INVENTIONS:
        docs[invention.name] = (
            f"The {invention.name} is a device for {invention.purpose}. It was introduced in {invention.year} by {invention.inventor}."
        )
    return docs


def multihop_tasks() -> list[Task]:
    tasks: list[Task] = []
    for company in COMPANIES:
        founder = PERSON[company.founder]
        tasks.append(
            _task(
                f"founder_country_{company.name}",
                f"In which country was the founder of {company.name} born?",
                CITY[founder.birth_city].country,
                hops=3,
            )
        )
        river = CITY[company.headquarters].river or "none"
        tasks.append(
            _task(
                f"hq_river_{company.name}",
                f"Which river flows through the city where {company.name} has its headquarters?",
                river,
                hops=2,
            )
        )
    for invention in INVENTIONS:
        mentor = PERSON[invention.inventor].mentor
        if mentor:
            tasks.append(
                _task(
                    f"inventor_mentor_{invention.name}",
                    f"Who mentored the inventor of the {invention.name}?",
                    mentor,
                    hops=2,
                )
            )
    for person in PEOPLE[3:]:
        capital = COUNTRY[CITY[person.birth_city].country].capital
        tasks.append(
            _task(
                f"capital_pop_{person.name}",
                f"What is the population of the capital of the country where {person.name} was born?",
                f"{CITY[capital].population:,}",
                hops=4,
                numeric=CITY[capital].population,
            )
        )
    tasks.append(
        _task(
            "age_gap",
            "How many years after Ostreva was founded was the founder of Havel & Daughters born?",
            str(PERSON["Noor Havel"].born - CITY["Ostreva"].founded),
            hops=3,
            numeric=PERSON["Noor Havel"].born - CITY["Ostreva"].founded,
        )
    )
    return tasks


def _task(task_id: str, question: str, answer: str, *, hops: int, numeric: int | None = None) -> Task:
    data: dict[str, object] = {"answer": answer, "hops": hops}
    if numeric is not None:
        data["numeric"] = numeric
    return Task(
        id=task_id.lower().replace(" ", "_").replace("&", "and"), prompt=question, data=data, tags=[f"hops:{hops}"]
    )
