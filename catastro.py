#!/usr/bin/env python3
"""
Generic Spanish Catastro property scraper.

Queries the public Catastro OVC API for all properties on a given street
in a given municipality and outputs a CSV with cadastral reference,
address, built surface, plot surface, year, and use.

Usage:
    python3 catastro.py PROVINCE MUNICIPALITY STREET
    python3 catastro.py TOLEDO ALMOROX "PINAR ALMOROX"
    python3 catastro.py MADRID "SAN MARTIN DE VALDEIGLESIAS" REAL --max-number 200
    python3 catastro.py TOLEDO ALMOROX "PINAR ALMOROX" --output my_results.csv
"""

import argparse
import csv
import re
import sys
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE_API = "https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCallejero.asmx"
SEDE_URL = "https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCConCiud.aspx"


def fetch_url(url, retries=3):
    """Fetch a URL with retries and rate limiting."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"  [WARN] Failed to fetch: {e}", file=sys.stderr)
                return None


def lookup_municipality_codes(province, municipality):
    """Look up Catastro province delegation and municipality codes.

    These numeric codes are needed for the Sede Electrónica URL
    (del=XX&mun=YY) to fetch plot surfaces.

    Returns (del_code, mun_code) or (None, None) on failure.
    """
    url = (
        f"{BASE_API}/ConsultaMunicipio?"
        f"Provincia={quote(province)}&Municipio={quote(municipality)}"
    )
    xml_text = fetch_url(url)
    if not xml_text:
        return None, None

    # XML structure: <locat><cd>28</cd><cmc>8</cmc></locat>
    #                <loine><cp>28</cp><cm>8</cm></loine>
    del_match = re.search(r"<cd>(\d+)</cd>", xml_text)
    if not del_match:
        del_match = re.search(r"<cp>(\d+)</cp>", xml_text)

    mun_match = re.search(r"<cmc>(\d+)</cmc>", xml_text)
    if not mun_match:
        mun_match = re.search(r"<cm>(\d+)</cm>", xml_text)

    del_code = del_match.group(1) if del_match else None
    mun_code = mun_match.group(1) if mun_match else None

    return del_code, mun_code


def discover_streets(province, municipality, street_query):
    """Query the Catastro API to find streets matching the query."""
    url = (
        f"{BASE_API}/ConsultaVia?"
        f"Provincia={quote(province)}&Municipio={quote(municipality)}"
        f"&TipoVia=&NombreVia={quote(street_query)}"
    )
    xml_text = fetch_url(url)
    if not xml_text:
        return [("CL", street_query)]

    names = re.findall(r"<nv>([^<]+)</nv>", xml_text)
    types = re.findall(r"<tv>([^<]+)</tv>", xml_text)

    streets = []
    for i, name in enumerate(names):
        sigla = types[i] if i < len(types) else "CL"
        streets.append((sigla, name))

    if not streets:
        streets = [("CL", street_query)]

    return streets


def get_property_from_api(province, municipality, number, street_name, street_type="CL"):
    """Query the Catastro API for a property by house number. Returns dict or None."""
    url = (
        f"{BASE_API}/Consulta_DNPLOC?"
        f"Provincia={quote(province)}&Municipio={quote(municipality)}"
        f"&Sigla={quote(street_type)}&Calle={quote(street_name)}"
        f"&Numero={number}&Bloque=&Escalera=&Planta=&Puerta="
    )
    xml_text = fetch_url(url)
    if not xml_text:
        return None

    try:
        ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    # Check for errors
    if re.search(r"<cuerr>[^0]", xml_text):
        return None

    # Extract cadastral reference parts
    pc1 = re.search(r"<pc1>([^<]+)</pc1>", xml_text)
    pc2 = re.search(r"<pc2>([^<]+)</pc2>", xml_text)
    car = re.search(r"<car>([^<]+)</car>", xml_text)
    cc1 = re.search(r"<cc1>([^<]+)</cc1>", xml_text)
    cc2 = re.search(r"<cc2>([^<]+)</cc2>", xml_text)

    if not pc1 or not pc2:
        return None

    parcel_ref = pc1.group(1) + pc2.group(1)
    full_ref = parcel_ref
    if car:
        full_ref += car.group(1)
    if cc1:
        full_ref += cc1.group(1)
    if cc2:
        full_ref += cc2.group(1)

    # Extract built surface
    sfc = re.search(r"<sfc>(\d+)</sfc>", xml_text)
    built_surface = int(sfc.group(1)) if sfc else 0

    # Extract year
    ant = re.search(r"<ant>(\d+)</ant>", xml_text)
    year = ant.group(1) if ant else ""

    # Extract use
    luso = re.search(r"<luso>([^<]+)</luso>", xml_text)
    use = luso.group(1) if luso else ""

    return {
        "number": number,
        "street": f"{street_type} {street_name}",
        "referencia_catastral": full_ref,
        "parcel_ref": parcel_ref,
        "built_surface_m2": built_surface,
        "year": year,
        "use": use,
    }


def get_plot_surface(cadastral_ref, del_code, mun_code):
    """Fetch plot/terrain surface from the Sede Electrónica viewer page."""
    if not del_code or not mun_code:
        return None

    url = (
        f"{SEDE_URL}?UrbRus=U&RefC={quote(cadastral_ref)}"
        f"&from=OVCBusqueda&pest=rc&RCCompleta={quote(cadastral_ref)}"
        f"&final=&del={del_code}&mun={mun_code}"
    )
    html = fetch_url(url)
    if not html:
        return None

    match = re.search(
        r"Superficie\s+gr.fica.*?>([\d.]+)\s*m", html, re.DOTALL | re.IGNORECASE
    )
    if match:
        value = match.group(1).replace(".", "")  # "1.052" -> "1052"
        try:
            result = int(value)
            if result > 0:
                return result
        except ValueError:
            pass

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Scrape properties from the Spanish Catastro API.",
        epilog="Example: python3 catastro.py TOLEDO ALMOROX 'PINAR ALMOROX'",
    )
    parser.add_argument("province", help="Province name (e.g. TOLEDO, MADRID)")
    parser.add_argument("municipality", help="Municipality name (e.g. ALMOROX)")
    parser.add_argument("street", help="Street name or partial match (e.g. 'PINAR ALMOROX')")
    parser.add_argument(
        "--max-number", type=int, default=500,
        help="Maximum house number to scan (default: 500)",
    )
    parser.add_argument(
        "--consecutive-misses", type=int, default=40,
        help="Stop scanning a street after this many consecutive misses (default: 40)",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output CSV file (default: <municipality>_<street>_catastro.csv)",
    )
    parser.add_argument(
        "--no-plot-surface", action="store_true",
        help="Skip fetching plot surface from Sede Electrónica (faster)",
    )
    args = parser.parse_args()

    province = args.province.upper()
    municipality = args.municipality.upper()
    street = args.street.upper()

    output_file = args.output or f"{municipality.lower().replace(' ', '_')}_{street.lower().replace(' ', '_')}_catastro.csv"

    # Step 1: Look up municipality codes for Sede Electrónica
    del_code, mun_code = None, None
    if not args.no_plot_surface:
        print(f"Looking up Catastro codes for {municipality}, {province}...")
        del_code, mun_code = lookup_municipality_codes(province, municipality)
        if del_code and mun_code:
            print(f"  Province code: {del_code}, Municipality code: {mun_code}")
        else:
            print("  [WARN] Could not determine municipality codes; plot surface will be skipped.")

    # Step 2: Discover matching streets
    print(f"\nDiscovering streets matching '{street}' in {municipality}...")
    streets = discover_streets(province, municipality, street)
    print(f"Found {len(streets)} street section(s):")
    for sigla, name in streets:
        print(f"  - {sigla} {name}")
    print()

    properties = []

    # Step 3: Scan each street
    for street_type, street_name in streets:
        print(f"=== Scanning: {street_type} {street_name} (numbers 1-{args.max_number}) ===")

        consecutive_misses = 0
        found_in_street = 0

        for num in range(1, args.max_number + 1):
            prop = get_property_from_api(province, municipality, num, street_name, street_type)
            if prop is None:
                consecutive_misses += 1
                if consecutive_misses > args.consecutive_misses:
                    print(f"  Reached end of street at number ~{num - args.consecutive_misses}")
                    break
                continue

            consecutive_misses = 0
            found_in_street += 1
            ref = prop["referencia_catastral"]
            print(
                f"  #{num}: ref={ref} built={prop['built_surface_m2']}m²",
                end="",
                flush=True,
            )

            # Step 4: Fetch plot surface from Sede Electrónica
            if not args.no_plot_surface:
                plot_surface = get_plot_surface(prop["referencia_catastral"], del_code, mun_code)
                prop["plot_surface_m2"] = plot_surface if plot_surface else ""
                if plot_surface:
                    print(f" plot={plot_surface}m²")
                else:
                    print(" plot=N/A")
            else:
                prop["plot_surface_m2"] = ""
                print()

            properties.append(prop)
            time.sleep(0.3)

        print(f"  Found {found_in_street} properties in {street_type} {street_name}\n")

    # Step 5: Write CSV
    print(f"Writing {len(properties)} properties to {output_file}...")
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Referencia Catastral",
            "Number",
            "Street",
            "Built Surface (m2)",
            "Plot Surface (m2)",
            "Year Built",
            "Use",
        ])
        for prop in sorted(properties, key=lambda p: (p["street"], p["number"])):
            writer.writerow([
                prop["referencia_catastral"],
                prop["number"],
                prop["street"],
                prop["built_surface_m2"],
                prop["plot_surface_m2"],
                prop["year"],
                prop["use"],
            ])

    print(f"Done! {len(properties)} properties exported to {output_file}")

    # Summary
    if properties:
        built = [p["built_surface_m2"] for p in properties if p["built_surface_m2"] > 0]
        plots = [p["plot_surface_m2"] for p in properties if isinstance(p["plot_surface_m2"], int)]
        print(f"\nSummary:")
        print(f"  Total properties: {len(properties)}")
        if built:
            print(f"  Built surface range: {min(built)} - {max(built)} m²")
        if plots:
            print(f"  Plot surface range: {min(plots)} - {max(plots)} m²")


if __name__ == "__main__":
    main()
