"""
Stratz API probe (prototype).

Set your token first (never hardcode it):
    Windows (PowerShell):  $env:STRATZ_TOKEN = "your-token"
    macOS/Linux:           export STRATZ_TOKEN="your-token"

Commands:
    python stratz_probe.py ping
        Tiny query to confirm the token and headers work.

    python stratz_probe.py matchup 1
        Fetches matchup + synergy rows for hero id 1 (Anti-Mage),
        Legend bracket, and prints the raw JSON.

    python stratz_probe.py type HeroStatsHeroDryadType
        Lists the fields available on that type. Use it when a query
        complains that a field doesn't exist.

    python stratz_probe.py raw "query { constants { heroes { id displayName } } }"
        Runs any GraphQL query you give it and prints the response.

The matchUp query below is written from memory of Stratz's schema and may
need adjusting. If it errors, paste the error message back and we'll fix it.

Requires: pip install requests
"""

import json
import os
import sys

import requests

URL = "https://api.stratz.com/graphql"
BRACKET = "LEGEND_ANCIENT"  # Legend + Ancient bracket group on Stratz


def run(query):
    token = os.environ.get("STRATZ_TOKEN")
    if not token:
        sys.exit("Set the STRATZ_TOKEN environment variable first.")
    r = requests.post(
        URL,
        json={"query": query},
        headers={
            "Authorization": f"Bearer {token}",
            # Stratz sits behind Cloudflare and rejects requests without this.
            "User-Agent": "STRATZ_API",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        sys.exit(r.text[:500])
    print(json.dumps(data, indent=2)[:6000])
    return data


def ping():
    run("query { constants { heroes { id displayName } } }")


def describe(type_name):
    """List the fields of a GraphQL type (Stratz may restrict this)."""
    run(
        'query { __type(name: "%s") { name fields { name type { name kind '
        'ofType { name kind } } } } }' % type_name
    )


def matchup(hero_id):
    q = f"""
    query {{
      heroStats {{
        matchUp(
          heroId: {hero_id},
          bracketBasicIds: {BRACKET},
          take: 200
        ) {{
          heroId
          vs {{ heroId2 matchCount winCount }}
          with {{ heroId2 matchCount winCount }}
        }}
      }}
    }}
    """
    run(q)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["ping"]:
        ping()
    elif len(args) == 2 and args[0] == "matchup":
        matchup(int(args[1]))
    elif len(args) == 2 and args[0] == "type":
        describe(args[1])
    elif len(args) == 2 and args[0] == "raw":
        run(args[1])
    else:
        print(__doc__)
