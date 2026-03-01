#!/usr/bin/env python3
"""
SEC Full-Text Filing Retriever
Fetches and returns plain text of 10-K, 10-Q, DEF 14A, and other filings from EDGAR.
Useful for MD&A, risk factors, business descriptions, segment tables,
footnotes, executive compensation, and other narrative disclosure not captured by XBRL.
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

from sec_utils import get_cik_from_ticker


# Canonical section aliases for 10-K items
_10K_SECTION_ALIASES = {
    'business': 'item 1',
    'risk factors': 'item 1a',
    'risk': 'item 1a',
    'properties': 'item 2',
    'legal proceedings': 'item 3',
    'mda': 'item 7',
    "management's discussion": 'item 7',
    "management discussion": 'item 7',
    'quantitative': 'item 7a',
    'financial statements': 'item 8',
    # Notes to financial statements — search for the header that appears inside Item 8
    'notes': 'notes to',
    'footnotes': 'notes to',
    'notes to financial statements': 'notes to',
    'controls': 'item 9a',
}

# For 10-Q the item numbering is different
_10Q_SECTION_ALIASES = {
    'financial statements': 'item 1',
    'mda': 'item 2',
    "management's discussion": 'item 2',
    "management discussion": 'item 2',
    'quantitative': 'item 3',
    'risk factors': 'item 1a',
    # Notes to financial statements — search for the header that appears inside Item 1
    'notes': 'notes to',
    'footnotes': 'notes to',
    'notes to financial statements': 'notes to',
}

# DEF 14A (proxy statement) section aliases
# Proxy sections are typically headed by descriptive titles, not "Item N" patterns
_DEF14A_SECTION_ALIASES = {
    # Director elections
    'directors': 'election of director',
    'board': 'board of director',
    'election': 'election of director',
    'director nominees': 'election of director',
    # Executive compensation (the CD&A and summary tables)
    'executive compensation': 'executive compensation',
    'compensation': 'executive compensation',
    'comp': 'executive compensation',
    "cd&a": 'compensation discussion',
    'compensation discussion': 'compensation discussion',
    'named executive': 'named executive',
    'neo': 'named executive',
    'summary compensation': 'summary compensation',
    # Say-on-pay advisory vote
    'say on pay': 'say-on-pay',
    'say-on-pay': 'say-on-pay',
    'advisory vote': 'advisory vote',
    # Auditor / audit committee
    'audit': 'audit committee',
    'auditor': 'ratification',
    'ratification': 'ratification',
    # Shareholder proposals
    'shareholder proposals': 'shareholder proposal',
    'proposals': 'shareholder proposal',
    'stockholder proposals': 'shareholder proposal',
    # Ownership / security holdings
    'ownership': 'beneficial ownership',
    'beneficial ownership': 'beneficial ownership',
    'stock ownership': 'beneficial ownership',
    'security ownership': 'security ownership',
    # Related-party transactions
    'related party': 'related party',
    'related parties': 'related party',
    'transactions with': 'transactions with',
    # Pay ratio
    'pay ratio': 'ceo pay ratio',
    'ceo pay ratio': 'ceo pay ratio',
    # Equity awards / outstanding option table
    'equity awards': 'outstanding equity',
    'option exercises': 'option exercise',
    'pension': 'pension benefit',
    # Meeting logistics
    'meeting': 'annual meeting',
    'proxy summary': 'proxy summary',
    'proxy statement': 'proxy statement',
}

# Map filing_type string → alias dict and end-of-section pattern
_ALIAS_MAP = {
    '10-K': _10K_SECTION_ALIASES,
    '10-Q': _10Q_SECTION_ALIASES,
    'DEF 14A': _DEF14A_SECTION_ALIASES,
    # Treat amended versions the same as originals
    '10-K/A': _10K_SECTION_ALIASES,
    '10-Q/A': _10Q_SECTION_ALIASES,
    'DEFA14A': _DEF14A_SECTION_ALIASES,
    'DEF14A': _DEF14A_SECTION_ALIASES,
    # S-1 uses same section aliases as 10-K for risk factors and business
    'S-1': _10K_SECTION_ALIASES,
    'S-1/A': _10K_SECTION_ALIASES,
}


class SECFilingTextClient:
    """Client for retrieving full text of 10-K and 10-Q filings from EDGAR."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def get_recent_filings(self, ticker: str, filing_type: str = '10-K', count: int = 1) -> List[Dict]:
        """Get recent filings metadata for a ticker using the submissions API."""
        cik = get_cik_from_ticker(ticker, self.headers)
        url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        data = response.json()

        recent = data['filings']['recent']
        company_name = data.get('name', '')

        forms = recent.get('form', [])
        dates = recent.get('filingDate', [])
        accessions = recent.get('accessionNumber', [])

        filings = []
        for i in range(len(forms)):
            if forms[i] != filing_type:
                continue
            filings.append({
                'cik': cik,
                'company': company_name,
                'accession': accessions[i],
                'date': dates[i],
                'form': forms[i],
            })
            if len(filings) >= count:
                break

        return filings

    def get_filing_document_url(self, cik: str, accession: str, filing_type: str) -> Optional[str]:
        """
        Get the URL of the primary filing document (e.g. the 10-K or 10-Q HTM file)
        from the filing index. Tries JSON index first, falls back to HTML index.
        """
        cik_int = int(cik)
        accession_nodash = accession.replace('-', '')

        # Try JSON index first
        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{accession}-index.json"
        try:
            resp = requests.get(index_url, headers=self.headers, timeout=30)
            if resp.status_code == 200:
                items = resp.json().get('directory', {}).get('item', [])
                for item in items:
                    if item.get('type', '').upper() == filing_type:
                        name = item.get('name', '')
                        if name:
                            return f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{name}"
        except Exception:
            pass

        # Fall back to HTML index
        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{accession}-index.htm"
        try:
            resp = requests.get(index_url, headers=self.headers, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                table = soup.find('table', class_='tableFile')
                if table:
                    for row in table.find_all('tr')[1:]:
                        cols = row.find_all('td')
                        if len(cols) < 4:
                            continue
                        doc_type = cols[3].text.strip()
                        if doc_type.upper() == filing_type:
                            link = cols[2].find('a')
                            if link:
                                href = link['href']
                                # Strip iXBRL viewer wrapper
                                if '/ix?doc=' in href:
                                    href = href.split('/ix?doc=')[1]
                                return self.BASE_URL + href
        except Exception:
            pass

        return None

    def fetch_document_text(self, url: str) -> str:
        """Fetch a filing document URL and return plain text."""
        resp = requests.get(url, headers=self.headers, timeout=60)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '')
        if url.lower().endswith(('.htm', '.html')) or 'html' in content_type:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for tag in soup(['script', 'style', 'head']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
        else:
            text = resp.text

        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        return text.strip()

    def extract_section(self, text: str, section: str, filing_type: str = '10-K') -> str:
        """
        Extract a named section from a filing's plain text.

        Works for 10-K, 10-Q, and DEF 14A proxy statements.
        section can be a canonical name or any registered alias.
        """
        section_lower = section.lower().strip()

        aliases = _ALIAS_MAP.get(filing_type, _10K_SECTION_ALIASES)
        normalized = aliases.get(section_lower, section_lower)

        lines = text.split('\n')
        start_idx = None

        # Find the start: a short line (header-like) containing the section identifier
        # For proxy statements, also check for common variations
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped or len(line_stripped) > 150:
                continue
            line_lower = line_stripped.lower()
            if normalized in line_lower:
                start_idx = i
                break
            # Additional checks for executive compensation in proxy statements
            if is_proxy and section_lower in ('executive compensation', 'compensation', 'comp'):
                if any(term in line_lower for term in ['executive compensation', 'compensation discussion', 
                                                       'named executive officer', 'summary compensation table']):
                    start_idx = i
                    break

        if start_idx is None:
            return f"[Section '{section}' not found. Returning full text.]\n\n{text}"

        # Find the end boundary — varies by filing type
        end_idx = None
        is_proxy = filing_type in ('DEF 14A', 'DEFA14A', 'DEF14A')

        for i in range(start_idx + 3, len(lines)):
            line_stripped = lines[i].strip()
            if not line_stripped or len(line_stripped) > 150:
                continue
            if i <= start_idx + 5:
                continue

            if is_proxy:
                # Proxy sections are separated by PROPOSAL N or standalone
                # section headers (all-caps or title-case, short, no period)
                if re.match(r'^proposal\s+\d+', line_stripped.lower()):
                    end_idx = i
                    break
                # Broad header detection for proxy: short all-caps or mixed-case heading
                # that looks like a new major section
                if (len(line_stripped) < 80
                        and line_stripped == line_stripped.upper()
                        and not line_stripped.startswith('(')
                        and len(line_stripped.split()) >= 2):
                    end_idx = i
                    break
            else:
                # 10-K / 10-Q: end at next "Item N" header
                if re.match(r'^item\s+\d+[a-z]?\.?\s*', line_stripped.lower()):
                    end_idx = i
                    break

        extracted = '\n'.join(lines[start_idx:end_idx]) if end_idx else '\n'.join(lines[start_idx:])
        return extracted.strip()

    def get_filing_text(
        self,
        ticker: str,
        filing_type: str = '10-K',
        section: Optional[str] = None,
        count: int = 1,
    ) -> List[Dict]:
        """
        Retrieve full text (or a specific section) of recent 10-K or 10-Q filings.

        Args:
            ticker: Stock ticker symbol
            filing_type: '10-K' or '10-Q'
            section: Optional section to extract. For 10-K: 'item 7'/'mda', 'item 1a'/'risk factors',
                     'item 1'/'business', 'item 8'/'financial statements'.
                     For 10-Q: 'item 2'/'mda', 'item 1'/'financial statements'.
                     Omit to return the full filing text.
            count: Number of recent filings to retrieve (default 1)

        Returns:
            List of dicts with filing metadata and text content
        """
        filings = self.get_recent_filings(ticker, filing_type=filing_type, count=count)
        results = []

        for filing in filings:
            cik_int = int(filing['cik'])
            accession_nodash = filing['accession'].replace('-', '')
            entry = {
                'ticker': ticker.upper(),
                'company': filing['company'],
                'date': filing['date'],
                'form': filing['form'],
                'section': section,
                'filing_url': f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{filing['accession']}-index.htm",
                'document_url': None,
                'text': None,
            }

            doc_url = self.get_filing_document_url(filing['cik'], filing['accession'], filing_type)
            if doc_url:
                entry['document_url'] = doc_url
                try:
                    full_text = self.fetch_document_text(doc_url)
                    if section:
                        entry['text'] = self.extract_section(full_text, section, filing_type)
                    else:
                        entry['text'] = full_text
                except requests.exceptions.Timeout:
                    entry['text'] = f"[Error: Timeout while fetching document. The document may be very large. Try reducing count or max_chars.]"
                except requests.exceptions.RequestException as e:
                    entry['text'] = f"[Error fetching document: {type(e).__name__}: {str(e)}]"
                except Exception as e:
                    entry['text'] = f"[Error processing document: {type(e).__name__}: {str(e)}]"
            else:
                entry['text'] = f"[Could not locate {filing_type} document in filing index]"

            results.append(entry)

        return results


def format_filing_text(results: List[Dict], max_chars: int = 50000) -> str:
    """Format filing text results for display."""
    if not results:
        return "No filings found."

    output = []
    for idx, r in enumerate(results, 1):
        section_label = f" — Section: {r['section']}" if r['section'] else ""
        output.append(f"\n{'='*80}")
        output.append(f"[{idx}] {r['form']}{section_label} — {r['company']} ({r['ticker']})")
        output.append(f"    Filed: {r['date']}")
        output.append(f"    Filing index: {r['filing_url']}")
        if r['document_url']:
            output.append(f"    Document:     {r['document_url']}")
        output.append(f"{'='*80}")

        if r['text']:
            text = r['text']
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n... [truncated — {len(r['text'])} chars total]"
            output.append(f"\n{text}")
        else:
            output.append("\n[No document text available]")

        output.append(f"\n{'─'*80}")

    return '\n'.join(output)
