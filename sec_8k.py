#!/usr/bin/env python3
"""
SEC 8-K Press Release Parser
Retrieves and extracts press release text (Exhibit 99.1) from 8-K filings on EDGAR.
"""

import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from sec_utils import get_cik_from_ticker


class SEC8KClient:
    """Client for retrieving 8-K press releases from SEC EDGAR."""

    BASE_URL = "https://www.sec.gov"
    DATA_URL = "https://data.sec.gov"

    def __init__(self):
        self.headers = {'User-Agent': 'SEC-MCP CLI maxforgan@google.com'}

    def get_recent_8k_filings(self, cik: str, count: int = 5, item_filter: Optional[str] = None) -> List[Dict]:
        """
        Get recent 8-K filings from the EDGAR submissions API.

        Args:
            cik: 10-digit CIK string
            count: Max number of 8-K filings to return
            item_filter: Optional 8-K item number to filter by (e.g. '2.02')
        """
        url = f"{self.DATA_URL}/submissions/CIK{cik}.json"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        data = response.json()

        recent = data['filings']['recent']
        company_name = data.get('name', '')

        forms = recent.get('form', [])
        dates = recent.get('filingDate', [])
        accessions = recent.get('accessionNumber', [])
        items_list = recent.get('items', [''] * len(forms))

        filings = []
        for i in range(len(forms)):
            if forms[i] != '8-K':
                continue
            items_str = items_list[i] if i < len(items_list) else ''
            if item_filter and item_filter not in items_str:
                continue
            filings.append({
                'accession': accessions[i],
                'date': dates[i],
                'company': company_name,
                'items': items_str,
                'cik': cik,
            })
            if len(filings) >= count:
                break

        return filings

    def get_filing_exhibit(self, cik: str, accession: str) -> Optional[Dict]:
        """
        Find Exhibit 99.1 (or best available press release doc) in a filing.
        Tries JSON index first, falls back to HTML index parsing.
        """
        cik_int = int(cik)
        accession_nodash = accession.replace('-', '')

        # Try JSON index
        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{accession}-index.json"
        try:
            resp = requests.get(index_url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                items = resp.json().get('directory', {}).get('item', [])
                doc = self._pick_best_doc(items, key='type', name_key='name')
                if doc:
                    return doc
        except Exception:
            pass

        # Fall back to HTML index
        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{accession}-index.htm"
        try:
            resp = requests.get(index_url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return self._parse_html_index(resp.text)
        except Exception:
            pass

        return None

    def _pick_best_doc(self, items: List[Dict], key: str, name_key: str) -> Optional[Dict]:
        """Return the best press-release document from a list, prioritising EX-99.1."""
        for priority in ['EX-99.1', 'EX-99', '8-K']:
            for item in items:
                if item.get(key, '').upper().startswith(priority):
                    return item
        return items[0] if items else None

    def _parse_html_index(self, html: str) -> Optional[Dict]:
        """Parse the HTML filing index page to find an exhibit document."""
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table', class_='tableFile')
        if not table:
            return None

        rows = table.find_all('tr')[1:]
        candidates = []
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 4:
                continue
            doc_type = cols[3].text.strip()
            link = cols[2].find('a')
            if not link:
                continue
            filename = link['href'].split('/')[-1]
            candidates.append({'name': filename, 'type': doc_type})

        return self._pick_best_doc(candidates, key='type', name_key='name')

    def fetch_document_text(self, cik: str, accession: str, filename: str) -> str:
        """Fetch a filing document and extract its plain text."""
        cik_int = int(cik)
        accession_nodash = accession.replace('-', '')
        url = f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{filename}"

        resp = requests.get(url, headers=self.headers, timeout=20)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '')
        if filename.lower().endswith(('.htm', '.html')) or 'html' in content_type:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for tag in soup(['script', 'style', 'head']):
                tag.decompose()
            text = soup.get_text(separator='\n', strip=True)
        else:
            text = resp.text

        # Collapse excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]{2,}', ' ', text)
        return text.strip()

    def get_press_releases(
        self,
        ticker: str,
        count: int = 5,
        item_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get 8-K press releases for a ticker, extracting Exhibit 99.1 text.

        Args:
            ticker: Stock ticker symbol (e.g. 'AHCO')
            count: Number of 8-K filings to retrieve (default 5)
            item_filter: Optional 8-K item number filter (e.g. '2.02' for earnings)

        Returns:
            List of dicts with filing metadata and press release text
        """
        cik = get_cik_from_ticker(ticker, self.headers)
        filings = self.get_recent_8k_filings(cik, count, item_filter)

        def fetch_one(filing: Dict) -> Dict:
            cik_int = int(cik)
            accession_nodash = filing['accession'].replace('-', '')
            entry = {
                'ticker': ticker.upper(),
                'company': filing['company'],
                'date': filing['date'],
                'items': filing['items'],
                'filing_url': f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{filing['accession']}-index.htm",
                'exhibit_url': None,
                'text': None,
            }
            doc = self.get_filing_exhibit(cik, filing['accession'])
            if doc and doc.get('name'):
                filename = doc['name']
                entry['exhibit_url'] = f"{self.BASE_URL}/Archives/edgar/data/{cik_int}/{accession_nodash}/{filename}"
                try:
                    entry['text'] = self.fetch_document_text(cik, filing['accession'], filename)
                except Exception as e:
                    entry['text'] = f"[Error fetching exhibit: {e}]"
            return entry

        # Fetch exhibits in parallel (capped at 5 workers to respect SEC rate limits)
        workers = min(len(filings), 5)
        results: List[Dict] = [None] * len(filings)  # type: ignore[list-item]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {executor.submit(fetch_one, f): i for i, f in enumerate(filings)}
            for future in as_completed(future_to_idx):
                results[future_to_idx[future]] = future.result()

        return results


def format_press_releases(releases: List[Dict], max_chars_per_release: int = 8000) -> str:
    """Format 8-K press releases for display."""
    if not releases:
        return "No 8-K filings found."

    company = releases[0]['company']
    ticker = releases[0]['ticker']
    output = [f"\n{'='*80}", f"8-K Press Releases — {company} ({ticker})", f"{'='*80}"]

    for idx, r in enumerate(releases, 1):
        output.append(f"\n[{idx}] Filed: {r['date']}  |  Items: {r['items'] or 'N/A'}")
        output.append(f"    Filing index: {r['filing_url']}")
        if r['exhibit_url']:
            output.append(f"    Exhibit:      {r['exhibit_url']}")

        if r['text']:
            text = r['text']
            if len(text) > max_chars_per_release:
                text = text[:max_chars_per_release] + f"\n\n... [truncated — {len(r['text'])} chars total]"
            output.append(f"\n{text}")

        output.append(f"\n{'─'*80}")

    return "\n".join(output)
