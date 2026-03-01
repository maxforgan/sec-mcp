#!/usr/bin/env python3
"""
SEC SC 13D/13G Parser — Large Shareholder Ownership Disclosures
Fetches and parses SC 13D (activist) and SC 13G (passive) filings
to extract ownership percentages and filing dates.
"""

import re
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup

from sec_utils import get_cik_from_ticker


def _findval(element, tag: str) -> str:
    """Safely extract text from an XML field."""
    el = element.find(tag)
    if el is None:
        return ''
    val = el.findtext('value')
    if val is not None:
        return val.strip()
    return (el.text or '').strip()


class SEC13D13GClient:
    """Client for fetching and parsing SC 13D and SC 13G ownership filings."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def _get_13d_13g_accessions(self, cik: str, filing_type: str = 'SC 13G', count: int = 30) -> List[Dict]:
        """Return up to `count` SC 13D/13G filings for the given CIK, newest first."""
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
            if form == filing_type:
                filings.append({'accession': accessions[i], 'date': dates[i], 'form': form})
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
                if form == filing_type:
                    filings.append({
                        'accession': page['accessionNumber'][i],
                        'date': page['filingDate'][i],
                        'form': form,
                    })
                    if len(filings) >= count:
                        break

        return filings

    def _find_xml_url(self, cik: str, accession: str) -> Optional[str]:
        """Locate the raw SC 13D/13G XML URL in the filing index."""
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
            # SC 13D/13G XML: ends in .xml, not the XSL viewer
            if href_lower.endswith('.xml') and 'xsl' not in href_lower:
                raw = a['href']
                return f"{self.BASE_URL}{raw}" if raw.startswith('/') else raw

        return None

    def _parse_xml(self, xml_text: str, filing_date: str, filing_type: str) -> Dict[str, Any]:
        """Parse SC 13D/13G ownershipDocument XML into structured data."""
        # Strip namespaces
        xml_clean = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', xml_text)
        xml_clean = re.sub(r'\s+\w+:\w+="[^"]*"', '', xml_clean)
        xml_clean = re.sub(r'<(/?)[\w]+:([\w]+)', r'<\1\2', xml_clean)

        try:
            root = ET.fromstring(xml_clean)
        except ET.ParseError:
            # If XML parsing fails, try to extract from text
            return self._parse_text_fallback(xml_text, filing_date, filing_type)

        # Issuer information
        issuer = root.find('issuer')
        issuer_name = (issuer.findtext('issuerName') or '') if issuer is not None else ''
        issuer_cik = (issuer.findtext('issuerCik') or '') if issuer is not None else ''
        issuer_ticker = (issuer.findtext('issuerTradingSymbol') or '') if issuer is not None else ''

        # Reporting owner(s)
        owners = []
        for owner in root.findall('reportingOwner'):
            owner_id = owner.find('reportingOwnerId')
            owner_name = (owner_id.findtext('rptOwnerName') or '') if owner_id is not None else ''
            owner_cik = (owner_id.findtext('rptOwnerCik') or '') if owner_id is not None else ''

            # Ownership information
            ownership_info = owner.find('reportingOwnerRelationship')
            if ownership_info is not None:
                is_director = ownership_info.findtext('isDirector') == '1'
                is_officer = ownership_info.findtext('isOfficer') == '1'
                is_ten_percent = ownership_info.findtext('isTenPercentOwner') == '1'
            else:
                is_director = False
                is_officer = False
                is_ten_percent = False

            # Get ownership percentage and shares
            ownership_amounts = owner.find('ownershipNature')
            shares_owned = 0
            percent_owned = 0.0
            if ownership_amounts is not None:
                shares_el = ownership_amounts.find('sharesOwned')
                if shares_el is not None:
                    shares_val = _findval(shares_el, 'shares')
                    try:
                        shares_owned = int(float(shares_val.replace(',', '')) if shares_val else 0)
                    except (ValueError, AttributeError):
                        pass

                percent_el = ownership_amounts.find('percentOwned')
                if percent_el is not None:
                    percent_val = _findval(percent_el, 'percent')
                    try:
                        percent_owned = float(percent_val.replace('%', '').replace(',', '')) if percent_val else 0.0
                    except (ValueError, AttributeError):
                        pass

            owners.append({
                'owner_name': owner_name,
                'owner_cik': owner_cik,
                'shares_owned': shares_owned,
                'percent_owned': percent_owned,
                'is_director': is_director,
                'is_officer': is_officer,
                'is_ten_percent_owner': is_ten_percent,
            })

        # Purpose of transaction (SC 13D specific)
        purpose = ''
        if filing_type == 'SC 13D':
            purpose_el = root.find('purposeOfTransaction')
            if purpose_el is not None:
                purpose = (purpose_el.text or '').strip()

        return {
            'issuer_name': issuer_name,
            'issuer_cik': issuer_cik,
            'issuer_ticker': issuer_ticker,
            'filing_date': filing_date,
            'filing_type': filing_type,
            'owners': owners,
            'purpose': purpose,
        }

    def _parse_text_fallback(self, text: str, filing_date: str, filing_type: str) -> Dict[str, Any]:
        """Fallback parser for text-based SC 13D/13G filings when XML is not available."""
        # Try to extract ownership percentage from text patterns
        percent_pattern = r'(\d+\.?\d*)\s*%'
        shares_pattern = r'(\d{1,3}(?:,\d{3})*)\s*(?:shares|common\s+shares)'
        
        percent_match = re.search(percent_pattern, text, re.IGNORECASE)
        shares_match = re.search(shares_pattern, text, re.IGNORECASE)
        
        percent_owned = 0.0
        shares_owned = 0
        
        if percent_match:
            try:
                percent_owned = float(percent_match.group(1))
            except ValueError:
                pass
        
        if shares_match:
            try:
                shares_owned = int(shares_match.group(1).replace(',', ''))
            except ValueError:
                pass
        
        # Try to extract owner name
        owner_name = ''
        name_patterns = [
            r'reporting\s+person[:\s]+([A-Z][A-Za-z\s,&]+)',
            r'name[:\s]+([A-Z][A-Za-z\s,&]+)',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                owner_name = match.group(1).strip()
                break
        
        return {
            'issuer_name': '',
            'issuer_cik': '',
            'issuer_ticker': '',
            'filing_date': filing_date,
            'filing_type': filing_type,
            'owners': [{
                'owner_name': owner_name or 'Unknown',
                'owner_cik': '',
                'shares_owned': shares_owned,
                'percent_owned': percent_owned,
                'is_director': False,
                'is_officer': False,
                'is_ten_percent_owner': True,
            }],
            'purpose': '',
        }

    def get_ownership_disclosures(
        self,
        ticker: str,
        filing_type: str = 'SC 13G',
        count: int = 20,
    ) -> Dict[str, Any]:
        """
        Get recent SC 13D/13G ownership disclosures for a public company.

        Args:
            ticker: Stock ticker symbol.
            filing_type: 'SC 13D' (activist) or 'SC 13G' (passive, default).
            count: Number of filings to process (default 20).

        Returns:
            Dict with company info and list of ownership disclosures, newest first.
        """
        cik = get_cik_from_ticker(ticker, self.headers)

        # Get company name from submissions
        subs_url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        subs = requests.get(subs_url, headers=self.headers, timeout=15).json()
        company_name = subs.get('name', ticker.upper())

        filings = self._get_13d_13g_accessions(cik, filing_type=filing_type, count=count)

        all_disclosures = []
        for f in filings:
            try:
                xml_url = self._find_xml_url(cik, f['accession'])
                if xml_url:
                    xml_resp = requests.get(xml_url, headers=self.headers, timeout=15)
                    xml_resp.raise_for_status()
                    disclosure = self._parse_xml(xml_resp.text, f['date'], f['form'])
                    disclosure['accession'] = f['accession']
                    all_disclosures.append(disclosure)
                else:
                    # Fallback: try to get text and parse it
                    try:
                        from sec_filing_text import SECFilingTextClient
                        text_client = SECFilingTextClient()
                        text_results = text_client.get_filing_text(ticker, filing_type=f['form'], count=1)
                        if text_results and text_results[0].get('text'):
                            disclosure = self._parse_text_fallback(
                                text_results[0]['text'], f['date'], f['form']
                            )
                            disclosure['accession'] = f['accession']
                            all_disclosures.append(disclosure)
                    except Exception:
                        continue
            except Exception:
                continue

        # Sort newest first
        all_disclosures.sort(key=lambda d: d['filing_date'], reverse=True)

        return {
            'company': company_name,
            'ticker': ticker.upper(),
            'cik': cik,
            'disclosures': all_disclosures,
        }


def format_ownership_disclosures(
    data: Dict[str, Any],
    max_rows: int = 50,
) -> str:
    """Format SC 13D/13G ownership disclosures for display."""
    if not data or not data.get('disclosures'):
        return "No ownership disclosures found."

    disclosures = data['disclosures']

    lines = [
        f"\n{'='*90}",
        f"Ownership Disclosures ({data.get('disclosures', [{}])[0].get('filing_type', 'SC 13D/13G')}) — {data['company']} ({data['ticker']})",
        f"Total disclosures shown: {min(len(disclosures), max_rows)} of {len(disclosures)}",
        f"{'='*90}\n",
        f"{'Filing Date':<12} {'Owner Name':<35} {'% Owned':>10} {'Shares':>15} {'Type':<12}",
        f"{'-'*12} {'-'*35} {'-'*10} {'-'*15} {'-'*12}",
    ]

    for d in disclosures[:max_rows]:
        for owner in d.get('owners', []):
            owner_name = owner.get('owner_name', 'Unknown')[:34]
            percent = owner.get('percent_owned', 0.0)
            shares = owner.get('shares_owned', 0)
            filing_type = d.get('filing_type', '')
            
            percent_str = f"{percent:.2f}%" if percent > 0 else "N/A"
            shares_str = f"{shares:,}" if shares > 0 else "N/A"
            
            lines.append(
                f"{d['filing_date']:<12} {owner_name:<35} {percent_str:>10} {shares_str:>15} {filing_type:<12}"
            )
            
            # Add purpose for SC 13D filings
            if filing_type == 'SC 13D' and d.get('purpose'):
                purpose = d['purpose'][:70]
                lines.append(f"{' '*12} Purpose: {purpose}")

    if len(disclosures) > max_rows:
        lines.append(f"\n... {len(disclosures) - max_rows} more disclosures not shown.")

    # Summary statistics
    if disclosures:
        total_owners = sum(len(d.get('owners', [])) for d in disclosures)
        avg_percent = sum(
            sum(o.get('percent_owned', 0) for o in d.get('owners', []))
            for d in disclosures
        ) / total_owners if total_owners > 0 else 0
        
        lines.append(f"\nSUMMARY:")
        lines.append(f"  Total filings: {len(disclosures)}")
        lines.append(f"  Total owners: {total_owners}")
        if avg_percent > 0:
            lines.append(f"  Average ownership: {avg_percent:.2f}%")

    return '\n'.join(lines)

