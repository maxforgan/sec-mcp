#!/usr/bin/env python3
"""
SEC Form 144 Parser — Insider Pre-Sales Notification
Fetches and parses Form 144 (Notice of Proposed Sale of Securities)
filed by insiders before selling restricted securities.
"""

import re
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from sec_utils import get_cik_from_ticker


def _findval(element, tag: str) -> str:
    """
    Safely extract text from a Form 144 XML field.
    SEC Form 144 wraps most values in a <value> child element; falls back to
    direct element text if <value> is absent.
    """
    el = element.find(tag)
    if el is None:
        return ''
    val = el.findtext('value')
    if val is not None:
        return val.strip()
    return (el.text or '').strip()


class SECForm144Client:
    """Client for fetching and parsing Form 144 insider pre-sales notification filings."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def _get_form144_accessions(self, cik: str, count: int = 30) -> List[Dict]:
        """Return up to `count` Form 144 filings for the given CIK, newest first."""
        url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        recent = data['filings']['recent']
        forms = recent.get('form', [])
        accessions = recent.get('accessionNumber', [])
        dates = recent.get('filingDate', [])

        filings = []
        for i, form in enumerate(forms):
            if form == '144':
                filings.append({'accession': accessions[i], 'date': dates[i]})
                if len(filings) >= count:
                    break

        # If we need more, check paginated older filings
        for filing_page in data.get('filings', {}).get('files', []):
            if len(filings) >= count:
                break
            page_url = f"{self.DATA_URL}/submissions/{filing_page['name']}"
            resp2 = requests.get(page_url, headers=self.headers, timeout=15)
            resp2.raise_for_status()
            page = resp2.json()
            for i, form in enumerate(page.get('form', [])):
                if form == '144':
                    filings.append({
                        'accession': page['accessionNumber'][i],
                        'date': page['filingDate'][i],
                    })
                    if len(filings) >= count:
                        break

        return filings

    def _find_xml_url(self, cik: str, accession: str) -> Optional[str]:
        """Locate the raw Form 144 XML URL in the filing index."""
        cik_int = int(cik)
        accession_nodash = accession.replace('-', '')
        index_url = (
            f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/"
            f"{accession_nodash}/{accession}-index.htm"
        )
        resp = requests.get(index_url, headers=self.headers, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', class_='tableFile')
        if not table:
            return None

        for row in table.find_all('tr'):
            a = row.find('a', href=True)
            if not a:
                continue
            href_lower = a['href'].lower()
            # Form 144 XML: ends in .xml, not the XSL viewer
            if href_lower.endswith('.xml') and 'xsl' not in href_lower:
                raw = a['href']
                return f"{self.BASE_URL}{raw}" if raw.startswith('/') else raw

        return None

    def _parse_xml(self, xml_text: str, filing_date: str) -> List[Dict]:
        """Parse Form 144 XML into a list of proposed sale notifications."""
        # Strip namespaces (defensive; Form 144 XML usually has none)
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
        xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
        xml_clean = re.sub(r'<(/?)[\w]+:([\w]+)', r'<\1\2', xml_clean)

        try:
            root = ET.fromstring(xml_clean)
        except ET.ParseError:
            return []

        # Issuer
        issuer = root.find('issuer')
        issuer_name = (issuer.findtext('issuerName') or '') if issuer is not None else ''
        issuer_ticker = (issuer.findtext('issuerTradingSymbol') or '') if issuer is not None else ''

        # Reporting person
        reporting_person = root.find('reportingPerson')
        person_name = ''
        person_title = ''
        if reporting_person is not None:
            person_name = (reporting_person.findtext('name') or '') if reporting_person is not None else ''
            person_title = (reporting_person.findtext('title') or '') if reporting_person is not None else ''

        # Proposed sale information
        sales = []
        sale_elements = root.findall('proposedSale') or root.findall('sale')
        
        for sale_el in sale_elements:
            # Security information
            security_title = _findval(sale_el, 'securityTitle') or _findval(sale_el, 'titleOfSecurity')
            shares = 0
            try:
                shares_str = _findval(sale_el, 'shares') or _findval(sale_el, 'numberOfShares')
                shares = int(float(shares_str.replace(',', '')) if shares_str else 0)
            except (ValueError, AttributeError):
                pass

            # Sale date
            sale_date = _findval(sale_el, 'saleDate') or _findval(sale_el, 'dateOfSale') or filing_date

            # Price information
            price_per_share = 0.0
            try:
                price_str = _findval(sale_el, 'pricePerShare') or _findval(sale_el, 'price')
                price_per_share = float(price_str.replace('$', '').replace(',', '')) if price_str else 0.0
            except (ValueError, AttributeError):
                pass

            # Nature of ownership
            nature = _findval(sale_el, 'natureOfOwnership') or _findval(sale_el, 'nature')

            sales.append({
                'filing_date': filing_date,
                'issuer_name': issuer_name,
                'issuer_ticker': issuer_ticker,
                'person_name': person_name.title() if person_name else '',
                'person_title': person_title,
                'security_title': security_title,
                'shares': shares,
                'price_per_share': price_per_share,
                'total_value': shares * price_per_share if shares and price_per_share else 0,
                'sale_date': sale_date,
                'nature_of_ownership': nature,
            })

        # If no sale elements found, create one from root-level data
        if not sales:
            security_title = _findval(root, 'securityTitle') or _findval(root, 'titleOfSecurity')
            shares = 0
            try:
                shares_str = _findval(root, 'shares') or _findval(root, 'numberOfShares')
                shares = int(float(shares_str.replace(',', '')) if shares_str else 0)
            except (ValueError, AttributeError):
                pass

            price_per_share = 0.0
            try:
                price_str = _findval(root, 'pricePerShare') or _findval(root, 'price')
                price_per_share = float(price_str.replace('$', '').replace(',', '')) if price_str else 0.0
            except (ValueError, AttributeError):
                pass

            if shares > 0:
                sales.append({
                    'filing_date': filing_date,
                    'issuer_name': issuer_name,
                    'issuer_ticker': issuer_ticker,
                    'person_name': person_name.title() if person_name else '',
                    'person_title': person_title,
                    'security_title': security_title,
                    'shares': shares,
                    'price_per_share': price_per_share,
                    'total_value': shares * price_per_share if shares and price_per_share else 0,
                    'sale_date': filing_date,
                    'nature_of_ownership': '',
                })

        return sales

    def get_form144_notifications(
        self,
        ticker: str,
        count: int = 40,
    ) -> Dict[str, Any]:
        """
        Get recent Form 144 pre-sales notifications for a public company.

        Args:
            ticker: Stock ticker symbol.
            count: Number of Form 144 filings to process (default 40; each filing
                   may contain multiple proposed sales).

        Returns:
            Dict with company info and list of proposed sales, newest first.
        """
        cik = get_cik_from_ticker(ticker, self.headers)

        # Get company name from submissions
        subs_url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        subs = requests.get(subs_url, headers=self.headers, timeout=15).json()
        company_name = subs.get('name', ticker.upper())

        filings = self._get_form144_accessions(cik, count=count)

        all_sales = []
        for f in filings:
            try:
                xml_url = self._find_xml_url(cik, f['accession'])
                if not xml_url:
                    continue
                xml_resp = requests.get(xml_url, headers=self.headers, timeout=15)
                xml_resp.raise_for_status()
                sales = self._parse_xml(xml_resp.text, f['date'])
                all_sales.extend(sales)
            except Exception:
                continue

        # Sort newest first
        all_sales.sort(key=lambda s: s['filing_date'], reverse=True)

        return {
            'company': company_name,
            'ticker': ticker.upper(),
            'cik': cik,
            'notifications': all_sales,
        }


def format_form144_notifications(
    data: Dict[str, Any],
    max_rows: int = 50,
) -> str:
    """Format Form 144 notifications for display."""
    if not data or not data.get('notifications'):
        return "No Form 144 notifications found."

    notifications = data['notifications']

    lines = [
        f"\n{'='*90}",
        f"Form 144 Pre-Sales Notifications — {data['company']} ({data['ticker']})",
        f"Total notifications shown: {min(len(notifications), max_rows)} of {len(notifications)}",
        f"{'='*90}\n",
        f"{'Filing Date':<12} {'Person':<28} {'Title':<20} {'Shares':>10} {'Price':>9} {'Value':>14} {'Sale Date':<12}",
        f"{'-'*12} {'-'*28} {'-'*20} {'-'*10} {'-'*9} {'-'*14} {'-'*12}",
    ]

    for n in notifications[:max_rows]:
        price_str = f"${n['price_per_share']:.2f}" if n['price_per_share'] else 'N/A'
        value_str = f"${n['total_value']:,.0f}" if n['total_value'] else ''
        person_name = n['person_name'][:27] if n['person_name'] else 'Unknown'
        title = n['person_title'][:19] if n['person_title'] else ''
        
        lines.append(
            f"{n['filing_date']:<12} {person_name:<28} {title:<20} "
            f"{n['shares']:>9,} {price_str:>9} {value_str:>14} {n['sale_date']:<12}"
        )

    if len(notifications) > max_rows:
        lines.append(f"\n... {len(notifications) - max_rows} more notifications not shown.")

    # Summary statistics
    if notifications:
        total_shares = sum(n['shares'] for n in notifications)
        total_value = sum(n['total_value'] for n in notifications)
        lines.append(f"\nSUMMARY:")
        lines.append(f"  Total proposed sales: {len(notifications)}")
        lines.append(f"  Total shares: {total_shares:,}")
        if total_value > 0:
            lines.append(f"  Total value: ${total_value:,.0f}")

    return '\n'.join(lines)

