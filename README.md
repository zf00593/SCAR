# UK Earnings & Cost-of-Living Data

Two halves: `fetch_data.py` pulls everything with a public API, and the tables
below list what you have to download by hand.

Nothing here requires an access request, application, approval, or institutional
affiliation. See [What's deliberately missing](#whats-deliberately-missing) for
why that rules out all genuine person-level income data.

## Quick start

```bash
pip install requests pandas
python fetch_data.py --list          # sources and which need a key
python fetch_data.py                 # fetch everything that needs no key
python fetch_data.py --only ons nomis landregistry
python fetch_data.py --rows 5000     # raise the per-source sample cap
```

Output lands in `data/`, one CSV per source, plus `data/_manifest.csv`
recording row counts and fetch timestamps.

**Untested against the live APIs.** This was written in a sandbox with no
network access to any of these hosts. The parsing logic is tested against mocked
responses (`python test_fetch_mocked.py`, 12 CSVs, all paths pass), but endpoint
URLs, auth headers and Nomis dimension codes need one real run to confirm.
Expect to fix something on first contact.

## Part 1 — API sources (automated)

| Source | Key | What you get | Level |
|---|---|---|---|
| **ONS API** | none | CPIH inflation, private rental price index, plus a full catalogue dump so you can find other dataset ids | Aggregate |
| **Nomis** | optional | ASHE earnings by local authority, on both a **workplace** and **residence** basis, with dimension code lookups | Aggregate |
| **HM Land Registry** | none | Every residential sale in England & Wales, with price, date, postcode | Transaction |
| **Adzuna** | free, instant | Job adverts: salary min/max, location, lat/lon, employer, contract type | Advert |
| **Reed** | free, instant | Job adverts: salary range, location, employer | Advert |
| **DWP Stat-Xplore** | free, instant | Dataset schema index for benefits and pensioner income | Aggregate |

Keys go in environment variables:

```bash
export NOMIS_UID=...        # nomisweb.co.uk/myaccount/userjoin.asp — raises row cap 25k→100k
export ADZUNA_APP_ID=...    # developer.adzuna.com
export ADZUNA_APP_KEY=...
export REED_API_KEY=...     # reed.co.uk/developers
export STATXPLORE_KEY=...   # Stat-Xplore account page
```

Sources whose key is unset are skipped with a note, not an error. All three keys
are self-service and issued instantly — no application to review.

### Notes that will bite you

- **Adzuna predicts salaries** when an advert omits one, flagged by
  `salary_is_predicted`. Filter on it before computing any average, or you're
  averaging their model's output rather than advertised pay.
- **Job adverts are not people.** They describe vacancies, skew toward hiring
  sectors and higher-churn roles, and one employer posting the same role in ten
  towns produces ten rows. Don't present them as an earnings distribution.
- **Nomis dimension codes** (`item=2`, `pay=1`, `sex=8`) are meaningless on
  their own and differ per dataset — hence the `nomis_*_codes.csv` lookups the
  scraper writes alongside the data.
- **ASHE workplace vs resident** is the only "where they work" split available
  without an access request. Workplace = people working in an area; resident =
  people living in it. In commuter areas these differ a lot, and mixing them up
  is the most common error in local earnings analysis.
- **Some ONS API datasets are archived** and stopped updating. Check
  `next_release` in `ons_catalogue.csv` before relying on one.
- **Stat-Xplore** only gets you the schema index here. Building a `/table` query
  needs dataset-specific measure and field ids — pick an id from the CSV, fetch
  its `/schema/{id}`, then construct the query. I didn't guess them.

## Part 2 — Manual downloads, no request needed

All free, all downloadable immediately, all Open Government Licence unless noted.

### Person-level records (the only openly redistributable ones)

| Dataset | What it is | Format | Link |
|---|---|---|---|
| **Census 2021 Microdata Teaching File** (England & Wales) | 604,351 individual person records, 1% sample, 19 variables. Region-level geography. **No income variable** — the census doesn't ask. | CSV | ons.gov.uk → Census → Census products → Microdata samples |
| **Census 2021 microdata** (Northern Ireland) | NISRA equivalent, published Jan 2025 | CSV | nisra.gov.uk |
| **Census 2022 microdata** (Scotland) | NRS equivalent | CSV | nrscotland.gov.uk |
| **SPENSER synthetic population** | Individual-level *synthetic* GB population to MSOA level, from Leeds/Alan Turing Institute. Modelled, not observed. | CSV / code | github.com/alan-turing-institute → SPENSER repos |

These are the only person-level files you can legally publish or redistribute.
Use them for demographic and occupational cross-tabs; combine with ASHE for
wages and the expenditure surveys for costs.

### Earnings

| Dataset | What it is | Format | Where |
|---|---|---|---|
| **ASHE reference tables** | Full ASHE outputs — by occupation (4-digit SOC), industry, region, age, full/part-time. Far more detail than Nomis exposes. | XLSX | ons.gov.uk → Employment and labour market → Earnings and working hours |
| **Employee earnings in the UK** | Annual bulletin with headline medians and distributions | XLSX / HTML | ons.gov.uk, published each October |
| **Low Pay Commission reports** | Minimum wage analysis, distributions near the wage floor | XLSX / PDF | gov.uk/government/organisations/low-pay-commission |

### Cost of living

| Dataset | What it is | Format | Where |
|---|---|---|---|
| **Ofgem energy price cap** | Unit rates and standing charges by region, quarterly. No API. | XLSX / CSV | ofgem.gov.uk → Energy price cap |
| **Family spending in the UK** | Household expenditure by category, region, income decile — the aggregate view of the Living Costs and Food Survey | XLSX | ons.gov.uk → Personal and household finances |
| **VOA private rental market statistics** | Rent distributions by local authority and property size | XLSX | gov.uk/government/collections/private-rental-market-statistics |
| **Land Registry Price Paid bulk** | Complete file, 1995→present, ~30M rows. Faster than the SPARQL API for bulk work. | CSV | landregistry.data.gov.uk → Price Paid Data |
| **UK House Price Index** | Monthly index by local authority and property type | CSV | gov.uk/government/collections/uk-house-price-index-reports |
| **Council tax levels** | Band D and average bills by billing authority | XLSX | gov.uk → MHCLG statistics |
| **English Housing Survey** headline reports | Housing costs, affordability, tenure | XLSX / PDF | gov.uk/government/collections/english-housing-survey |

Land Registry address data carries Royal Mail and Ordnance Survey third-party
rights that restrict some commercial reuse — check before publishing anything
address-level.

## What's deliberately missing

You asked to exclude anything requiring an access request. That excludes every
source of genuine person-level UK income data:

- **UK Data Service** — Labour Force Survey, Understanding Society, Living Costs
  and Food Survey, Family Resources Survey, Wealth and Assets Survey. Free, but
  needs registration and End User Licence acceptance, and even then you may only
  publish derived non-disclosive outputs, never the records.
- **ONS Secure Research Service / Integrated Data Service** — record-level ASHE
  (the 1% PAYE sample), the ONS Longitudinal Study. Needs accredited-researcher
  status, a sponsoring organisation and an approved public-good project.

So: **no open API returns person-level UK earnings, and nothing in this repo
does either.** The closest available substitutes are job adverts (one row per
vacancy) and the census teaching file (real individuals, no income). If the
project genuinely needs person-level income, the UKDS End User Licence route is
the realistic option — free, a few days, but it rules out publishing raw records.

## Attribution

ONS, Nomis, Land Registry, DWP and census data are Open Government Licence v3.0
— reuse freely with attribution. Adzuna and Reed are commercial terms: cache and
aggregate rather than republishing raw adverts, and attribute the source.
