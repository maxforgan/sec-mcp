#!/usr/bin/env python3
"""
SEC Form 4 Parser — Insider Transactions
Fetches and parses Form 4 (Statement of Changes in Beneficial Ownership)
filed by directors, officers, and 10%+ shareholders.
"""

import re
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from sec_utils import get_cik_from_ticker


# Human-readable labels for the most common transaction codes
TRANSACTION_CODE_LABELS = {
    'P': 'Purchase',
    'S': 'Sale',
    'A': 'Grant/Award',
    'D': 'Disposition to Issuer',
    'F': 'Tax Withholding (shares surrendered)',
    'G': 'Gift',
    'M': 'Option Exercise',
    'X': 'Derivative Expiration',
    'C': 'Conversion',
    'J': 'Other',
    'W': 'Inherited',
    'Z': 'Deposit/Withdrawal',
}


def _findval(element, tag: str) -> str:
    """
    Safely extract text from a Form 4 XML field.
    SEC Form 4 wraps most values in a <value> child element; falls back to
    direct element text if <value> is absent.
    """
    el = element.find(tag)
    if el is None:
        return ''
    val = el.findtext('value')
    if val is not None:
        return val.strip()
    return (el.text or '').strip()


class SECForm4Client:
    """Client for fetching and parsing Form 4 insider transaction filings."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def _get_form4_accessions(self, cik: str, count: int = 30) -> List[Dict]:
        """Return up to `count` Form 4 filings for the given CIK, newest first."""
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
            if form == '4':
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
                if form == '4':
                    filings.append({
                        'accession': page['accessionNumber'][i],
                        'date': page['filingDate'][i],
                    })
                    if len(filings) >= count:
                        break

        return filings

    def _find_xml_url(self, cik: str, accession: str) -> Optional[str]:
        """Locate the raw Form 4 XML URL in the filing index."""
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
            # Form 4 XML: ends in .xml, not the XSL viewer
            if href_lower.endswith('.xml') and 'xsl' not in href_lower:
                raw = a['href']
                return f"{self.BASE_URL}{raw}" if raw.startswith('/') else raw

        return None

    def _parse_xml(self, xml_text: str, filing_date: str) -> List[Dict]:
        """Parse ownershipDocument XML into a flat list of transaction dicts."""
        # Strip namespaces (defensive; Form 4 XML usually has none)
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
        xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
        xml_clean = re.sub(r'<(/?)[\w]+:([\w]+)', r'<\1\2', xml_clean)

        root = ET.fromstring(xml_clean)

        # Issuer
        issuer = root.find('issuer')
        issuer_name = (issuer.findtext('issuerName') or '') if issuer is not None else ''
        issuer_ticker = (issuer.findtext('issuerTradingSymbol') or '') if issuer is not None else ''

        # Reporting owner(s) — handle both single and multiple owners
        transactions = []
        for owner in root.findall('reportingOwner'):
            owner_id = owner.find('reportingOwnerId')
            owner_name = (owner_id.findtext('rptOwnerName') or '') if owner_id is not None else ''
            owner_rel = owner.find('reportingOwnerRelationship')
            owner_role = ''
            if owner_rel is not None:
                is_dir = owner_rel.findtext('isDirector') == '1'
                is_off = owner_rel.findtext('isOfficer') == '1'
                title = owner_rel.findtext('officerTitle') or ''
                if is_off and title:
                    owner_role = title
                elif is_off:
                    owner_role = 'Officer'
                elif is_dir:
                    owner_role = 'Director'
                elif owner_rel.findtext('isTenPercentOwner') == '1':
                    owner_role = '10% Owner'

            def _txn_base(txn_el, is_derivative: bool) -> Dict:
                date = _findval(txn_el, 'transactionDate') or filing_date
                security = _findval(txn_el, 'securityTitle')
                coding = txn_el.find('transactionCoding')
                code = (coding.findtext('transactionCode') or '') if coding is not None else ''
                amounts = txn_el.find('transactionAmounts')
                shares = 0
                price = 0.0
                acq_disp = ''
                if amounts is not None:
                    try:
                        shares = int(float(_findval(amounts, 'transactionShares') or '0'))
                    except ValueError:
                        pass
                    try:
                        price = float(_findval(amounts, 'transactionPricePerShare') or '0')
                    except ValueError:
                        pass
                    acq_disp = _findval(amounts, 'transactionAcquiredDisposedCode')

                post = txn_el.find('postTransactionAmounts')
                post_shares = 0
                if post is not None:
                    try:
                        post_shares = int(float(_findval(post, 'sharesOwnedFollowingTransaction') or '0'))
                    except ValueError:
                        pass

                underlying_title = ''
                underlying_shares = 0
                if is_derivative:
                    und = txn_el.find('underlyingSecurity')
                    if und is not None:
                        underlying_title = _findval(und, 'underlyingSecurityTitle')
                        try:
                            underlying_shares = int(float(
                                _findval(und, 'underlyingSecurityShares') or '0'
                            ))
                        except ValueError:
                            pass
                    post_shares = post_shares or underlying_shares

                return {
                    'date': date,
                    'filing_date': filing_date,
                    'insider_name': owner_name.title(),
                    'insider_role': owner_role,
                    'security': security or (underlying_title if is_derivative else ''),
                    'underlying': underlying_title if is_derivative else '',
                    'code': code,
                    'code_label': TRANSACTION_CODE_LABELS.get(code, code),
                    'acq_disp': acq_disp,  # A=acquired, D=disposed
                    'shares': shares,
                    'price': price,
                    'value': shares * price,
                    'shares_after': post_shares,
                    'derivative': is_derivative,
                }

            for txn_el in root.findall('nonDerivativeTable/nonDerivativeTransaction'):
                transactions.append(_txn_base(txn_el, False))
            for txn_el in root.findall('derivativeTable/derivativeTransaction'):
                transactions.append(_txn_base(txn_el, True))

        return transactions

    def get_insider_transactions(
        self,
        ticker: str,
        count: int = 40,
        transaction_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Get recent Form 4 insider transactions for a public company.

        Args:
            ticker: Stock ticker symbol.
            count: Number of Form 4 filings to process (default 40; each filing
                   may contain multiple transactions).
            transaction_types: Optional filter. Pass e.g. ['P','S'] for only
                open-market buys and sells. Default: all types.

        Returns:
            Dict with company info and list of transactions, newest first.
        """
        cik = get_cik_from_ticker(ticker, self.headers)

        # Get company name from submissions
        subs_url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        subs = requests.get(subs_url, headers=self.headers, timeout=15).json()
        company_name = subs.get('name', ticker.upper())

        filings = self._get_form4_accessions(cik, count=count)

        all_transactions = []
        for f in filings:
            try:
                xml_url = self._find_xml_url(cik, f['accession'])
                if not xml_url:
                    continue
                xml_resp = requests.get(xml_url, headers=self.headers, timeout=15)
                xml_resp.raise_for_status()
                txns = self._parse_xml(xml_resp.text, f['date'])
                all_transactions.extend(txns)
            except Exception:
                continue

        # Filter by transaction type if requested
        if transaction_types:
            types_upper = [t.upper() for t in transaction_types]
            all_transactions = [t for t in all_transactions if t['code'].upper() in types_upper]

        # Sort newest first
        all_transactions.sort(key=lambda t: t['date'], reverse=True)

        return {
            'company': company_name,
            'ticker': ticker.upper(),
            'cik': cik,
            'transactions': all_transactions,
        }


def format_insider_transactions(
    data: Dict[str, Any],
    show_derivatives: bool = True,
    max_rows: int = 50,
) -> str:
    """Format insider transactions for display."""
    if not data or not data.get('transactions'):
        return "No insider transactions found."

    txns = data['transactions']
    if not show_derivatives:
        txns = [t for t in txns if not t['derivative']]

    lines = [
        f"\n{'='*90}",
        f"Insider Transactions (Form 4) — {data['company']} ({data['ticker']})",
        f"Total transactions shown: {min(len(txns), max_rows)} of {len(txns)}",
        f"{'='*90}\n",
        f"{'Date':<12} {'Insider':<28} {'Role':<22} {'Type':<28} {'Shares':>10} {'Price':>9} {'Value':>14} {'After':>12}",
        f"{'-'*12} {'-'*28} {'-'*22} {'-'*28} {'-'*10} {'-'*9} {'-'*14} {'-'*12}",
    ]

    for t in txns[:max_rows]:
        price_str = f"${t['price']:.2f}" if t['price'] else 'N/A'
        value_str = f"${t['value']:,.0f}" if t['value'] else ''
        after_str = f"{t['shares_after']:,}" if t['shares_after'] else ''
        acq = '+' if t['acq_disp'] == 'A' else ('-' if t['acq_disp'] == 'D' else '')
        type_label = t['code_label']
        if t['derivative']:
            type_label = f"[Deriv] {type_label}"
        lines.append(
            f"{t['date']:<12} {t['insider_name'][:27]:<28} {t['insider_role'][:21]:<22} "
            f"{type_label[:27]:<28} {acq}{t['shares']:>9,} {price_str:>9} {value_str:>14} {after_str:>12}"
        )

    if len(txns) > max_rows:
        lines.append(f"\n... {len(txns) - max_rows} more transactions not shown.")

    # Summary: open-market buys vs sells
    buys = [t for t in txns if t['code'] == 'P']
    sells = [t for t in txns if t['code'] == 'S']
    if buys or sells:
        lines.append(f"\nSUMMARY — Open-Market Transactions:")
        if buys:
            lines.append(f"  Purchases: {len(buys)} transactions, "
                         f"{sum(t['shares'] for t in buys):,} shares, "
                         f"${sum(t['value'] for t in buys):,.0f} total value")
        if sells:
            lines.append(f"  Sales:     {len(sells)} transactions, "
                         f"{sum(t['shares'] for t in sells):,} shares, "
                         f"${sum(t['value'] for t in sells):,.0f} total value")

    return '\n'.join(lines)
