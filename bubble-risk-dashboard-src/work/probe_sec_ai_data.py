from __future__ import annotations

import json
from urllib.request import Request, urlopen


UA = "Codex bubble-risk-dashboard contact: user@example.com"
CIKS = {
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "AMZN": "0001018724",
    "ORCL": "0001341439",
    "CRWV": "0001769628",
}


def fetch(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return json.load(urlopen(Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30))


for ticker, cik in CIKS.items():
    data = fetch(cik)
    facts = data.get("facts", {}).get("us-gaap", {})
    print("\n", ticker, data.get("entityName"))
    for tag in [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
        "LongTermDebt",
        "LongTermDebtCurrent",
        "LongTermDebtNoncurrent",
        "DebtInstrumentCarryingAmount",
        "ProceedsFromIssuanceOfLongTermDebt",
        "RepaymentsOfLongTermDebt",
        "PropertyPlantAndEquipmentNet",
    ]:
        units = facts.get(tag, {}).get("units", {})
        count = sum(len(v) for v in units.values())
        if count:
            frames = []
            for unit_rows in units.values():
                frames += [r.get("frame") for r in unit_rows if r.get("frame")]
            print(tag, count, sorted(set(frames))[-8:])
