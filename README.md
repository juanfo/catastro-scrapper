# catastro-scraper

Command-line tool to scrape property data from Spain's public [Catastro](https://www.catastro.meh.es/) API. Given a province, municipality, and street name, it finds all properties and exports a CSV with:

- Cadastral reference (*referencia catastral*)
- House number and street
- Built surface (m²)
- Plot surface (m²)
- Year built
- Use (residential, commercial, etc.)

## Requirements

- Python 3.8+
- No external dependencies (stdlib only)

## Usage

```bash
python3 catastro.py PROVINCE MUNICIPALITY STREET
```

### Examples

```bash
# All properties on a street in a municipality
python3 catastro.py MADRID GETAFE "GRAN VIA"

# Street in a multi-word municipality
python3 catastro.py BARCELONA "SANT CUGAT DEL VALLES" MAJOR

# Custom output file and scan limit
python3 catastro.py VALENCIA VALENCIA COLON -o results.csv --max-number 200

# Fast mode — skip plot surface (no Sede Electrónica scraping)
python3 catastro.py SEVILLA SEVILLA SIERPES --no-plot-surface
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output`, `-o` | `<municipality>_<street>_catastro.csv` | Output CSV file path |
| `--max-number` | `500` | Maximum house number to scan |
| `--consecutive-misses` | `40` | Stop scanning after this many consecutive missing numbers |
| `--no-plot-surface` | off | Skip plot surface lookup (much faster) |

## Output

The CSV contains one row per property:

```
Referencia Catastral,Number,Street,Built Surface (m2),Plot Surface (m2),Year Built,Use
1234567AB1234N0001XY,5,CL MAYOR,120,350,1985,Residencial
```

A summary is also printed to the terminal after completion.

## How it works

1. **Street discovery** — queries the Catastro `ConsultaVia` endpoint to find all streets matching your search term
2. **Property scan** — iterates house numbers 1 to N on each street, calling `Consulta_DNPLOC` to get cadastral references, built surface, year, and use
3. **Plot surface** — for each property, scrapes the [Sede Electrónica del Catastro](https://www1.sedecatastro.gob.es/) page to extract the *superficie gráfica* (plot area)
4. **CSV export** — writes all results sorted by street and number

Rate limiting (0.3s between requests) and retries are built in to be respectful to the public API.