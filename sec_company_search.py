#!/usr/bin/env python3
"""
SEC EDGAR Company Search
Searches for companies/filers by name and returns CIK numbers.
Useful for finding investment firms, funds, and other entities that
don't have public stock tickers.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional


class SECCompanySearchClient:
    """Search EDGAR for companies/filers by name."""

    BASE_URL = "https://www.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def search_by_name(
        self,
        name: str,
        filing_type: str = '',
        count: int = 20,
    ) -> List[Dict]:
        """
        Search EDGAR for companies/filers matching a name.

        Args:
            name: Company or filer name to search (partial match supported)
            filing_type: Optional filing type to filter by (e.g., '13F-HR', '10-K').
                         Leave empty to return all filer types.
            count: Maximum number of results to return (default 20)

        Returns:
            List of dicts with company name, CIK, state, SIC, and latest filing date
        """
        url = f"{self.BASE_URL}/cgi-bin/browse-edgar"
        params = {
            'company': name,
            'CIK': '',
            'type': filing_type,
            'dateb': '',
            'owner': 'include',
            'count': str(min(count, 100)),
            'search_text': '',
            'action': 'getcompany',
        }

        response = requests.get(url, params=params, headers=self.headers, timeout=15)
        response.raise_for_status()

        return self._parse_results(response.text)

    def _parse_results(self, html: str) -> List[Dict]:
        """Parse the EDGAR company search results HTML."""
        soup = BeautifulSoup(html, 'html.parser')

        results = []

        # Results are in a table with class 'tableFile2'
        table = soup.find('table', class_='tableFile2')
        if not table:
            return results

        rows = table.find_all('tr')[1:]  # skip header
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 4:
                continue

            # Column layout: Entity Name | CIK | State | SIC | Latest Filing Date
            name_cell = cols[0]
            cik_cell = cols[1] if len(cols) > 1 else None
            state_cell = cols[2] if len(cols) > 2 else None
            sic_cell = cols[3] if len(cols) > 3 else None
            date_cell = cols[4] if len(cols) > 4 else None

            company_name = name_cell.get_text(strip=True)
            cik_raw = cik_cell.get_text(strip=True) if cik_cell else ''
            # CIK is displayed without leading zeros in the table; zero-pad to 10
            try:
                cik = str(int(cik_raw)).zfill(10)
            except ValueError:
                cik = cik_raw

            results.append({
                'name': company_name,
                'cik': cik,
                'state': state_cell.get_text(strip=True) if state_cell else '',
                'sic': sic_cell.get_text(strip=True) if sic_cell else '',
                'latest_filing': date_cell.get_text(strip=True) if date_cell else '',
            })

        return results


def format_company_search_results(results: List[Dict], query: str) -> str:
    """Format company search results for display."""
    if not results:
        return f"No companies found matching '{query}'."

    output = [
        f"\n{'='*80}",
        f"EDGAR Company Search — '{query}'",
        f"{'='*80}",
        f"{'Company Name':<50} {'CIK':<12} {'State':<6} {'Latest Filing'}",
        f"{'-'*50} {'-'*12} {'-'*6} {'-'*15}",
    ]

    for r in results:
        output.append(
            f"{r['name'][:49]:<50} {r['cik']:<12} {r['state']:<6} {r['latest_filing']}"
        )

    output.append(f"\n{len(results)} result(s) returned.")
    output.append(
        "Use the 'cik' value with get-13f-holdings or get-sec-filings to retrieve filings."
    )

    return '\n'.join(output)
