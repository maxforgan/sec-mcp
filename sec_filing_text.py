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

        Works for 10-K, 10-Q, DEF 14A proxy statements, S-1, and other filing types.
        section can be a canonical name or any registered alias.
        """
        section_lower = section.lower().strip()
        aliases = _ALIAS_MAP.get(filing_type, _10K_SECTION_ALIASES)
        normalized = aliases.get(section_lower, section_lower)
        is_proxy = filing_type in ('DEF 14A', 'DEFA14A', 'DEF14A')
        is_10k_or_10q = filing_type in ('10-K', '10-Q', '10-K/A', '10-Q/A', 'S-1', 'S-1/A')

        lines = text.split('\n')
        start_idx = None

        # Build search patterns for better matching
        search_patterns = [normalized]
        
        # For Item-based sections (10-K, 10-Q, S-1), add pattern variations
        if is_10k_or_10q and normalized.startswith('item '):
            item_num = normalized.replace('item ', '').strip()
            # Patterns: "Item 1", "ITEM 1", "Item 1.", "Item 1 -", "Item 1:", etc.
            search_patterns.extend([
                f'item {item_num}',
                f'item {item_num}.',
                f'item {item_num}:',
                f'item {item_num} -',
                f'item {item_num}—',  # em dash
                f'item {item_num}–',  # en dash
            ])
        
        # For proxy sections, add common variations
        if is_proxy:
            if section_lower in ('executive compensation', 'compensation', 'comp'):
                search_patterns.extend([
                    'executive compensation, including compensation discussion',
                    'executive compensation',
                    'compensation discussion and analysis',
                    'compensation discussion',
                    'cd&a',
                    'named executive officer',
                    'summary compensation table',
                    'compensation of executives',
                ])
            elif section_lower in ('risk factors', 'risk'):
                search_patterns.extend(['risk factors', 'risk factor', 'risks'])
            elif section_lower in ('business',):
                search_patterns.extend(['business', 'description of business', 'business overview'])

        # Special handling for notes/footnotes (they appear within financial statements)
        if normalized == 'notes to':
            # Look for "Notes to Financial Statements" or similar
            notes_patterns = [
                'notes to financial statements',
                'notes to consolidated financial statements',
                'notes to the financial statements',
                'footnotes',
                'notes',
            ]
            for i, line in enumerate(lines):
                line_lower = line.strip().lower()
                if any(pattern in line_lower for pattern in notes_patterns):
                    # Make sure it's not in table of contents
                    if 'table of contents' not in ' '.join(lines[max(0, i-5):i]).lower():
                        start_idx = i
                        break

        # Enhanced start detection with multiple strategies
        # For executive compensation in proxy, prioritize the full section header
        if is_proxy and section_lower in ('executive compensation', 'compensation', 'comp'):
            # First, try to find the full section header
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                line_lower = line_stripped.lower()
                # Look for the full header "Executive Compensation, Including Compensation Discussion and Analysis"
                if 'executive compensation, including compensation discussion' in line_lower:
                    # Make sure it's not in a proposal
                    if 'proposal' not in line_lower:
                        start_idx = i
                        break
                # Also check for standalone "Executive Compensation" header (not in proposal)
                elif (line_lower == 'executive compensation' or 
                      line_lower.startswith('executive compensation') and 
                      'proposal' not in ' '.join(lines[max(0, i-3):i+1]).lower()):
                    start_idx = i
                    break

        # Enhanced start detection with multiple strategies
        if start_idx is None:
            for strategy in ['exact_match', 'fuzzy_match', 'context_match']:
                for i, line in enumerate(lines):
                    line_stripped = line.strip()
                    if not line_stripped:
                        continue
                    
                    line_lower = line_stripped.lower()
                    
                    # Skip table of contents
                    if 'table of contents' in line_lower and i < 50:
                        continue
                    
                    # Skip proposal headers for executive compensation
                    if is_proxy and section_lower in ('executive compensation', 'compensation', 'comp'):
                        if 'proposal' in line_lower and 'executive compensation, including' not in line_lower:
                            continue
                    
                    # Strategy 1: Exact match in line
                    if strategy == 'exact_match':
                        if len(line_stripped) <= 150:
                            for pattern in search_patterns:
                                if pattern in line_lower:
                                    # Additional validation: not in TOC
                                    context = ' '.join(lines[max(0, i-5):i+1]).lower()
                                    if (i > 50 or 'table of contents' not in context):
                                        start_idx = i
                                        break
                            if start_idx is not None:
                                break
                    
                    # Strategy 2: Fuzzy match (handle variations, punctuation)
                    elif strategy == 'fuzzy_match' and start_idx is None:
                        if len(line_stripped) <= 200:
                            # Remove punctuation and normalize
                            line_normalized = re.sub(r'[^\w\s]', ' ', line_lower)
                            for pattern in search_patterns:
                                pattern_normalized = re.sub(r'[^\w\s]', ' ', pattern)
                                # Check if pattern words appear in order
                                pattern_words = pattern_normalized.split()
                                line_words = line_normalized.split()
                                if len(pattern_words) > 0:
                                    # Check if all pattern words appear in line
                                    if all(any(pw in lw or lw in pw for lw in line_words) 
                                           for pw in pattern_words if len(pw) > 2):
                                        if i > 50 or 'table of contents' not in ' '.join(lines[max(0, i-10):i+1]).lower():
                                            start_idx = i
                                            break
                            if start_idx is not None:
                                break
                    
                    # Strategy 3: Context match (look at current + next line)
                    elif strategy == 'context_match' and start_idx is None:
                        if i < len(lines) - 1:
                            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
                            combined = f"{line_stripped} {next_line}".lower()
                            if len(combined) <= 250:
                                for pattern in search_patterns:
                                    if pattern in combined:
                                        if i > 50 or 'table of contents' not in ' '.join(lines[max(0, i-10):i+2]).lower():
                                            start_idx = i
                                            break
                            if start_idx is not None:
                                break
                
                if start_idx is not None:
                    break

        if start_idx is None:
            return f"[Section '{section}' not found. Returning full text.]\n\n{text}"

        # Enhanced end detection
        end_idx = None
        min_lines_after_start = 10  # Minimum lines to scan before considering end

        for i in range(start_idx + min_lines_after_start, len(lines)):
            line_stripped = lines[i].strip()
            if not line_stripped:
                continue
            
            line_lower = line_stripped.lower()
            
            if is_proxy:
                # Proxy sections: end at PROPOSAL N, or major section headers
                if re.match(r'^proposal\s+\d+', line_lower):
                    end_idx = i
                    break
                
                # For executive compensation, continue through related subsections
                if section_lower in ('executive compensation', 'compensation', 'comp'):
                    # Don't end at these compensation-related headers (they're part of the section)
                    compensation_subheaders = [
                        'compensation discussion',
                        'compensation discussion and analysis',
                        'cd&a',
                        'named executive officer',
                        'summary compensation',
                        'grants of plan-based awards',
                        'outstanding equity awards',
                        'option exercises',
                        'pension benefits',
                        'nonqualified deferred compensation',
                        'potential payments upon termination',
                        'pay ratio',
                        'compensation committee',
                        'report of the compensation',
                    ]
                    
                    # Check if this line is a compensation subheader
                    is_comp_subheader = any(sub in line_lower for sub in compensation_subheaders)
                    
                    # End at major sections that are NOT part of compensation
                    # Check for truly different sections that come after executive compensation
                    different_sections = [
                        'director compensation',  # This comes after executive compensation
                        'security ownership',
                        'beneficial ownership',
                        'shareholder proposal',
                        'shareholder proposals',
                        'proposal six',  # Proposals start after compensation
                        'proposal seven',
                        'proposal eight',
                        'proposal nine',
                        'proposal ten',
                        'audit',
                        'ratification',
                        'election of director',
                    ]
                    
                    # Check if this is a different section
                    # For "Director Compensation", make sure it's a standalone header, not in a table
                    is_different_section = False
                    if 'director compensation' in line_lower:
                        # Only end if it's a clear section header (standalone, short line, not in table)
                        if (len(line_stripped) < 80 and 
                            (line_stripped == line_stripped.upper() or 
                             line_stripped.lower() == 'director compensation')):
                            # Check context - make sure it's not in a table or list
                            context_lines = ' '.join(lines[max(0, i-3):i+3]).lower()
                            if 'table' not in context_lines or 'director compensation' == line_stripped.lower():
                                is_different_section = True
                    else:
                        # For other different sections
                        is_different_section = any(diff in line_lower for diff in different_sections if diff != 'director compensation')
                    
                    if (is_different_section and 
                        not is_comp_subheader and
                        len(line_stripped) < 150):
                        # Make sure it's not just a mention in text
                        if (line_stripped == line_stripped.upper() or 
                            line_lower in [d.lower() for d in different_sections]):
                            # Additional check: make sure we've seen substantial compensation content
                            # Don't end too early (at least 1000 chars should be extracted)
                            if i - start_idx > 50:  # At least 50 lines
                                end_idx = i
                                break
                else:
                    # For other proxy sections, use standard detection
                    # Major section headers (all caps, short, 2+ words)
                    if (len(line_stripped) < 100
                            and line_stripped == line_stripped.upper()
                            and not line_stripped.startswith('(')
                            and len(line_stripped.split()) >= 2
                            and not any(term in line_lower for term in ['table of', 'page', 'exhibit'])):
                        # Make sure it's not a continuation of current section
                        if not any(pattern in line_lower for pattern in search_patterns):
                            end_idx = i
                            break
            elif is_10k_or_10q:
                # 10-K/10-Q: end at next Item header (with variations)
                item_patterns = [
                    r'^item\s+(\d+)([a-z])?\.?\s*',
                    r'^item\s+(\d+)([a-z])?:\s*',
                    r'^item\s+(\d+)([a-z])?\s*[-—–]',
                ]
                
                # Extract current item number and sub-item from normalized pattern
                current_item_num = None
                current_sub_item = None
                if normalized.startswith('item '):
                    match = re.search(r'item\s+(\d+)([a-z])?', normalized)
                    if match:
                        current_item_num = match.group(1)
                        current_sub_item = match.group(2) if match.lastindex >= 2 else None
                
                for pattern in item_patterns:
                    match = re.match(pattern, line_lower)
                    if match:
                        found_item_num = match.group(1)
                        found_sub_item = match.group(2) if match.lastindex >= 2 else None
                        
                        # End if we find a different main item number
                        # Item 1A should end at Item 2, not Item 1B
                        if current_item_num:
                            try:
                                current_num = int(current_item_num)
                                found_num = int(found_item_num)
                                # End if we hit a different main item (1 -> 2, not 1A -> 1B)
                                if found_num > current_num:
                                    end_idx = i
                                    break
                                # Also end if same number but no sub-item and we had one
                                # (e.g., Item 1A ends at Item 1 if it appears, though rare)
                                elif found_num == current_num and not found_sub_item and current_sub_item:
                                    # But only if it's clearly a new section, not continuation
                                    # Check if line looks like a header
                                    if len(line_stripped) < 100 and not line_stripped.startswith('('):
                                        end_idx = i
                                        break
                            except ValueError:
                                pass
                        else:
                            # If we don't have a current item number, end at any item
                            end_idx = i
                            break
                
                if end_idx is not None:
                    break
                
                # Also end at "PART" headers (for S-1 and some 10-Ks)
                if re.match(r'^part\s+[ivx]+', line_lower):
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
