#!/usr/bin/env python3
"""
SEC 13F Filings Parser
Extracts 13F institutional holdings from SEC EDGAR directly.
No external parsing libraries required.
"""

import re
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from sec_utils import get_cik_from_ticker


class SEC13FClient:
    """Client for retrieving and parsing 13F filings from SEC EDGAR."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def _resolve_cik(self, ticker_or_cik: str) -> str:
        """Resolve a ticker symbol or raw CIK to a zero-padded 10-digit CIK string."""
        cleaned = ticker_or_cik.strip()
        # If it looks like a numeric CIK (all digits, possibly zero-padded)
        if re.match(r'^0*\d+$', cleaned):
            return cleaned.zfill(10)
        # Otherwise treat it as a ticker and look it up
        return get_cik_from_ticker(cleaned, self.headers)

    def _find_latest_13f_accession(self, cik: str) -> tuple:
        """
        Query the EDGAR submissions API and return (accession, filing_date, period) for
        the most recent 13F-HR filing. Raises ValueError if none found.
        """
        url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        filer_name = data.get('name', cik)

        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        accessions = recent.get('accessionNumber', [])
        dates = recent.get('filingDate', [])
        periods = recent.get('reportDate', [])

        for i, form in enumerate(forms):
            if form in ('13F-HR', '13F-HR/A'):
                return (
                    filer_name,
                    accessions[i],
                    dates[i],
                    periods[i] if i < len(periods) else dates[i],
                )

        # Check older filings pages if recent list didn't have any
        for filing_page in data.get('filings', {}).get('files', []):
            page_url = f"{self.DATA_URL}/submissions/{filing_page['name']}"
            resp2 = requests.get(page_url, headers=self.headers, timeout=15)
            resp2.raise_for_status()
            page = resp2.json()
            pforms = page.get('form', [])
            paccessions = page.get('accessionNumber', [])
            pdates = page.get('filingDate', [])
            pperiods = page.get('reportDate', [])
            for i, form in enumerate(pforms):
                if form in ('13F-HR', '13F-HR/A'):
                    return (
                        filer_name,
                        paccessions[i],
                        pdates[i],
                        pperiods[i] if i < len(pperiods) else pdates[i],
                    )

        raise ValueError(f"No 13F-HR filings found for CIK {cik}")

    def _find_infotable_url(self, cik: str, accession: str) -> str:
        """Parse the filing index page to find the URL of infotable.xml."""
        cik_int = int(cik)
        accession_nodash = accession.replace('-', '')
        index_url = (
            f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/"
            f"{accession_nodash}/{accession}-index.htm"
        )
        resp = requests.get(index_url, headers=self.headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='tableFile')
        if not table:
            raise ValueError(f"Could not find document table in filing index {accession}")

        # Strategy: find any row described as the Information Table, then grab its
        # raw .xml link (skipping the XSL-rendered viewer which lives under /xslForm13F_*)
        for row in table.find_all('tr'):
            cols = row.find_all('td')
            row_text = ' '.join(c.get_text(strip=True).upper() for c in cols)
            if 'INFORMATION TABLE' not in row_text:
                continue
            for a in row.find_all('a', href=True):
                href_lower = a['href'].lower()
                if href_lower.endswith('.xml') and 'xsl' not in href_lower:
                    raw_href = a['href']
                    if raw_href.startswith('/'):
                        return f"{self.BASE_URL}{raw_href}"
                    return raw_href

        raise ValueError(f"Could not find infotable.xml in filing {accession}")

    def _parse_infotable_xml(self, xml_text: str) -> List[Dict]:
        """Parse 13F infotable XML into a list of holding dicts.

        Values in the XML are in thousands of USD; we multiply by 1000.
        """
        # 1. Strip xmlns declarations (xmlns="..." and xmlns:foo="...")
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
        # 2. Strip namespace-qualified attributes that became invalid (e.g., xsi:schemaLocation)
        xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
        # 3. Remove namespace prefixes from tag names (e.g., <n1:infoTable> → <infoTable>)
        xml_clean = re.sub(r'<(/?)[\w]+:([\w]+)', r'<\1\2', xml_clean)

        try:
            root = ET.fromstring(xml_clean)
        except ET.ParseError:
            # Last resort: strip all namespace prefixes from original
            xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
            xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
            xml_clean = re.sub(r'<(/?)[\w.-]+:([\w.-]+)', r'<\1\2', xml_clean)
            root = ET.fromstring(xml_clean)

        holdings = []
        for entry in root.iter('infoTable'):
            name = (entry.findtext('nameOfIssuer') or '').strip()
            title = (entry.findtext('titleOfClass') or '').strip()
            cusip = (entry.findtext('cusip') or '').strip()
            value_str = (entry.findtext('value') or '0').replace(',', '')

            shrs_el = entry.find('shrsOrPrnAmt')
            shares_str = '0'
            shares_type = ''
            if shrs_el is not None:  # use 'is not None' to avoid ElementTree deprecation warning
                shares_str = (shrs_el.findtext('sshPrnamt') or '0').replace(',', '')
                shares_type = (shrs_el.findtext('sshPrnamtType') or '').strip()

            try:
                # Despite form instructions saying "in thousands", the XML value field
                # is stored in whole dollars by convention across major filers
                value_dollars = int(value_str)
            except ValueError:
                value_dollars = 0
            try:
                shares = int(shares_str)
            except ValueError:
                shares = 0

            holdings.append({
                'name': name,
                'title': title,
                'cusip': cusip,
                'value': value_dollars,
                'shares': shares,
                'shares_type': shares_type,
            })

        return holdings

    def get_latest_13f_holdings(self, ticker_or_cik: str) -> Dict[str, Any]:
        """
        Get the latest 13F holdings for a given ticker or CIK.

        Args:
            ticker_or_cik: Ticker symbol or 10-digit CIK of the investment firm.

        Returns:
            Dict with filer name, period, and list of holdings.
        """
        cik = self._resolve_cik(ticker_or_cik)
        filer_name, accession, filing_date, period = self._find_latest_13f_accession(cik)
        infotable_url = self._find_infotable_url(cik, accession)

        resp = requests.get(infotable_url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        holdings = self._parse_infotable_xml(resp.text)

        return {
            'filer': filer_name,
            'cik': cik,
            'period': period,
            'filing_date': filing_date,
            'accession': accession,
            'holdings': holdings,
        }


def format_13f_holdings(
    holdings_data: Dict[str, Any],
    top_n: int = 20,
    return_all: bool = False,
) -> str:
    """Format 13F holdings for display."""
    if not holdings_data or not holdings_data.get('holdings'):
        return "No holdings data available."

    holdings = sorted(holdings_data['holdings'], key=lambda h: h['value'], reverse=True)

    total_value = sum(h['value'] for h in holdings)
    total_positions = len(holdings)

    if not return_all:
        display = holdings[:top_n]
        header_line = f"Top {min(top_n, total_positions)} Holdings (by value)"
    else:
        display = holdings
        header_line = "All Holdings (by value)"

    lines = [
        f"\n{'='*80}",
        f"13F Holdings — {holdings_data['filer']}",
        f"Period of Report:  {holdings_data.get('period', 'N/A')}",
        f"Filed:             {holdings_data.get('filing_date', 'N/A')}",
        f"Total Positions:   {total_positions}",
        f"Total Value:       ${total_value:,.0f}",
        f"{'='*80}",
        f"\n{header_line}:\n",
        f"{'#':<4} {'Company':<40} {'Value (USD)':>15} {'Shares':>12} {'Type':<5} {'% AUM':>7}",
        f"{'-'*4} {'-'*40} {'-'*15} {'-'*12} {'-'*5} {'-'*7}",
    ]

    for rank, h in enumerate(display, 1):
        pct = (h['value'] / total_value * 100) if total_value else 0
        lines.append(
            f"{rank:<4} {h['name'][:39]:<40} ${h['value']:>14,.0f} "
            f"{h['shares']:>12,} {h['shares_type']:<5} {pct:>6.1f}%"
        )

    if not return_all and total_positions > top_n:
        lines.append(f"\n... and {total_positions - top_n} more positions. Use return_all=true to see all.")

    return '\n'.join(lines)
