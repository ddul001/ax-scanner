"""Does a page chosen for a role (by the LLM link resolver) really look like that role? Cheap, language-aware sanity check.

The LLM may answer a role even when no link fits (for example a stock page for "test drive"). A real test-drive page names
the topic in its title, a heading or its URL, whereas a stock page that merely links to it in the menu does not. Only the
title, h1-h3 and the URL path are examined, never the menu text.
"""
from __future__ import annotations

import re

from app.checks.context import Page
from app.checks.util import prices_in_text
from app.services.signals import fold

EVIDENCE: dict[str, re.Pattern] = {
    "test_drive": re.compile(r"test.?drive|testdrive|probefahrt|essai|prueba|prova|proefrit|proba (?:la )?drum|jazda probna|zkusebni jizda|programeaza|programare|rezerv"),
    "service": re.compile(r"service|atelier|werkstatt|taller|reparat|mentenan|revizi|entretien|officina|onderhoud|serwis|servis"),
    "contact": re.compile(r"contact|kontakt|contatt|contactez|contatti|kapcsolat"),
    "financing": re.compile(r"finan|leasing|credit|kredit|rate|renting|credito"),
    "faq": re.compile(r"faq|intrebari|preguntas|fragen|questions|ajutor|aide|hilfe|help|domande"),
    "stock_list": re.compile(r"stoc|stock|inventar|vehicul|masini|autoturism|cars|coches|fahrzeug|gebrauchtwagen|neuwagen|occasion|voiture|ocazi|rulate|used|new|segunda|usad|auto|veicol|samochod"),
    "locator": re.compile(r"dealer|concession|haendler|handler|reteau|retea|distribuitor|network|etablissement|point de vente|showroom|concesionario|partner|vestiging|rappresentant|reprezentant|puncte|find|trouver|gaseste|suche"),
    "configurator": re.compile(r"configur|konfigur|build|personaliz|bauen|composer"),
    "offers": re.compile(r"ofert|promo|angebot|offre|oferta|deals|aktion|campan|reducer|special|rabatt|vorteil"),
    "shop": re.compile(r"shop|magazin|accesori|zubeh|boutique|tienda|store|accessoires|accessori|piese|parts"),
    "cart": re.compile(r"\bcos\b|cos de|cart|carrito|warenkorb|panier|basket|carrello|winkelmand"),
    "checkout": re.compile(r"checkout|finaliz|comand|pago|kasse|paiement|plata|livrare si|order|bestell|commande"),
    "shipping": re.compile(r"livrare|transport|shipping|delivery|envio|versand|livraison|consegna|levering"),
    "returns": re.compile(r"retur|return|devol|ruckgabe|retour|withdrawal|retragere|reso|widerruf"),
    "warranty": re.compile(r"garanti|warranty|gewahrleist|garantie|garanzia"),
}


def _zone(page: Page) -> str:
    parts = []
    title = page.tree.css_first("title")
    if title:
        parts.append(title.text(strip=True))
    for heading in page.tree.css("h1, h2, h3"):
        parts.append(heading.text(strip=True))
    path = page.url.split("//", 1)[-1].split("/", 1)[-1]
    parts.append(path.replace("-", " ").replace("_", " "))
    return fold(" ".join(parts))


def looks_like(role: str, page: Page) -> bool:
    """True when the page plausibly is a `role` page; roles without a rule (models_list, categories, stock_new/used) always pass."""
    pattern = EVIDENCE.get(role)
    if pattern is None or not page.ok:
        return True
    if pattern.search(_zone(page)):
        return True
    return role == "stock_list" and len(prices_in_text(page.text)) >= 3  # a list of priced cars needs no heading
